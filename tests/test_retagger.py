"""retagger.py 测试：文件名解析与批量重写（tag 写入用假实现）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from nana.retagger import RetitleError, resolve_update, retitle_directory


def test_resolve_update_extracts_title_and_artist():
    update = resolve_update(Path("夜に駆ける - Cover- ななひら.mp3"), " - Cover- ")
    assert update.title == "夜に駆ける"
    assert update.artist == "ななひら"


def test_resolve_update_without_split_word():
    update = resolve_update(Path("曲名.mp3"), " - Cover- ")
    assert update.title == "曲名"
    assert update.artist is None


def test_retitle_directory_writes_updates(tmp_path: Path):
    (tmp_path / "A - Cover- X.mp3").write_text("")
    (tmp_path / "B.mp3").write_text("")
    (tmp_path / "note.txt").write_text("")

    written = []

    def fake_writer(path, title, artist):
        written.append((Path(path).name, title, artist))

    report = retitle_directory(tmp_path, " - Cover- ", tag_writer=fake_writer)
    assert report.ok
    assert written == [
        ("A - Cover- X.mp3", "A", "X"),
        ("B.mp3", "B", None),
    ]
    assert len(report.updated) == 2


def test_retitle_directory_missing_directory(tmp_path: Path):
    with pytest.raises(RetitleError, match="目录不存在"):
        retitle_directory(tmp_path / "nope", " - Cover- ")


def test_retitle_directory_records_failures_and_continues(tmp_path: Path):
    (tmp_path / "A.mp3").write_text("")
    (tmp_path / "B.mp3").write_text("")

    def failing_writer(path, title, artist):
        if Path(path).name == "A.mp3":
            raise RetitleError("boom")

    report = retitle_directory(tmp_path, " - Cover- ", tag_writer=failing_writer)
    assert not report.ok
    assert [update.path.name for update in report.updated] == ["B.mp3"]
    assert report.failed[0][0].name == "A.mp3"
