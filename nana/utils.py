"""纯工具函数：标题清洗、文件名解析、相似度打分、文件遍历。

本模块只依赖标准库，不碰网络、不导入音频库，方便直接单测。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable, Sequence

# 旧版 musicLrcMatch.py 支持的音频扩展名。
AUDIO_EXTENSIONS: tuple[str, ...] = ("mp3", "wma", "wav", "ape", "flac", "ogg", "aac")

# 文件名里不允许出现的字符（Windows / POSIX 取并集，外加控制字符）。
_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
# 圆括号 / 全角圆括号 / 方括号里通常是版本、翻自、TV size 之类的补充说明。
_BRACKETS = re.compile(r"\(.*?\)|（.*?）|\[.*?\]")
_WHITESPACE = re.compile(r"\s+")


def sanitize_filename(name: str, replacement: str = "-", max_length: int = 150) -> str:
    """把视频标题变成可安全落盘的文件名（不含路径分隔符）。

    旧版直接 re.sub 之后仍可能留下多余空格或结尾的点；
    这里再折叠空白、去掉首尾空白与点，并限制长度，避免超长标题。
    """
    cleaned = _ILLEGAL_CHARS.sub(replacement, name or "")
    cleaned = _WHITESPACE.sub(" ", cleaned).strip()
    cleaned = cleaned.strip(" .")
    if max_length and len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip(" .")
    return cleaned or "untitled"


@dataclass(frozen=True)
class TrackName:
    """一个音频文件名拆出来的信息。"""

    stem: str
    title: str
    artist: str | None


def parse_track_name(filename: str, split_word: str) -> TrackName:
    """按分割词把「歌名 - Cover- 歌手.mp3」拆成标题与歌手。

    只按分割词切一次；分割词为空或未命中时 artist 为 None，
    此时 title 就是去掉扩展名的完整文件名。
    """
    stem = Path(filename).stem
    if not split_word or split_word not in stem:
        return TrackName(stem=stem, title=stem, artist=None)
    title, _, artist = stem.partition(split_word)
    title, artist = title.strip(), artist.strip()
    if not title or not artist:
        return TrackName(stem=stem, title=stem, artist=None)
    return TrackName(stem=stem, title=title, artist=artist)


def strip_brackets(text: str) -> str:
    """去掉圆括号 / 方括号里的补充说明，用于搜索前归一化。"""
    return _BRACKETS.sub("", text or "").strip()


def normalize_for_match(text: str) -> str:
    """模糊匹配前的归一化：去括号、全半角统一、大小写与空白折叠。"""
    text = unicodedata.normalize("NFKC", strip_brackets(text or ""))
    return _WHITESPACE.sub(" ", text).strip().casefold()


def similarity(a: str, b: str) -> float:
    """返回 0-100 的相似度。

    旧版用 quick_ratio()，对短字符串偏差较大；这里改用精确的
    SequenceMatcher.ratio()，并对「文件名是 API 歌名的子串」这种情况
    给 90 分下限（例如文件名「夜に駆ける」对上「夜に駆ける (TV size)」）。
    """
    na, nb = normalize_for_match(a), normalize_for_match(b)
    if not na or not nb:
        return 0.0
    score = SequenceMatcher(None, na, nb).ratio() * 100.0
    shorter, longer = (na, nb) if len(na) <= len(nb) else (nb, na)
    if len(shorter) >= 2 and shorter in longer:
        score = max(score, 90.0)
    return round(score, 1)


def audio_files(
    directory: Path, extensions: Sequence[str] = AUDIO_EXTENSIONS
) -> list[Path]:
    """列出目录下的音频文件（不递归，按文件名排序）。"""
    path = Path(directory)
    if not path.is_dir():
        return []
    allowed = {"." + ext.lstrip(".").casefold() for ext in extensions}
    return sorted(
        (item for item in path.iterdir() if item.is_file() and item.suffix.casefold() in allowed),
        key=lambda item: item.name.casefold(),
    )


def audio_stems(directory: Path, extensions: Sequence[str] = AUDIO_EXTENSIONS) -> set[str]:
    """目录下所有音频文件的主名（小写），用于防重。"""
    return {item.stem.casefold() for item in audio_files(directory, extensions)}


def lrc_stems(directory: Path) -> set[str]:
    """目录下所有 .lrc 文件的主名（小写），用于跳过已有歌词。"""
    path = Path(directory)
    if not path.is_dir():
        return set()
    return {
        item.stem.casefold()
        for item in path.iterdir()
        if item.is_file() and item.suffix.casefold() == ".lrc"
    }


def select_new_titles(titles: Iterable[str], existing_stems: Iterable[str]) -> list[str]:
    """防重：过滤掉本地已有以及本批次内重复的标题，保持原顺序。

    比较时用清洗后的文件名主名并统一小写，
    这样「歌名」与「歌名.mp3」、大小写差异都不会重复下载。
    """
    seen = {stem.casefold() for stem in existing_stems}
    selected: list[str] = []
    for title in titles:
        key = sanitize_filename(title).casefold()
        if key in seen:
            continue
        seen.add(key)
        selected.append(title)
    return selected
