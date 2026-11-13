"""解压页：独立的输出目录，以及解开后清理源文件的选项。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
from qfluentwidgets import CheckBox, PushButton

from core.filesystem import normalize_user_path
from core.models import AppConfig
from gui.config.paths import selection_directory
from gui.views.file_dialog import pick_directory
from gui.views.widgets import CollapsibleSection, text_field


class ExtractOutputPanel(QWidget):
    """解压输出目录；与压缩页的输出目录各自独立。"""

    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._config_dir = Path.cwd()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        title = QLabel("解压输出")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        directory_box, self.output_edit, row = text_field("输出目录", "")
        browse = PushButton("浏览…")
        browse.clicked.connect(self._choose_output)
        row.addWidget(browse)
        layout.addWidget(directory_box)
        hint = QLabel("1 级目录与 2 级目录在这里保持原名重建。")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)
        self.output_edit.textChanged.connect(self.changed)

    def set_config_directory(self, directory: Path) -> None:
        self._config_dir = directory

    def output_directory(self) -> str:
        return self.output_edit.text().strip()

    def set_output_directory(self, value: str) -> None:
        self.output_edit.setText(value)

    def _choose_output(self) -> None:
        raw = self.output_directory()
        selected = pick_directory(
            self.window(), title="选择解压输出目录",
            start_path=str(selection_directory(raw, self._config_dir)),
            default_output=str(normalize_user_path(raw, self._config_dir)) if raw else "",
        )
        if selected:
            self.set_output_directory(selected)

    def collect(self, config: AppConfig) -> AppConfig:
        return replace(config, extract_output_directory=self.output_directory())

    def apply(self, config: AppConfig) -> None:
        self.set_output_directory(config.extract_output_directory)


class ExtractOptionsPanel(CollapsibleSection):
    """解压任务选项：解开后清理源压缩包与空目录。"""

    changed = Signal()

    def __init__(self) -> None:
        super().__init__("任务选项")
        self.delete_check = CheckBox("解压后删除源文件")
        self.delete_check.setToolTip(
            "一个 2 级目录里的压缩包全部解开后才删除这些源压缩包，"
            "目录清空后一并移除，1 级目录同样处理。\n"
            "有压缩包解不开时保留它的源文件。"
        )
        self.body_layout.addWidget(self.delete_check)
        self.delete_check.toggled.connect(self._updated)
        self.toggle.setChecked(True)
        self._updated()

    def _updated(self) -> None:
        self.set_summary("解压后删除源文件" if self.delete_check.isChecked() else "")
        self.changed.emit()

    def delete_source_enabled(self) -> bool:
        return self.delete_check.isChecked()

    def collect(self, config: AppConfig) -> AppConfig:
        return replace(config, delete_source_after_extract=self.delete_check.isChecked())

    def apply(self, config: AppConfig) -> None:
        self.delete_check.setChecked(config.delete_source_after_extract)


__all__ = ["ExtractOptionsPanel", "ExtractOutputPanel"]
