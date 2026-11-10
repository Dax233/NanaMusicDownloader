"""downloader.py 测试：元信息解析、命令拼装、依赖检查与流程编排（不联网）。"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from nana.config import Config, DownloadConfig
from nana.downloader import (
    DependencyError,
    DownloadError,
    build_download_command,
    build_ffmpeg_command,
    build_metadata_command,
    download,
    ensure_dependencies,
    parse_metadata_output,
)


class FakeRunner:
    """假的 subprocess.run：记录命令，按需伪造 stdout，并在转码时生成输出文件。"""

    def __init__(self, metadata: str = "") -> None:
        self.commands: list[list[str]] = []
        self.metadata = metadata

    def __call__(self, command, check=False, capture_output=False, text=False):
        self.commands.append(list(command))
        if command[0] == "ffmpeg":
            Path(command[-1]).write_text("fake mp3")
            return subprocess.CompletedProcess(command, 0, "", "")
        if "--json" in command:
            return subprocess.CompletedProcess(command, 0, self.metadata, "")
        return subprocess.CompletedProcess(command, 0, "", "")


def _config(tmp_path: Path, **overrides) -> Config:
    values = dict(url="https://example.com/video", output_dir=tmp_path / "out")
    values.update(overrides)
    return Config(download=DownloadConfig(**values))


def test_parse_metadata_output_handles_concatenated_objects():
    output = '{"title": "A", "format": "mp4"}\n{"title": "B", "format": "mp4"}\n'
    assert [item["title"] for item in parse_metadata_output(output)] == ["A", "B"]


def test_parse_metadata_output_skips_noise():
    output = 'progress 10%\n{"title": "A"}\nwarning: something\n{"title": "B"}\n'
    assert [item["title"] for item in parse_metadata_output(output)] == ["A", "B"]


def test_parse_metadata_output_handles_nested_objects():
    output = '{"title": "A", "extra": {"k": [1, 2]}}'
    parsed = parse_metadata_output(output)
    assert parsed == [{"title": "A", "extra": {"k": [1, 2]}}]


def test_parse_metadata_output_without_json_returns_empty():
    assert parse_metadata_output("no json here") == []
    assert parse_metadata_output("") == []


def test_command_builders(tmp_path: Path):
    config = _config(tmp_path, cookies_file=tmp_path / "cookies.txt")
    cfg = config.download
    assert build_download_command(cfg) == [
        "you-get",
        "--playlist",
        "--cookies",
        str(tmp_path / "cookies.txt"),
        "-o",
        str(tmp_path / "out"),
        "https://example.com/video",
    ]
    assert "--json" in build_metadata_command(cfg)
    ffmpeg = build_ffmpeg_command(tmp_path / "a.mp4", tmp_path / "a.mp3", cfg)
    assert ffmpeg[:3] == ["ffmpeg", "-y", "-i"]
    assert ffmpeg[-1] == str(tmp_path / "a.mp3")


def test_command_builders_without_cookies(tmp_path: Path):
    cfg = _config(tmp_path).download
    assert "--cookies" not in build_download_command(cfg)
    assert "--cookies" not in build_metadata_command(cfg)


def test_missing_dependencies_reported():
    with pytest.raises(DependencyError, match="you-get"):
        ensure_dependencies(which=lambda name: None)


def test_dependencies_ok_when_all_found():
    ensure_dependencies(which=lambda name: "/usr/bin/" + name)


def test_download_requires_url(tmp_path: Path):
    with pytest.raises(DownloadError, match="下载地址"):
        download(Config(), which=lambda name: "/usr/bin/" + name)


def test_download_skips_existing_and_cleans_intermediates(tmp_path: Path):
    output = tmp_path / "out"
    output.mkdir()
    (output / "A.mp3").write_text("old")
    (output / "B.mp4").write_text("video")
    (output / "B.xml").write_text("danmaku")

    runner = FakeRunner(metadata='{"title": "A"}\n{"title": "B"}\n')
    tagged = []

    def fake_tag_writer(path, title, config):
        tagged.append((Path(path).name, title))

    config = _config(tmp_path)
    report = download(
        config,
        runner=runner,
        tag_writer=fake_tag_writer,
        which=lambda name: "/usr/bin/" + name,
    )

    assert report.downloaded == ["B"]
    assert report.skipped == ["A"]
    assert tagged == [("B.mp3", "B")]
    assert (output / "B.mp3").is_file()
    assert not (output / "B.mp4").exists()
    assert not (output / "B.xml").exists()


def test_download_reports_missing_source(tmp_path: Path):
    output = tmp_path / "out"
    output.mkdir()
    runner = FakeRunner(metadata='{"title": "C"}\n')
    config = _config(tmp_path)
    report = download(
        config,
        runner=runner,
        tag_writer=lambda *args: None,
        which=lambda name: "/usr/bin/" + name,
    )
    assert report.downloaded == []
    assert report.failed and "未找到下载后的视频文件" in report.failed[0][1]
    assert report.ok is False


def test_download_raises_when_metadata_unparsable(tmp_path: Path):
    output = tmp_path / "out"
    output.mkdir()
    runner = FakeRunner(metadata="garbage")
    config = _config(tmp_path)
    with pytest.raises(DownloadError, match="视频信息"):
        download(config, runner=runner, which=lambda name: "/usr/bin/" + name)


def test_download_keeps_video_when_configured(tmp_path: Path):
    output = tmp_path / "out"
    output.mkdir()
    (output / "B.mp4").write_text("video")
    (output / "B.xml").write_text("danmaku")
    runner = FakeRunner(metadata='{"title": "B"}\n')
    config = _config(tmp_path, keep_video=True)
    download(
        config,
        runner=runner,
        tag_writer=lambda *args: None,
        which=lambda name: "/usr/bin/" + name,
    )
    assert (output / "B.mp4").is_file()
    assert (output / "B.xml").is_file()


def test_download_continues_after_tag_failure(tmp_path: Path):
    output = tmp_path / "out"
    output.mkdir()
    (output / "A.mp4").write_text("video")
    (output / "B.mp4").write_text("video")
    runner = FakeRunner(metadata='{"title": "A"}\n{"title": "B"}\n')

    def failing_writer(path, title, config):
        if title == "A":
            raise DependencyError("eyed3 不存在")

    config = _config(tmp_path)
    report = download(
        config,
        runner=runner,
        tag_writer=failing_writer,
        which=lambda name: "/usr/bin/" + name,
    )
    assert report.downloaded == ["B"]
    assert len(report.failed) == 1
    assert "eyed3" in report.failed[0][1]
