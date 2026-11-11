"""歌词搜索、匹配与写入。

歌词匹配策略与 API 用法衍生自 RavelloH/music-lrc-match
（https://github.com/RavelloH/music-lrc-match，AGPL-3.0）：
原项目由 RavelloH 编写，Dax233 在 NanaMusicDownloader 中修改沿用，
本次翻新将其重构为带超时、重试与多源降级的客户端，
去掉了旧版靠全局 error 计数 + 递归 + input 询问的可用性探测。
"""

from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Sequence

from .config import Config, LyricsConfig
from .utils import audio_files, lrc_stems, parse_track_name, similarity

log = logging.getLogger(__name__)

USER_AGENT = "NanaMusicDownloader/2.0 (+https://github.com/Dax233/NanaMusicDownloader)"
Fetcher = Callable[[str, float], bytes]


class LyricsError(RuntimeError):
    """歌词流程中的可预期错误。"""


class LyricsUnavailable(LyricsError):
    """搜索 / 歌词 API 全部不可用。"""


@dataclass(frozen=True)
class SongCandidate:
    """搜索 API 返回的一条候选歌曲。"""

    song_id: str
    name: str
    artists: tuple[str, ...] = ()


@dataclass(frozen=True)
class MatchResult:
    """带分数的匹配结果。"""

    candidate: SongCandidate
    score: float


