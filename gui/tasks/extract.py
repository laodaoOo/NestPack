"""解压执行：来源扫描、工具解析、进度与用户取消。"""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject

from core.extract import ExtractJob, ExtractOutcome, extract_archives, scan_jobs
from core.models import FORMAT_7Z
from gui.tasks.threading import BackgroundTask, TaskWorker
from platforms import resolve_optional_tool


class ExtractWorker(TaskWorker):
    """在独立线程中批量解压各 2 级目录里的压缩包。"""

    def __init__(
        self,
        rar_tool: Path | None,
        sevenzip_tool: Path | None,
        jobs: list[ExtractJob],
        output_dir: Path,
        delete_source: bool,
        cancel_event: threading.Event,
    ) -> None:
        super().__init__("解压失败")
        self._rar_tool = rar_tool
        self._sevenzip_tool = sevenzip_tool
        self._jobs = list(jobs)
        self._output_dir = output_dir
        self._delete_source = delete_source
        self._cancel_event = cancel_event

    def execute(self) -> ExtractOutcome:
        self.log.emit(
            f"WinRAR：{self._rar_tool}"
            if self._rar_tool else "WinRAR：未检测到（遇到 rar 压缩包时无法解）"
        )
        self.log.emit(
            f"7-Zip：{self._sevenzip_tool}"
            if self._sevenzip_tool else "7-Zip：未检测到（遇到 7z / zip 压缩包时无法解）"
        )
        self.log.emit(f"解压输出目录：{self._output_dir}")
        if self._delete_source:
            self.log.emit("解压后删除源文件：已开启（每个 2 级目录解开后清理）")
        outcome = extract_archives(
            self._jobs,
            self._output_dir,
            rar_tool=self._rar_tool,
            sevenzip_tool=self._sevenzip_tool,
            delete_source=self._delete_source,
            cancel_event=self._cancel_event,
            output_cb=self.log.emit,
            progress_cb=self._progress,
        )
        self.log.emit(
            f"解压完成：{outcome.archives} 个压缩包，写入 {outcome.entries} 个条目。"
        )
        if outcome.removed:
            self.log.emit(f"已删除 {outcome.removed} 个源压缩包。")
        for name, reason in outcome.failures:
            self.log.emit(f"[未解开] {name}：{reason}")
        return outcome

    def _progress(self, value: int, total: int, message: str) -> None:
        """把批量进度转成界面进度条信号，并记录当前压缩包。"""
        self.progress.emit(value, total, message)


class ExtractTask(BackgroundTask):
    """解析本次解压工具，并把来源扫描结果交给后台线程。"""

    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        self._cancel_event = threading.Event()

    def start(
        self,
        sources: list[Path],
        output_dir: Path,
        *,
        delete_source: bool,
        winrar_configured: str,
        sevenzip_configured: str,
        config_dir: Path,
    ) -> list[ExtractJob]:
        """校验来源与工具后启动解压，返回本次的待办列表。"""
        rar_tool = resolve_optional_tool(winrar_configured, config_dir)
        sevenzip_tool = resolve_optional_tool(sevenzip_configured, config_dir, kind=FORMAT_7Z)
        if rar_tool is None and sevenzip_tool is None:
            raise ValueError("未找到任何可用的压缩命令行（WinRAR 与 7z 均未检测到）。")
        jobs = scan_jobs(sources, output_dir)
        if not jobs:
            raise ValueError("所选文件夹里没有找到可解压的压缩包。")
        self._cancel_event = threading.Event()
        self._start(ExtractWorker(
            rar_tool, sevenzip_tool, jobs, output_dir, delete_source, self._cancel_event,
        ))
        return jobs

    def cancel(self) -> None:
        """请求停止解压，已解出的内容保留在输出目录。"""
        self._cancel_event.set()
