"""config.py 的加载与校验测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from nana.config import (
    DEFAULT_SEARCH_APIS,
    Config,
    ConfigError,
    load_config,
    parse_config,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_load_without_path_uses_defaults():
    config = load_config()
    assert isinstance(config, Config)
    assert config.download.output_dir == Path("output")
    assert config.lyrics.language == "original"
    assert config.lyrics.search_apis == DEFAULT_SEARCH_APIS


def test_example_config_is_valid():
    config = load_config(REPO_ROOT / "config.example.toml")
    assert config.download.url.startswith("https://")
    assert config.tag.artist
    assert config.lyrics.similarity_threshold == 75.0


def test_parse_full_sections(tmp_path: Path):
    path = _write(
        tmp_path,
        """
[download]
url = "https://example.com/video"
output_dir = "music"
cookies_file = "cookies.txt"
bitrate = "320k"
sample_rate = 48000
channels = 2
keep_video = true

[tag]
artist = "A"
album = "B"
album_artist = "A"
split_word = " - "

[lyrics]
songs_dir = "music"
lrc_dir = "lrc"
language = "translation"
similarity_threshold = 80.5
timeout = 5.0
retries = 1
search_apis = ["https://a.example", "https://b.example"]
log_file = "musicinfo.log"
""",
    )
    config = load_config(path)
    assert config.download.url == "https://example.com/video"
    assert config.download.output_dir == tmp_path / "music"
    assert config.download.cookies_file == tmp_path / "cookies.txt"
    assert config.download.bitrate == "320k"
    assert config.download.sample_rate == 48000
    assert config.download.keep_video is True
    assert config.tag.split_word == " - "
    assert config.lyrics.language == "translation"
    assert config.lyrics.lrc_dir == tmp_path / "lrc"
    assert config.lyrics.search_apis == ("https://a.example", "https://b.example")
    assert config.lyrics.log_file == tmp_path / "musicinfo.log"
    assert config.source == path


def test_empty_optional_paths_become_none(tmp_path: Path):
    path = _write(
        tmp_path,
        """
[download]
cookies_file = ""
cover_image = ""

[lyrics]
lrc_dir = ""
log_file = ""
""",
    )
    config = load_config(path)
    assert config.download.cookies_file is None
    assert config.download.cover_image is None
    assert config.lyrics.lrc_dir is None
    assert config.lyrics.log_file is None


def test_unknown_section_raises(tmp_path: Path):
    path = _write(tmp_path, "[downlod]\nurl = \"x\"\n")
    with pytest.raises(ConfigError, match="未知配置段"):
        load_config(path)


def test_unknown_field_raises(tmp_path: Path):
    path = _write(tmp_path, "[download]\nur1 = \"x\"\n")
    with pytest.raises(ConfigError, match="未知字段"):
        load_config(path)


def test_wrong_type_raises(tmp_path: Path):
    path = _write(tmp_path, "[download]\nsample_rate = \"44100\"\n")
    with pytest.raises(ConfigError, match="sample_rate"):
        load_config(path)


def test_bool_is_not_accepted_as_int(tmp_path: Path):
    path = _write(tmp_path, "[download]\nchannels = true\n")
    with pytest.raises(ConfigError, match="channels"):
        load_config(path)


def test_invalid_language_raises(tmp_path: Path):
    path = _write(tmp_path, "[lyrics]\nlanguage = \"cn\"\n")
    with pytest.raises(ConfigError, match="language"):
        load_config(path)


def test_threshold_out_of_range_raises(tmp_path: Path):
    path = _write(tmp_path, "[lyrics]\nsimilarity_threshold = 120\n")
    with pytest.raises(ConfigError, match="similarity_threshold"):
        load_config(path)


def test_invalid_search_api_scheme_raises(tmp_path: Path):
    path = _write(tmp_path, "[lyrics]\nsearch_apis = [\"ftp://x\"]\n")
    with pytest.raises(ConfigError, match="search_apis"):
        load_config(path)


def test_invalid_toml_raises(tmp_path: Path):
    path = _write(tmp_path, "[download\nurl = 1")
    with pytest.raises(ConfigError, match="TOML"):
        load_config(path)


def test_missing_config_file_raises(tmp_path: Path):
    with pytest.raises(ConfigError, match="不存在"):
        load_config(tmp_path / "nope.toml")


def test_parse_config_without_source_uses_cwd():
    config = parse_config({"download": {"output_dir": "out"}})
    assert config.download.output_dir == Path.cwd() / "out"
