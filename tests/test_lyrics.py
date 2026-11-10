"""lyrics.py 测试：响应解析、匹配打分、API 降级顺序与离线的歌词流程。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nana.config import Config, LyricsConfig
from nana.lyrics import (
    LyricsClient,
    LyricsError,
    LyricsUnavailable,
    SongCandidate,
    find_lyrics,
    parse_search_response,
    pick_best_candidate,
    write_log,
)

SEARCH_PAYLOAD = json.dumps(
    {
        "result": {
            "songs": [
                {"id": 1, "name": "夜に駆ける", "artists": [{"name": "YOASOBI"}]},
                {"id": 2, "name": "夜に駆ける (Remix)", "artists": [{"name": "某人"}]},
            ]
        }
    },
    ensure_ascii=False,
).encode("utf-8")


def make_client(apis=("https://a.example", "https://b.example"), fetcher=None, retries=0):
    config = LyricsConfig(search_apis=apis, retries=retries, timeout=1.0)
    return LyricsClient(config, fetcher=fetcher, sleep=lambda seconds: None)


def test_parse_search_response():
    candidates = parse_search_response(SEARCH_PAYLOAD)
    assert [candidate.song_id for candidate in candidates] == ["1", "2"]
    assert candidates[0].artists == ("YOASOBI",)


def test_parse_search_response_invalid_json():
    with pytest.raises(LyricsError, match="解析"):
        parse_search_response(b"not json")


def test_parse_search_response_empty_result():
    assert parse_search_response(b'{"result": {"songs": []}}') == []
    assert parse_search_response(b"{}") == []


def test_pick_best_candidate_chooses_highest_score():
    candidates = [
        SongCandidate("1", "全然违う歌", ("某人",)),
        SongCandidate("2", "夜に駆ける", ("YOASOBI",)),
    ]
    match = pick_best_candidate("夜に駆ける", candidates, 75.0)
    assert match is not None
    assert match.candidate.song_id == "2"
    assert match.score >= 90.0


def test_pick_best_candidate_below_threshold_returns_none():
    candidates = [SongCandidate("1", "别的歌", ("某人",))]
    assert pick_best_candidate("夜に駆ける", candidates, 90.0) is None
    assert pick_best_candidate("夜に駆ける", [], 75.0) is None


def test_pick_best_candidate_artist_bonus():
    candidates = [
        SongCandidate("1", "夜に駆ける", ("YOASOBI",)),
        SongCandidate("2", "夜に駆ける", ("别人",)),
    ]
    match = pick_best_candidate("夜に駆ける YOASOBI", candidates, 75.0)
    assert match is not None
    assert match.candidate.song_id == "1"


def test_search_falls_back_to_second_api():
    requested = []

    def fetcher(url, timeout):
        requested.append(url)
        if url.startswith("https://a.example"):
            raise OSError("connection refused")
        return SEARCH_PAYLOAD

    client = make_client(fetcher=fetcher)
    candidates = client.search("夜に駆ける")
    assert len(candidates) == 2
    assert requested[0].startswith("https://a.example")
    assert requested[1].startswith("https://b.example")


def test_search_all_apis_down_raises_with_all_urls():
    def fetcher(url, timeout):
        raise OSError("down")

    client = make_client(fetcher=fetcher)
    with pytest.raises(LyricsUnavailable) as excinfo:
        client.search("夜に駆ける")
    message = str(excinfo.value)
    assert "https://a.example" in message
    assert "https://b.example" in message


def test_search_retries_same_api_before_fallback():
    calls = []

    def fetcher(url, timeout):
        calls.append(url)
        if len(calls) == 1:
            raise OSError("first try down")
        return SEARCH_PAYLOAD

    client = make_client(fetcher=fetcher, retries=1)
    assert client.search("夜に駆ける")
    assert calls[0] == calls[1]


def test_search_falls_through_empty_api():
    requested = []

    def fetcher(url, timeout):
        requested.append(url)
        if url.startswith("https://a.example"):
            return b'{"result": {"songs": []}}'
        return SEARCH_PAYLOAD

    client = make_client(fetcher=fetcher)
    assert client.search("夜に駆ける")
    assert requested[0].startswith("https://a.example")
    assert requested[-1].startswith("https://b.example")


def test_fetch_lyric_returns_text():
    client = make_client(fetcher=lambda url, timeout: json.dumps({"lyric": "[00:01]la"}).encode())
    assert client.fetch_lyric("1") == "[00:01]la"


def test_fetch_lyric_nolyric_returns_none():
    client = make_client(fetcher=lambda url, timeout: b'{"nolyric": true}')
    assert client.fetch_lyric("1") is None


def test_fetch_lyric_empty_lyric_returns_none():
    client = make_client(fetcher=lambda url, timeout: b'{"lyric": ""}')
    assert client.fetch_lyric("1") is None


def test_translation_requires_successful_search():
    client = make_client(fetcher=lambda url, timeout: SEARCH_PAYLOAD)
    with pytest.raises(LyricsError, match="搜索"):
        client.fetch_translation("1")


def test_translation_uses_search_base():
    requested = []

    def fetcher(url, timeout):
        requested.append(url)
        if "/search" in url:
            return SEARCH_PAYLOAD
        return json.dumps({"tlyric": {"lyric": "[00:01]translated"}}, ensure_ascii=False).encode()

    client = make_client(fetcher=fetcher)
    client.search("夜に駆ける")
    lyric = client.fetch_translation("1")
    assert lyric == "[00:01]translated"
    assert requested[-1] == "https://a.example/lyric?id=1"


class FakeClient:
    """离线假客户端，记录搜索关键词。"""

    def __init__(self, candidates, lyric):
        self.candidates = candidates
        self.lyric = lyric
        self.searched: list[str] = []

    def search(self, keyword):
        self.searched.append(keyword)
        return tuple(self.candidates)

    def fetch_lyric(self, song_id):
        return self.lyric

    def fetch_translation(self, song_id):
        return self.lyric


def test_find_lyrics_writes_lrc_and_skips_existing(tmp_path: Path):
    songs = tmp_path / "songs"
    songs.mkdir()
    (songs / "夜に駆ける - Cover- ななひら.mp3").write_text("")
    (songs / "既存曲 - Cover- 誰.mp3").write_text("")
    (songs / "既存曲 - Cover- 誰.lrc").write_text("old")

    client = FakeClient([SongCandidate("1", "夜に駆ける", ("YOASOBI",))], "[00:01]la")
    report = find_lyrics(Config(lyrics=LyricsConfig(songs_dir=songs)), client=client)

    assert client.searched == ["夜に駆ける"]
    assert (songs / "夜に駆ける - Cover- ななひら.lrc").read_text(encoding="utf-8") == "[00:01]la"
    assert len(report.written) == 1
    assert len(report.skipped_existing) == 1
    assert report.ok


def test_find_lyrics_low_score_skips(tmp_path: Path):
    songs = tmp_path / "songs"
    songs.mkdir()
    (songs / "別の曲 - Cover- 人.mp3").write_text("")
    client = FakeClient([SongCandidate("1", "夜に駆ける", ("YOASOBI",))], "[00:01]la")
    report = find_lyrics(Config(lyrics=LyricsConfig(songs_dir=songs)), client=client)
    assert report.written == []
    assert len(report.low_score) == 1
    assert not (songs / "別の曲.lrc").exists()


def test_find_lyrics_no_lyric_marks_pure_music(tmp_path: Path):
    songs = tmp_path / "songs"
    songs.mkdir()
    (songs / "夜に駆ける - Cover- ななひら.mp3").write_text("")
    client = FakeClient([SongCandidate("1", "夜に駆ける", ("YOASOBI",))], None)
    report = find_lyrics(Config(lyrics=LyricsConfig(songs_dir=songs)), client=client)
    assert len(report.no_lyric) == 1
    assert report.written == []


def test_find_lyrics_records_client_errors(tmp_path: Path):
    songs = tmp_path / "songs"
    songs.mkdir()
    (songs / "夜に駆ける - Cover- ななひら.mp3").write_text("")

    class BrokenClient:
        def search(self, keyword):
            raise LyricsUnavailable("所有搜索 API 均不可用")

        def fetch_lyric(self, song_id):
            raise AssertionError("不应被调用")

        def fetch_translation(self, song_id):
            raise AssertionError("不应被调用")

    report = find_lyrics(Config(lyrics=LyricsConfig(songs_dir=songs)), client=BrokenClient())
    assert len(report.failed) == 1
    assert not report.ok


def test_find_lyrics_requires_songs_dir(tmp_path: Path):
    with pytest.raises(LyricsError, match="歌曲目录不存在"):
        find_lyrics(Config(lyrics=LyricsConfig(songs_dir=tmp_path / "nope")))


def test_write_log_appends_sections(tmp_path: Path):
    log_path = tmp_path / "musicinfo.log"
    config = Config(lyrics=LyricsConfig(songs_dir=tmp_path, lrc_dir=tmp_path))
    from nana.lyrics import LyricsReport

    report = LyricsReport(
        written=[tmp_path / "a.lrc"],
        low_score=[tmp_path / "b.lrc"],
        failed=[(tmp_path / "c.mp3", "网络错误")],
    )
    write_log(report, log_path, config)
    write_log(report, log_path, config)
    text = log_path.read_text(encoding="utf-8")
    assert text.count("=====") == 4  # 两次运行各有一个起止分隔行
    assert "[setting]" in text
    assert "a.lrc" in text
    assert "网络错误" in text