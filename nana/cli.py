"""命令行入口：download / retitle / lyrics / all。

对应 README 里的三步流程；旧版三个脚本分别对应前三个子命令，
all 则是「一条命令跑完三步」。
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import replace
from pathlib import Path

from . import __version__
from .config import Config, ConfigError, load_config
from .downloader import DependencyError, DownloadError, download
from .lyrics import LyricsError, find_lyrics, write_log
from .retagger import RetitleError, retitle_directory

log = logging.getLogger("nana")


def build_parser() -> argparse.ArgumentParser:
    """构建 argparse 解析器（单独暴露出来方便测试）。"""
    parser = argparse.ArgumentParser(
        prog="nana",
        description="批量下载视频、转 MP3、写音频 tag、按分割词重写并模糊匹配歌词",
    )
    parser.add_argument("-c", "--config", type=Path, help="TOML 配置文件路径（省略则只用内置默认值）")
    parser.add_argument("-v", "--verbose", action="store_true", help="输出调试日志")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="{download,retitle,lyrics,all}")

    p_download = sub.add_parser("download", help="下载视频并转成带 tag 的 MP3")
    p_download.add_argument("url", nargs="?", help="视频或合集地址（覆盖配置里的 [download].url）")
    p_download.add_argument("-o", "--output-dir", type=Path, help="输出目录（覆盖配置）")
    p_download.add_argument("--cookies", type=Path, help="cookies 文件路径（覆盖配置）")
    p_download.add_argument("--keep-video", action="store_true", help="保留下载的视频与弹幕文件")

    p_retitle = sub.add_parser("retitle", help="按分割词重写 MP3 的标题与歌手")
    p_retitle.add_argument("directory", nargs="?", type=Path, help="待处理目录（默认 [download].output_dir）")
    p_retitle.add_argument("--split-word", help="标题分割词（覆盖配置里的 [tag].split_word）")

    p_lyrics = sub.add_parser("lyrics", help="搜索并写入歌词")
    p_lyrics.add_argument("directory", nargs="?", type=Path, help="歌曲目录（默认 [lyrics].songs_dir）")
    p_lyrics.add_argument("--lrc-dir", type=Path, help="歌词保存目录（默认与歌曲目录相同）")
    p_lyrics.add_argument(
        "--language", choices=("original", "translation"), help="原文或翻译歌词"
    )
    p_lyrics.add_argument("--threshold", type=float, help="匹配度下限（0-100）")

    p_all = sub.add_parser("all", help="依次执行 download → retitle → lyrics")
    p_all.add_argument("url", nargs="?", help="视频或合集地址（覆盖配置里的 [download].url）")
    p_all.add_argument("-o", "--output-dir", type=Path, help="输出目录（覆盖配置）")
    p_all.add_argument("--cookies", type=Path, help="cookies 文件路径（覆盖配置）")
    p_all.add_argument("--keep-video", action="store_true", help="保留下载的视频与弹幕文件")

    return parser


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )


def _apply_download_overrides(config: Config, args: argparse.Namespace) -> Config:
    """把 download / all 子命令的覆盖项合并进配置。"""
    updates: dict = {}
    if getattr(args, "url", None):
        updates["url"] = args.url
    if getattr(args, "output_dir", None):
        updates["output_dir"] = args.output_dir
    if getattr(args, "cookies", None):
        updates["cookies_file"] = args.cookies
    if getattr(args, "keep_video", False):
        updates["keep_video"] = True
    return replace(config, download=replace(config.download, **updates)) if updates else config


def _apply_lyrics_overrides(config: Config, args: argparse.Namespace) -> Config:
    """把 lyrics 子命令的覆盖项合并进配置。"""
    updates: dict = {}
    if getattr(args, "directory", None):
        updates["songs_dir"] = args.directory
    if getattr(args, "lrc_dir", None):
        updates["lrc_dir"] = args.lrc_dir
    if getattr(args, "language", None):
        updates["language"] = args.language
    if getattr(args, "threshold", None) is not None:
        updates["similarity_threshold"] = args.threshold
    return replace(config, lyrics=replace(config.lyrics, **updates)) if updates else config


def _maybe_write_log(config: Config, report, logger: logging.Logger) -> None:
    path = config.lyrics.log_file
    if path is None:
        return
    try:
        write_log(report, path, config)
        logger.info("运行日志已追加到 %s", path)
    except OSError as exc:  # 日志写不进去不影响主流程结果
        logger.warning("写入运行日志失败 %s：%s", path, exc)


def _run_download(config: Config):
    return download(config)


def main(argv: list[str] | None = None) -> int:
    """CLI 主入口，返回进程退出码。"""
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        log.error("配置错误：%s", exc)
        return 2

    try:
        if args.command == "download":
            report = download(_apply_download_overrides(config, args))
            return 0 if report.ok else 1

        if args.command == "retitle":
            directory = args.directory or config.download.output_dir
            split_word = args.split_word or config.tag.split_word
            report = retitle_directory(directory, split_word)
            return 0 if report.ok else 1

        if args.command == "lyrics":
            config = _apply_lyrics_overrides(config, args)
            report = find_lyrics(config)
            _maybe_write_log(config, report, log)
            return 0 if report.ok else 1

        if args.command == "all":
            config = _apply_download_overrides(config, args)
            download_report = download(config)
            if not download_report.ok:
                log.warning("有 %d 首下载/转码失败，继续尝试后续步骤", len(download_report.failed))
            retitle_report = retitle_directory(config.download.output_dir, config.tag.split_word)
            lyrics_config = replace(
                config, lyrics=replace(config.lyrics, songs_dir=config.download.output_dir)
            )
            lyrics_report = find_lyrics(lyrics_config)
            _maybe_write_log(lyrics_config, lyrics_report, log)
            return 0 if (download_report.ok and retitle_report.ok and lyrics_report.ok) else 1

    except (DownloadError, DependencyError, RetitleError, LyricsError) as exc:
        log.error("%s", exc)
        return 1
    except KeyboardInterrupt:
        log.warning("已中断")
        return 130
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
