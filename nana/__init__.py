"""NanaMusicDownloader 的核心包。

把旧版三个脚本（Downloader.py / reTitle.py / musicLrcMatch.py）拆成
配置、下载、tag 重写、歌词匹配与 CLI 五个职责清晰的模块。
"""

from .config import Config, load_config

__version__ = "2.0.0"
__all__ = ["Config", "load_config", "__version__"]
