"""cli.py 测试：参数解析与错误退出码（不真正下载）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from nana.cli import build_parser, main


def test_parser_requires_subcommand():
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_parser_download_args():
    args = build_parser().parse_args(
        ["download", "https://example.com/v", "-o", "out", "--keep-video"]
    )
    assert args.command == "download"
    assert args.url == "https://example.com/v"
    assert args.output_dir == Path("out")
    assert args.keep_video is True


def test_parser_lyrics_args():
    args = build_parser().parse_args(
        ["lyrics", "--language", "translation", "--threshold", "60"]
    )
    assert args.command == "lyrics"
    assert args.language == "translation"
    assert args.threshold == 60.0


def test_main_returns_2_on_bad_config(tmp_path: Path):
    assert main(["-c", str(tmp_path / "nope.toml"), "download"]) == 2


def test_main_without_url_returns_1():
    assert main(["download"]) == 1


def test_main_retitle_missing_dir_returns_1(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["retitle", str(tmp_path / "nope")]) == 1


def test_main_all_without_url_returns_1():
    assert main(["all"]) == 1
