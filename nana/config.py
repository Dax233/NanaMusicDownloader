"""TOML 配置的加载与校验。

设计目标：所有可调项都放进配置文件，改行为不再需要改源码。
解析结果是一组不可变的 dataclass，运行期不会被悄悄改掉状态。
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

# 默认的第三方网易云镜像，按顺序降级使用。
DEFAULT_SEARCH_APIS: tuple[str, ...] = (
    "http://cloud-music.pl-fe.cn",
    "https://music.api.ravelloh.top",
    "https://music.api.coderace.top",
    "https://neteaseapi.imgugu.ink",
)
DEFAULT_LYRIC_API = "https://music.163.com/api/song/media?id="
DEFAULT_TRANSLATE_API = "/lyric?id="
SUPPORTED_LANGUAGES = ("original", "translation")


class ConfigError(ValueError):
    """配置缺失、格式错误或取值不合法。"""


@dataclass(frozen=True)
class DownloadConfig:
    """[download] 段：下载与转码参数。"""

    url: str = ""
    output_dir: Path = Path("output")
    video_extension: str = "mp4"
    cookies_file: Path | None = None
    cover_image: Path | None = Path("avater.jpg")
    bitrate: str = "192k"
    sample_rate: int = 44100
    channels: int = 2
    keep_video: bool = False
    skip_existing: bool = True


@dataclass(frozen=True)
class TagConfig:
    """[tag] 段：写进 MP3 的元信息与标题分割词。"""

    artist: str = "ななひら"
    album: str = "ななひら翻唱集"
    album_artist: str = "ななひら"
    split_word: str = " - Cover- "


@dataclass(frozen=True)
class LyricsConfig:
    """[lyrics] 段：歌词搜索与匹配参数。"""

    songs_dir: Path = Path("output")
    lrc_dir: Path | None = None
    language: str = "original"
    split_word: str = " - Cover- "
    similarity_threshold: float = 75.0
    search_limit: int = 3
    timeout: float = 10.0
    retries: int = 2
    search_apis: tuple[str, ...] = DEFAULT_SEARCH_APIS
    lyric_api: str = DEFAULT_LYRIC_API
    translate_api: str = DEFAULT_TRANSLATE_API
    log_file: Path | None = None


@dataclass(frozen=True)
class Config:
    """整套配置。"""

    download: DownloadConfig = field(default_factory=DownloadConfig)
    tag: TagConfig = field(default_factory=TagConfig)
    lyrics: LyricsConfig = field(default_factory=LyricsConfig)
    source: Path | None = None


_TOP_LEVEL = {"download", "tag", "lyrics"}
_DOWNLOAD_KEYS = {
    "url",
    "output_dir",
    "video_extension",
    "cookies_file",
    "cover_image",
    "bitrate",
    "sample_rate",
    "channels",
    "keep_video",
    "skip_existing",
}
_TAG_KEYS = {"artist", "album", "album_artist", "split_word"}
_LYRICS_KEYS = {
    "songs_dir",
    "lrc_dir",
    "language",
    "split_word",
    "similarity_threshold",
    "search_limit",
    "timeout",
    "retries",
    "search_apis",
    "lyric_api",
    "translate_api",
    "log_file",
}


def load_config(path: str | Path | None = None) -> Config:
    """读取并校验配置文件；path 为 None 时返回内置默认值。"""
    if path is None:
        return Config()
    config_path = Path(path).expanduser()
    try:
        text = config_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ConfigError(f"配置文件不存在：{config_path}") from exc
    except OSError as exc:
        raise ConfigError(f"读取配置文件失败：{config_path}：{exc}") from exc
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"配置文件 {config_path} 不是合法 TOML：{exc}") from exc
    return parse_config(raw, source=config_path)


def parse_config(raw: Mapping[str, Any], source: Path | None = None) -> Config:
    """把 TOML 解析出的字典校验成 Config。"""
    if not isinstance(raw, Mapping):
        raise ConfigError("配置文件顶层必须是 TOML 表")
    unknown = sorted(set(raw) - _TOP_LEVEL)
    if unknown:
        raise ConfigError(
            f"未知配置段：{', '.join(unknown)}（可用：download / tag / lyrics）"
        )
    base = source.parent if source is not None else Path.cwd()
    return Config(
        download=_parse_download(_table(raw, "download"), base),
        tag=_parse_tag(_table(raw, "tag")),
        lyrics=_parse_lyrics(_table(raw, "lyrics"), base),
        source=source,
    )


def _table(raw: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = raw.get(name, {})
    if not isinstance(value, Mapping):
        raise ConfigError(f"[{name}] 必须是 TOML 表")
    return value


def _check_keys(section: Mapping[str, Any], name: str, allowed: set[str]) -> None:
    unknown = sorted(set(section) - allowed)
    if unknown:
        raise ConfigError(
            f"[{name}] 中出现未知字段：{', '.join(unknown)}"
            f"（可用：{', '.join(sorted(allowed))}）"
        )


def _as_str(section: Mapping[str, Any], name: str, key: str, default: str) -> str:
    value = section.get(key, default)
    if not isinstance(value, str):
        raise ConfigError(f"[{name}].{key} 必须是字符串")
    return value


def _as_int(
    section: Mapping[str, Any], name: str, key: str, default: int, minimum: int | None = None
) -> int:
    value = section.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"[{name}].{key} 必须是整数")
    if minimum is not None and value < minimum:
        raise ConfigError(f"[{name}].{key} 不能小于 {minimum}")
    return value


def _as_float(
    section: Mapping[str, Any], name: str, key: str, default: float, minimum: float | None = None
) -> float:
    value = section.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"[{name}].{key} 必须是数字")
    result = float(value)
    if minimum is not None and result < minimum:
        raise ConfigError(f"[{name}].{key} 不能小于 {minimum}")
    return result


def _as_bool(section: Mapping[str, Any], name: str, key: str, default: bool) -> bool:
    value = section.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"[{name}].{key} 必须是布尔值（true / false）")
    return value


def _as_path(
    section: Mapping[str, Any], name: str, key: str, default: Path, base: Path
) -> Path:
    value = _as_str(section, name, key, str(default))
    if not value.strip():
        raise ConfigError(f"[{name}].{key} 不能为空")
    return _resolve(base, value)


def _as_optional_path(
    section: Mapping[str, Any], name: str, key: str, default: str, base: Path
) -> Path | None:
    value = _as_str(section, name, key, default)
    if not value.strip():
        return None
    return _resolve(base, value)


def _resolve(base: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else base / path


def _as_str_list(
    section: Mapping[str, Any], name: str, key: str, default: tuple[str, ...]
) -> tuple[str, ...]:
    value = section.get(key)
    if value is None:
        return default
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError(f"[{name}].{key} 必须是字符串数组")
    cleaned = tuple(item.strip() for item in value)
    if not cleaned:
        raise ConfigError(f"[{name}].{key} 不能为空数组")
    for item in cleaned:
        if not item.startswith(("http://", "https://")):
            raise ConfigError(
                f"[{name}].{key} 中的地址必须以 http:// 或 https:// 开头：{item!r}"
            )
    return cleaned


def _parse_download(section: Mapping[str, Any], base: Path) -> DownloadConfig:
    _check_keys(section, "download", _DOWNLOAD_KEYS)
    video_extension = _as_str(section, "download", "video_extension", "mp4").strip().lstrip(".")
    if not video_extension:
        raise ConfigError("[download].video_extension 不能为空")
    return DownloadConfig(
        url=_as_str(section, "download", "url", "").strip(),
        output_dir=_as_path(section, "download", "output_dir", Path("output"), base),
        video_extension=video_extension,
        cookies_file=_as_optional_path(section, "download", "cookies_file", "", base),
        cover_image=_as_optional_path(section, "download", "cover_image", "avater.jpg", base),
        bitrate=_as_str(section, "download", "bitrate", "192k"),
        sample_rate=_as_int(section, "download", "sample_rate", 44100, minimum=1),
        channels=_as_int(section, "download", "channels", 2, minimum=1),
        keep_video=_as_bool(section, "download", "keep_video", False),
        skip_existing=_as_bool(section, "download", "skip_existing", True),
    )


def _parse_tag(section: Mapping[str, Any]) -> TagConfig:
    _check_keys(section, "tag", _TAG_KEYS)
    return TagConfig(
        artist=_as_str(section, "tag", "artist", TagConfig.artist),
        album=_as_str(section, "tag", "album", TagConfig.album),
        album_artist=_as_str(section, "tag", "album_artist", TagConfig.album_artist),
        split_word=_as_str(section, "tag", "split_word", TagConfig.split_word),
    )


def _parse_lyrics(section: Mapping[str, Any], base: Path) -> LyricsConfig:
    _check_keys(section, "lyrics", _LYRICS_KEYS)
    language = _as_str(section, "lyrics", "language", "original").strip().lower()
    if language not in SUPPORTED_LANGUAGES:
        raise ConfigError(
            f"[lyrics].language 只能是 {' / '.join(SUPPORTED_LANGUAGES)}，收到 {language!r}"
        )
    threshold = _as_float(section, "lyrics", "similarity_threshold", 75.0)
    if not 0.0 <= threshold <= 100.0:
        raise ConfigError("[lyrics].similarity_threshold 必须在 0-100 之间")
    return LyricsConfig(
        songs_dir=_as_path(section, "lyrics", "songs_dir", Path("output"), base),
        lrc_dir=_as_optional_path(section, "lyrics", "lrc_dir", "", base),
        language=language,
        split_word=_as_str(section, "lyrics", "split_word", TagConfig.split_word),
        similarity_threshold=threshold,
        search_limit=_as_int(section, "lyrics", "search_limit", 3, minimum=1),
        timeout=_as_float(section, "lyrics", "timeout", 10.0, minimum=0.1),
        retries=_as_int(section, "lyrics", "retries", 2, minimum=0),
        search_apis=_as_str_list(section, "lyrics", "search_apis", DEFAULT_SEARCH_APIS),
        lyric_api=_as_str(section, "lyrics", "lyric_api", DEFAULT_LYRIC_API),
        translate_api=_as_str(section, "lyrics", "translate_api", DEFAULT_TRANSLATE_API),
        log_file=_as_optional_path(section, "lyrics", "log_file", "", base),
    )