@dataclass
class LyricsReport:
    """一次歌词流程的结果汇总。"""

    written: list[Path] = field(default_factory=list)
    skipped_existing: list[Path] = field(default_factory=list)
    low_score: list[Path] = field(default_factory=list)
    no_lyric: list[Path] = field(default_factory=list)
    failed: list[tuple[Path, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed


def _load_json(payload: bytes | str) -> dict:
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8", errors="replace")
    try:
        data = json.loads(payload)
    except (TypeError, ValueError) as exc:
        raise LyricsError(f"解析 API 响应失败：{exc}") from exc
    if not isinstance(data, dict):
        raise LyricsError("API 响应不是 JSON 对象")
    return data


def parse_search_response(payload: bytes | str) -> list[SongCandidate]:
    """解析网易云风格的搜索响应（result.songs）。"""
    data = _load_json(payload)
    result = data.get("result") or {}
    if not isinstance(result, dict):
        return []
    songs = result.get("songs") or []
    candidates: list[SongCandidate] = []
    for song in songs:
        if not isinstance(song, dict):
            continue
        song_id = song.get("id")
        name = str(song.get("name", "")).strip()
        if song_id is None or not name:
            continue
        artists = tuple(
            str(artist.get("name", "")).strip()
            for artist in song.get("artists", [])
            if isinstance(artist, dict) and artist.get("name")
        )
        candidates.append(SongCandidate(song_id=str(song_id), name=name, artists=artists))
    return candidates


def candidate_score(file_title: str, candidate: SongCandidate) -> float:
    """给候选打分：歌名相似度 + 歌手命中加成。"""
    score = similarity(file_title, candidate.name)
    lowered = file_title.casefold()
    if any(artist.casefold() in lowered for artist in candidate.artists if artist):
        score = min(100.0, score + 5.0)
    return round(score, 1)


def pick_best_candidate(
    file_title: str,
    candidates: Sequence[SongCandidate],
    threshold: float = 75.0,
) -> MatchResult | None:
    """在候选里挑分最高的一条；低于阈值返回 None。"""
    best: MatchResult | None = None
    for candidate in candidates:
        score = candidate_score(file_title, candidate)
        if best is None or score > best.score:
            best = MatchResult(candidate=candidate, score=score)
    if best is None or best.score < threshold:
        return None
    return best


def _default_fetcher(url: str, timeout: float) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


class LyricsClient:
    """带超时、重试与多 API 降级的歌词客户端。

    搜索时按 search_apis 顺序尝试，前一个请求失败或无结果才换下一个；
    歌词 / 翻译接口使用同样的超时重试策略。
    """

    def __init__(
        self,
        config: LyricsConfig,
        *,
        fetcher: Fetcher | None = None,
        sleep: Callable[[float], None] = time.sleep,
        logger: logging.Logger = log,
    ) -> None:
        self.config = config
        self._fetch = fetcher or _default_fetcher
        self._sleep = sleep
        self.logger = logger
        self._active_search_base: str | None = None

    def _request(self, url: str, what: str) -> bytes:
        last_error: Exception | None = None
        for attempt in range(self.config.retries + 1):
            try:
                return self._fetch(url, self.config.timeout)
            except Exception as exc:  # 网络异常种类多，统一收口后重试
                last_error = exc
                self.logger.debug("%s 请求失败（第 %d 次）：%s", what, attempt + 1, exc)
                if attempt < self.config.retries:
                    self._sleep(min(2.0, 0.3 * (attempt + 1)))
        raise LyricsUnavailable(
            f"{what} 请求失败：{url}（已重试 {self.config.retries} 次）"
        ) from last_error

    def search(self, keyword: str) -> tuple[SongCandidate, ...]:
        """按配置顺序尝试搜索 API，返回第一个有结果的候选列表。"""
        errors: list[str] = []
        for base in self.config.search_apis:
            base = base.rstrip("/")
            url = (
                f"{base}/search?limit={self.config.search_limit}&type=1"
                f"&keywords={urllib.parse.quote(keyword)}"
            )
            try:
                candidates = parse_search_response(self._request(url, "搜索 API"))
            except LyricsError as exc:
                errors.append(f"{base}：{exc}")
                self.logger.warning("搜索 API 不可用，尝试下一个：%s", base)
                continue
            if candidates:
                self._active_search_base = base
                self.logger.debug("搜索 API 命中：%s", base)
                return tuple(candidates)
            errors.append(f"{base}：无搜索结果")
        raise LyricsUnavailable("所有搜索 API 均不可用：\n- " + "\n- ".join(errors))

    def fetch_lyric(self, song_id: str) -> str | None:
        """获取原文歌词；纯音乐 / 无歌词返回 None。"""
        payload = self._request(f"{self.config.lyric_api}{song_id}", "歌词 API")
        data = _load_json(payload)
        if data.get("nolyric"):
            return None
        lyric = data.get("lyric")
        return lyric.strip() if isinstance(lyric, str) and lyric.strip() else None

    def fetch_translation(self, song_id: str) -> str | None:
        """获取翻译歌词；接口不可用或没有翻译返回 None。"""
        if not self._active_search_base:
            raise LyricsError("获取翻译歌词前需要先成功执行一次搜索")
        payload = self._request(
            f"{self._active_search_base}{self.config.translate_api}{song_id}", "翻译歌词 API"
        )
        if "纯音乐" in payload.decode("utf-8", errors="replace"):
            return None
        data = _load_json(payload)
        translated = data.get("tlyric") or {}
        lyric = translated.get("lyric") if isinstance(translated, dict) else None
        return lyric.strip() if isinstance(lyric, str) and lyric.strip() else None


class LyricsSource:
    """find_lyrics 需要的客户端接口，方便测试注入假实现。"""

    def search(self, keyword: str) -> Sequence[SongCandidate]: ...
    def fetch_lyric(self, song_id: str) -> str | None: ...
    def fetch_translation(self, song_id: str) -> str | None: ...


def find_lyrics(
    config: Config,
    *,
    client: LyricsSource | None = None,
    logger: logging.Logger = log,
) -> LyricsReport:
    """遍历歌曲目录，搜索并写入 .lrc 文件。"""
    cfg = config.lyrics
    songs_dir = cfg.songs_dir
    if not songs_dir.is_dir():
        raise LyricsError(f"歌曲目录不存在：{songs_dir}")
    lrc_dir = cfg.lrc_dir or songs_dir
    lrc_dir.mkdir(parents=True, exist_ok=True)

    client = client or LyricsClient(cfg, logger=logger)
    report = LyricsReport()
    existing = lrc_stems(lrc_dir)
    songs = audio_files(songs_dir)
    if not songs:
        logger.warning("目录中没有找到音频文件：%s", songs_dir)

    for path in songs:
        if path.stem.casefold() in existing:
            report.skipped_existing.append(path)
            continue
        track = parse_track_name(path.name, cfg.split_word)
        try:
            candidates = client.search(track.title)
            match = pick_best_candidate(track.title, candidates, cfg.similarity_threshold)
            if match is None:
                report.low_score.append(path)
                logger.warning("匹配度不足，跳过：%s", path.name)
                continue
            if cfg.language == "translation":
                lyric = client.fetch_translation(match.candidate.song_id)
            else:
                lyric = client.fetch_lyric(match.candidate.song_id)
        except LyricsError as exc:
            report.failed.append((path, str(exc)))
            logger.error("歌词获取失败 %s：%s", path.name, exc)
            continue
        if not lyric:
            report.no_lyric.append(path)
            logger.info("纯音乐或没有歌词：%s", path.name)
            continue
        lrc_path = lrc_dir / f"{path.stem}.lrc"
        try:
            lrc_path.write_text(lyric, encoding="utf-8")
        except OSError as exc:
            report.failed.append((path, f"写入 LRC 失败：{exc}"))
            logger.error("写入 LRC 失败 %s：%s", lrc_path, exc)
            continue
        report.written.append(lrc_path)
        logger.info("已写入歌词：%s（匹配度 %.1f%%）", lrc_path.name, match.score)

    logger.info(
        "歌词流程结束：写入 %d，已存在 %d，匹配度不足 %d，无歌词 %d，失败 %d",
        len(report.written),
        len(report.skipped_existing),
        len(report.low_score),
        len(report.no_lyric),
        len(report.failed),
    )
    return report


def write_log(report: LyricsReport, path: Path, config: Config) -> None:
    """把本次运行结果追加到日志文件。

    旧版用占位符模板 + 多次 str.replace 维护日志，格式脆弱；
    这里改成简单的分段追加，仍然保留「设置 / 结果 / 失败」的信息量。
    """
    cfg = config.lyrics
    lines = [
        "===== " + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " =====",
        "[setting]",
        f"songs_dir = {cfg.songs_dir}",
        f"lrc_dir = {cfg.lrc_dir or cfg.songs_dir}",
        f"language = {cfg.language}",
        f"similarity_threshold = {cfg.similarity_threshold}",
        "[written]",
        *[str(item) for item in report.written],
        "[skipped_existing]",
        *[str(item) for item in report.skipped_existing],
        "[low_score]",
        *[str(item) for item in report.low_score],
        "[no_lyric]",
        *[str(item) for item in report.no_lyric],
        "[failed]",
        *[f"{item}：{reason}" for item, reason in report.failed],
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
