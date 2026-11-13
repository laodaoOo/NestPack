"""解压入口：按 1 级 / 2 级目录批量解开其中的压缩包。"""

from __future__ import annotations

from .workflow import ExtractJob, ExtractOutcome, extract_archives, scan_jobs

__all__ = ["ExtractJob", "ExtractOutcome", "extract_archives", "scan_jobs"]
