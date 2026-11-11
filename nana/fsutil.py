"""文件系统小工具。

单独成模块的原因：清理中间文件属于删除操作，集中在这里方便审阅与替换，
也避免下载/转码代码里散落文件清理调用。
"""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)


def cleanup_path(path: Path, logger: logging.Logger = log) -> bool:
    """清理单个文件；文件不存在或清理失败都不抛异常。

    返回是否真的清理成功，方便调用方统计。
    """
    try:
        path.unlink(missing_ok=True)
        return True
    except OSError as exc:  # 清理失败不算致命错误，记一条警告即可
        logger.warning("清理临时文件失败 %s：%s", path, exc)
        return False
