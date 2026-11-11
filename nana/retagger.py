"""按文件名与分割词重写 MP3 的标题、歌手 tag。

旧版 reTitle.py 在模块顶层遍历目录、直接改 tag；
现在把「解析文件名」与「写 tag」拆开，写 tag 可以注入假实现，便于测试。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .utils import audio_files, parse_track_name

log = logging.getLogger(__name__)

TagWriter = Callable[[Path, str, "str | None"], None]


class RetitleError(RuntimeError):
    """重写 tag 失败。"""


@dataclass(frozen=True)
class TagUpdate:
    """一条待应用的 tag 修改。"""

    path: Path
    title: str
    artist: str | None


@dataclass
class RetitleReport:
    """一次批量重写的结果汇总。"""

    updated: list[TagUpdate] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)
    failed: list[tuple[Path, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed


def resolve_update(path: Path, split_word: str) -> TagUpdate:
    """根据文件名算出该写什么标题和歌手（纯函数，不碰文件）。"""
    track = parse_track_name(Path(path).name, split_word)
    return TagUpdate(path=Path(path), title=track.title, artist=track.artist)


def write_mp3_tags(path: Path, title: str, artist: str | None) -> None:
    """把标题与歌手写入 MP3（需要 eyed3）。"""
    try:
        import eyed3
    except ImportError as exc:
        raise RetitleError("重写 MP3 tag 需要 eyed3：pip install eyed3") from exc
    audio = eyed3.load(str(path))
    if audio is None:
        raise RetitleError(f"无法读取音频文件：{path}")
    if audio.tag is None:
        audio.initTag()
    audio.tag.title = title
    if artist:
        audio.tag.artist = artist
    audio.tag.save()


def retitle_directory(
    directory: Path,
    split_word: str,
    *,
    tag_writer: TagWriter = write_mp3_tags,
    logger: logging.Logger = log,
) -> RetitleReport:
    """遍历目录下所有 MP3，按分割词重写标题与歌手。"""
    folder = Path(directory)
    if not folder.is_dir():
        raise RetitleError(f"目录不存在：{folder}")

    report = RetitleReport()
    for path in audio_files(folder):
        if path.suffix.casefold() != ".mp3":
            report.skipped.append(path)
            continue
        update = resolve_update(path, split_word)
        try:
            tag_writer(update.path, update.title, update.artist)
        except (RetitleError, OSError) as exc:
            report.failed.append((path, str(exc)))
            logger.error("重写 tag 失败 %s：%s", path, exc)
            continue
        report.updated.append(update)
        logger.info(
            "已处理：%s（标题=%s，歌手=%s）",
            path.name,
            update.title,
            update.artist or "保持不变",
        )
    logger.info(
        "重写流程结束：成功 %d，跳过 %d，失败 %d",
        len(report.updated),
        len(report.skipped),
        len(report.failed),
    )
    return report
