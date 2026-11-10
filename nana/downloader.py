"""下载视频、转换为 MP3、写入音频 tag。

旧版 Downloader.py 把所有步骤写在一个函数里、配置写死在模块顶部；
这里拆成可单独调用的小步骤，外部命令与 tag 写入都可以注入，
因此不装 you-get / ffmpeg / eyed3 也能跑测试。
"""

from __future__ import annotations

import importlib.util
import json
import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .config import Config, DownloadConfig
from .fsutil import cleanup_path
from .utils import audio_stems, sanitize_filename, select_new_titles

log = logging.getLogger(__name__)

_MIME_BY_SUFFIX = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

Runner = Callable[..., subprocess.CompletedProcess]
TagWriter = Callable[[Path, str, Config], None]


class DependencyError(RuntimeError):
    """缺少外部命令或 Python 可选依赖。"""


class DownloadError(RuntimeError):
    """下载、转码或写 tag 过程中的失败。"""


@dataclass
class DownloadReport:
    """一次下载流程的结果汇总。"""

    downloaded: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed


def parse_metadata_output(output: str) -> list[dict]:
    """解析 you-get --json 的连续 JSON 输出。

    you-get 在合集模式下会一段一段地吐出多个 JSON 对象（可能夹着进度文字），
    旧版用正则匹配花括号，遇到嵌套对象就不可靠；这里用 raw_decode 逐个解。
    """
    decoder = json.JSONDecoder()
    entries: list[dict] = []
    pos, length = 0, len(output or "")
    while pos < length:
        start = output.find("{", pos)
        if start < 0:
            break
        try:
            obj, end = decoder.raw_decode(output, start)
        except json.JSONDecodeError:
            pos = start + 1  # 不是完整 JSON，往后挪一格继续找
            continue
        if isinstance(obj, dict):
            entries.append(obj)
        pos = end
    return entries


def build_download_command(cfg: DownloadConfig) -> list[str]:
    """拼出 you-get 下载命令。"""
    args = ["you-get", "--playlist"]
    if cfg.cookies_file:
        args += ["--cookies", str(cfg.cookies_file)]
    return [*args, "-o", str(cfg.output_dir), cfg.url]


def build_metadata_command(cfg: DownloadConfig) -> list[str]:
    """拼出 you-get 只取元信息的命令。"""
    args = ["you-get", "--json", "--playlist"]
    if cfg.cookies_file:
        args += ["--cookies", str(cfg.cookies_file)]
    return [*args, "-o", str(cfg.output_dir), cfg.url]


def build_ffmpeg_command(source: Path, target: Path, cfg: DownloadConfig) -> list[str]:
    """拼出 ffmpeg 转 MP3 命令。"""
    return [
        "ffmpeg",
        "-y",
        "-i",
        str(source),
        "-vn",
        "-ar",
        str(cfg.sample_rate),
        "-ac",
        str(cfg.channels),
        "-b:a",
        cfg.bitrate,
        str(target),
    ]


def missing_dependencies(
    *,
    need_youget: bool = True,
    need_ffmpeg: bool = True,
    need_tag: bool = False,
    which: Callable[[str], str | None] = shutil.which,
) -> list[str]:
    """返回缺失依赖的可读列表（空列表表示齐全）。"""
    missing: list[str] = []
    if need_youget and which("you-get") is None:
        missing.append("you-get（安装：pip install you-get）")
    if need_ffmpeg and which("ffmpeg") is None:
        missing.append("ffmpeg（安装：apt install ffmpeg 或 brew install ffmpeg）")
    if need_tag and importlib.util.find_spec("eyed3") is None:
        missing.append("eyed3（安装：pip install eyed3）")
    return missing


def ensure_dependencies(
    *,
    need_youget: bool = True,
    need_ffmpeg: bool = True,
    need_tag: bool = False,
    which: Callable[[str], str | None] = shutil.which,
) -> None:
    """依赖缺失时抛出带安装提示的 DependencyError。"""
    missing = missing_dependencies(
        need_youget=need_youget,
        need_ffmpeg=need_ffmpeg,
        need_tag=need_tag,
        which=which,
    )
    if missing:
        raise DependencyError(
            "缺少运行依赖：\n- " + "\n- ".join(missing) + "\n详见 README 的「安装」一节。"
        )


def _run(
    command: list[str],
    runner: Runner | None = None,
    *,
    capture: bool = False,
) -> subprocess.CompletedProcess:
    """执行外部命令，把各种失败统一包装成 DownloadError。"""
    runner = runner or subprocess.run
    log.debug("执行命令：%s", " ".join(command))
    try:
        return runner(command, check=True, capture_output=capture, text=True)
    except subprocess.CalledProcessError as exc:
        detail = (getattr(exc, "stderr", "") or "").strip()
        raise DownloadError(
            f"命令执行失败（退出码 {exc.returncode}）：{' '.join(command)}"
            + (f"：{detail}" if detail else "")
        ) from exc
    except OSError as exc:
        raise DownloadError(f"无法执行命令：{' '.join(command)}：{exc}") from exc


