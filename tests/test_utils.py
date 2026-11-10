"""utils.py 的纯函数测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from nana.utils import (
    TrackName,
    audio_files,
    audio_stems,
    lrc_stems,
    normalize_for_match,
    parse_track_name,
    sanitize_filename,
    select_new_titles,
    similarity,
    strip_brackets,
)


def test_sanitize_filename_replaces_illegal_chars():
    assert sanitize_filename('A/B\\C:D*E?F"G<H>I|J') == "A-B-C-D-E-F-G-H-I-J"


def test_sanitize_filename_strips_spaces_and_dots():
    assert sanitize_filename("  歌名.  ") == "歌名"


def test_sanitize_filename_limits_length():
    cleaned = sanitize_filename("长" * 400, max_length=20)
    assert len(cleaned) == 20


def test_sanitize_filename_never_empty():
    assert sanitize_filename("") == "untitled"
    assert sanitize_filename("///") == "---"


def test_parse_track_name_splits_artist():
    track = parse_track_name("夜に駆ける - Cover- ななひら.mp3", " - Cover- ")
    assert track == TrackName(
        stem="夜に駆ける - Cover- ななひら", title="夜に駆ける", artist="ななひら"
    )


def test_parse_track_name_without_split_word_keeps_stem():
    track = parse_track_name("ただの曲.mp3", " - Cover- ")
    assert track.title == track.stem == "ただの曲"
    assert track.artist is None


def test_parse_track_name_empty_artist_falls_back():
    track = parse_track_name("曲 - Cover- .mp3", " - Cover- ")
    assert track.title == track.stem
    assert track.artist is None


def test_parse_track_name_handles_other_extensions():
    track = parse_track_name("歌 - Cover- 人.flac", " - Cover- ")
    assert track.title == "歌"
    assert track.artist == "人"


def test_strip_brackets_removes_versions():
    assert strip_brackets("歌名 (TV Size) [Remix]") == "歌名"
    assert strip_brackets("歌名（完整版）") == "歌名"


def test_normalize_for_match_unifies_width_and_case():
    assert normalize_for_match("ＡＢＣ　（live）") == "abc"


def test_similarity_identical_and_contained():
    assert similarity("夜に駆ける", "夜に駆ける") == 100.0
    assert similarity("夜に駆ける", "夜に駆ける (TV size)") >= 90.0


def test_similarity_different_songs_is_low():
    assert similarity("夜に駆ける", "全然违う歌") < 50.0


def test_similarity_empty_returns_zero():
    assert similarity("", "x") == 0.0
    assert similarity("x", "") == 0.0


def test_select_new_titles_dedupes_and_skips_existing():
    assert select_new_titles(["A", "B", "A", "C"], {"b"}) == ["A", "C"]


def test_select_new_titles_uses_cleaned_filenames():
    # 清洗后会变成同名文件的两个标题只应保留一个
    assert select_new_titles(["歌/名", "歌-名", "歌-名"], set()) == ["歌/名"]


def test_audio_and_lrc_scanning(tmp_path: Path):
    (tmp_path / "a.mp3").write_text("")
    (tmp_path / "b.flac").write_text("")
    (tmp_path / "c.txt").write_text("")
    (tmp_path / "a.lrc").write_text("")
    assert [path.name for path in audio_files(tmp_path)] == ["a.mp3", "b.flac"]
    assert audio_stems(tmp_path) == {"a", "b"}
    assert lrc_stems(tmp_path) == {"a"}


def test_scanning_missing_directory_returns_empty(tmp_path: Path):
    missing = tmp_path / "nope"
    assert audio_files(missing) == []
    assert audio_stems(missing) == set()
    assert lrc_stems(missing) == set()