def _cover_mime(path: Path) -> str:
    """按扩展名猜封面 MIME；猜不到时再尝试 Pillow。"""
    mime = _MIME_BY_SUFFIX.get(path.suffix.casefold())
    if mime:
        return mime
    try:
        from PIL import Image  # 可选依赖，装不上就按 jpeg 处理

        with Image.open(path) as image:
            return "image/" + (image.format or "jpeg").casefold()
    except Exception:  # 封面格式无法识别时不能让写 tag 整体失败
        return "image/jpeg"


def write_tags(mp3_path: Path, title: str, config: Config) -> None:
    """把标题 / 歌手 / 专辑 / 封面写入 MP3（需要 eyed3）。"""
    try:
        import eyed3
        from eyed3.id3.frames import ImageFrame
    except ImportError as exc:
        raise DependencyError("写入 MP3 tag 需要 eyed3：pip install eyed3") from exc

    audio = eyed3.load(str(mp3_path))
    if audio is None:
        raise DownloadError(f"无法读取音频文件：{mp3_path}")
    if audio.tag is None:
        audio.initTag()
    tag = audio.tag
    tag.title = title
    if config.tag.artist:
        tag.artist = config.tag.artist
    if config.tag.album:
        tag.album = config.tag.album
    if config.tag.album_artist:
        tag.album_artist = config.tag.album_artist

    cover = config.download.cover_image
    if cover is not None and Path(cover).is_file():
        tag.images.set(ImageFrame.FRONT_COVER, Path(cover).read_bytes(), _cover_mime(Path(cover)))
    else:
        log.warning("封面不存在，跳过写入：%s", cover)
    tag.save()


def download(
    config: Config,
    *,
    runner: Runner | None = None,
    tag_writer: TagWriter = write_tags,
    logger: logging.Logger = log,
    which: Callable[[str], str | None] = shutil.which,
) -> DownloadReport:
    """执行完整下载流程：下载 → 取元信息 → 转码 → 写 tag → 清理中间文件。"""
    cfg = config.download
    if not cfg.url.strip():
        raise DownloadError(
            "尚未配置下载地址：请在配置文件 [download].url 或命令行的 URL 参数中指定视频/合集地址"
        )
    ensure_dependencies(need_youget=True, need_ffmpeg=True, which=which)

    report = DownloadReport()
    output_dir = cfg.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("[1/3] 下载视频（you-get）…")
    _run(build_download_command(cfg), runner)

    logger.info("[2/3] 读取视频元信息…")
    result = _run(build_metadata_command(cfg), runner, capture=True)
    entries = parse_metadata_output(getattr(result, "stdout", "") or "")
    if not entries:
        raise DownloadError("未能从 you-get 输出中解析出任何视频信息，请检查 URL 与 cookies 是否有效")
    titles = [str(entry.get("title", "")).strip() for entry in entries]
    titles = [title for title in titles if title]

    existing = audio_stems(output_dir) if cfg.skip_existing else set()
    todo = select_new_titles(titles, existing)
    skipped = [title for title in titles if title not in todo]
    logger.info("[3/3] 待处理 %d 首，已存在 %d 首", len(todo), len(skipped))

    for title in todo:
        stem = sanitize_filename(title)
        source = output_dir / f"{stem}.{cfg.video_extension}"
        target = output_dir / f"{stem}.mp3"
        try:
            if not source.is_file():
                raise DownloadError(f"未找到下载后的视频文件：{source.name}")
            _run(build_ffmpeg_command(source, target, cfg), runner)
            if not target.is_file():
                raise DownloadError(f"转码后未生成文件：{target.name}")
            tag_writer(target, title, config)
        except (DownloadError, DependencyError) as exc:
            report.failed.append((title, str(exc)))
            logger.error("处理失败 %s：%s", title, exc)
            continue
        report.downloaded.append(title)
        logger.info("完成：%s", target.name)
        if not cfg.keep_video:
            cleanup_path(source, logger)

    report.skipped = skipped
    if not cfg.keep_video:
        for danmaku in sorted(output_dir.glob("*.xml")):
            cleanup_path(danmaku, logger)

    logger.info(
        "下载流程结束：成功 %d，跳过 %d，失败 %d",
        len(report.downloaded),
        len(report.skipped),
        len(report.failed),
    )
    return report