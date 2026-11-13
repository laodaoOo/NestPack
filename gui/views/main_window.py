"""主窗口：压缩和解包工作区、层编辑与右侧输出及任务区域。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import PushButton

from core.filesystem import normalize_user_path
from core.models import COMPRESS_MODE_SEPARATE
from gui.appearance.logo import LogoState
from gui.appearance.theme import APP_NAME, STYLE_SHEET, create_app_icon, load_application_fonts
from gui.config.naming import output_preview
from gui.views.config_bar import ConfigBar
from gui.views.dialogs import show_error, show_info, show_licenses
from gui.views.extract_panel import ExtractOptionsPanel, ExtractOutputPanel
from gui.views.layers_panel import LayersPanel
from gui.views.output_panel import OutputPanel
from gui.views.settings_dialog import SettingsDialog
from gui.views.side_panel import SidePanel
from gui.views.source_panel import SourcePanel
from gui.views.task_options import TaskOptionsPanel
from gui.views.unpack_panel import UnpackPanel

# 导航顺序：压缩、解压（把 2 级目录里的压缩包解到输出）、解包（逐层还原）。
WORKSPACE_TITLES = ("压缩", "解压", "解包")
WORKSPACE_KINDS = ("compress", "extract", "unpack")


class MainWindow(QMainWindow):
    """管理界面归属与展示，任务执行由应用协调。"""

    close_requested = Signal(object)
    workspace_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._config_dir = Path.cwd()
        self._active_kind: str | None = None
        self._workspace_index = 0
        self.setWindowTitle(f"{APP_NAME} · 多层嵌套压缩")
        self.setWindowIcon(create_app_icon())
        self.resize(1240, 820)
        self.setMinimumSize(940, 600)
        load_application_fonts()
        self.setStyleSheet(STYLE_SHEET)
        self.source = SourcePanel()
        self.layers = LayersPanel()
        self.output = OutputPanel()
        self.extract_panel = ExtractOutputPanel()
        self.extract_options = ExtractOptionsPanel()
        self.options = TaskOptionsPanel()
        self.settings = SettingsDialog(self)
        self.config_bar = ConfigBar()
        self.unpack = UnpackPanel()
        self.side = SidePanel()
        self._build_ui()
        self.source.paths_changed.connect(self._sources_changed)
        self.source.mode_changed.connect(self._mode_changed)
        self.source.selection_changed.connect(self._mode_changed)
        self.layers.defaults_requested.connect(self.source.select_defaults)
        self.layers.add_requested.connect(self.add_layer)
        self.layers.card_changed.connect(self.update_summary)
        self.layers.cards_changed.connect(self.update_summary)
        self.layers.selection_changed.connect(lambda: self._show_compress_details(0))
        self.layers.selection_changed.connect(self.update_summary)
        self.layers.view_changed.connect(self.update_summary)
        self.output.directory_changed.connect(self.source.set_default_output_directory)
        self.output.changed.connect(self.update_summary)
        self.options.changed.connect(self.update_summary)
        self.side.open_output_requested.connect(self.open_output_directory)

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("appRoot")
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        header = QFrame()
        header.setObjectName("appHeader")
        row = QHBoxLayout(header)
        row.setContentsMargins(24, 4, 24, 0)
        row.setSpacing(20)
        title = QLabel(APP_NAME)
        title.setObjectName("appName")
        row.addWidget(title)
        self.navigation = QButtonGroup(self)
        for index, title in enumerate(WORKSPACE_TITLES):
            button = QPushButton(title)
            button.setObjectName("workspaceTab")
            button.setCheckable(True)
            button.setChecked(index == 0)
            self.navigation.addButton(button, index)
            button.clicked.connect(
                lambda _checked=False, value=index: self._switch_workspace(value)
            )
            row.addWidget(button)
        row.addStretch(1)
        self.settings_button = PushButton("设置")
        self.settings_button.clicked.connect(self._show_settings)
        row.addWidget(self.settings_button)
        about = PushButton("关于/许可")
        about.clicked.connect(lambda: show_licenses(self))
        row.addWidget(about)
        layout.addWidget(header)
        layout.addWidget(self.config_bar)
        content = QSplitter(Qt.Orientation.Horizontal)
        content.setChildrenCollapsible(False)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(24, 20, 24, 20)
        left_layout.setSpacing(24)
        left_layout.addWidget(self.source)
        self._left_layout = left_layout
        self.extract_extras = self._extract_workspace()
        left_layout.addWidget(self.extract_extras)
        self.workspaces = QStackedWidget()
        self.workspaces.addWidget(self._compress_workspace())
        self.workspaces.addWidget(self.unpack)
        left_layout.addWidget(self.workspaces, 1)
        content.addWidget(self._scroll(left))
        self.workspaces.setMinimumWidth(420)

        delivery = QFrame()
        delivery.setObjectName("deliveryPanel")
        delivery.setMinimumWidth(420)
        delivery_layout = QVBoxLayout(delivery)
        delivery_layout.setContentsMargins(20, 20, 20, 16)
        delivery_layout.setSpacing(16)
        self.outputs = QStackedWidget()
        compress_details = QWidget()
        details_layout = QVBoxLayout(compress_details)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.setSpacing(16)
        detail_tabs = QHBoxLayout()
        self.detail_navigation = QButtonGroup(self)
        for index, title in enumerate(("层设置", "任务输出")):
            button = QPushButton(title)
            button.setObjectName("detailTab")
            button.setCheckable(True)
            button.setChecked(index == 0)
            self.detail_navigation.addButton(button, index)
            button.clicked.connect(
                lambda _checked=False, value=index: self._show_compress_details(value)
            )
            detail_tabs.addWidget(button)
        self.detail_tab_row = QWidget()
        self.detail_tab_row.setLayout(detail_tabs)
        details_layout.addWidget(self.detail_tab_row)
        self.compress_details = QStackedWidget()
        self.compress_details.addWidget(self.layers.editors)
        self.compress_details.addWidget(self._scroll(self.output))
        details_layout.addWidget(self.compress_details, 1)
        self.outputs.addWidget(compress_details)
        self.outputs.addWidget(self._scroll(self.extract_panel))
        self.outputs.addWidget(self._scroll(self.unpack.output_panel))
        delivery_layout.addWidget(self.outputs, 1)
        delivery_layout.addWidget(self.side)
        content.addWidget(delivery)
        content.setSizes([660, 580])
        content.setStretchFactor(0, 1)
        content.setStretchFactor(1, 1)
        layout.addWidget(content, 1)
        self._switch_workspace(0)

    def _compress_workspace(self) -> QWidget:
        """压缩页的层列表与任务选项；来源列表由三页共用。"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)
        layout.addWidget(self.layers)
        layout.addWidget(self.options)
        layout.addStretch(1)
        return page

    def _extract_workspace(self) -> QWidget:
        """解压页只保留来源列表与规则说明。"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        hint = QLabel(
            "1 级目录保持不变；其中每个 2 级目录里的压缩包都解开到「解压输出」下"
            "同名的这两层文件夹里。重名时自动追加序号，压缩包内只有一层"
            "外壳文件夹时剥掉这一层。"
        )
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addWidget(self.extract_options)
        layout.addStretch(1)
        return page

    def _show_compress_details(self, index: int) -> None:
        self.compress_details.setCurrentIndex(index)
        self.detail_navigation.button(index).setChecked(True)

    @staticmethod
    def _scroll(content: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        return scroll

    def _show_settings(self) -> None:
        self.settings.show()
        self.settings.raise_()
        self.settings.activateWindow()

    def workspace(self) -> str:
        return WORKSPACE_KINDS[self._workspace_index]

    def _switch_workspace(self, index: int) -> None:
        self._workspace_index = index
        workspace = self.workspace()
        extract = workspace == "extract"
        self.source.setVisible(workspace != "unpack")
        self.source.set_mode_visible(workspace == "compress")
        self.source.set_list_expanding(extract)
        self.extract_extras.setVisible(extract)
        self.workspaces.setVisible(not extract)
        self.workspaces.setCurrentIndex(0 if workspace == "compress" else 1)
        self._left_layout.setStretchFactor(self.extract_extras, 1 if extract else 0)
        self.detail_tab_row.setVisible(workspace == "compress")
        self.outputs.setCurrentIndex(index)
        self.side.set_workspace(workspace)
        self.update_summary()
        self.workspace_changed.emit(workspace)

    def set_config_path(self, path: Path) -> None:
        self._config_dir = path.parent
        self.config_bar.set_path(path)
        self.source.set_config_directory(path.parent)
        self.layers.set_config_directory(path.parent)
        self.output.set_config_directory(path.parent)
        self.extract_panel.set_config_directory(path.parent)
        self.unpack.set_config_directory(path.parent)
        self.settings.runtime.set_config_directory(path.parent)

    def _sources_changed(self) -> None:
        sources = self.source.paths()
        if sources:
            first = normalize_user_path(sources[0], self._config_dir)
            if not self.output.output_directory():
                self.output.set_output_directory(str(first.parent))
        self._mode_changed()

    def _mode_changed(self) -> None:
        separate = self.source.mode() == COMPRESS_MODE_SEPARATE
        self.layers.set_sources(self.source.paths(), separate, self.source.selected_path())
        self.update_summary()

    def add_layer(self) -> None:
        self.layers.add_card()

    def update_summary(self) -> None:
        self.layers.set_random_names(self.options.random_names_enabled())
        workspace = self.workspace()
        if workspace != "compress":
            if self._active_kind is None:
                self.side.set_summary(
                    f"{len(self.source.paths())} 个来源" if workspace == "extract"
                    else "逐层恢复原始文件"
                )
            return
        layers = self.layers.collect(strict=False)
        if self._active_kind is None:
            self.side.set_summary(f"{len(self.source.paths())} 个来源，当前 {len(layers)} 层")
        if not layers:
            self.output.set_preview("添加压缩层后显示最外层名称", "")
            return
        sources = self.source.paths()
        if self.source.mode() == COMPRESS_MODE_SEPARATE:
            selected = self.source.selected_path()
            if selected is None:
                self.output.set_preview("输出预览", "选择来源后显示它的最终输出路径", [])
                return
            sources = [selected]
        paths, hint = output_preview(
            layers, sources, self.source.mode(),
            self.output.output_directory(), self._config_dir,
            random_names=self.options.random_names_enabled(),
        )
        self.output.set_preview("最终输出路径" if paths else "输出预览", hint, paths)

    def set_task_active(self, kind: str, active: bool) -> None:
        self._active_kind = kind if active else None
        self.config_bar.setEnabled(not active)
        self.settings_button.setEnabled(not active)
        self.settings.setEnabled(not active)
        if active:
            self.settings.hide()
        compression_editable = not active or kind == "unpack"
        self.source.set_editable(compression_editable)
        self.layers.set_editable(compression_editable)
        self.output.setEnabled(compression_editable)
        self.options.setEnabled(compression_editable)
        extract_editable = not active or kind != "extract"
        self.extract_panel.setEnabled(extract_editable)
        self.extract_options.setEnabled(extract_editable)
        self.unpack.set_editable(not active or kind in ("compress", "extract"))
        self.side.set_active(active, cancellable=kind in ("compress", "extract", "unpack"))
        if not active:
            self.update_summary()

    def set_status(self, message: str, state: LogoState | None = None) -> None:
        self.side.set_status(message, state)

    def open_output_directory(self) -> None:
        workspace = self.workspace()
        panel = (
            self.unpack if workspace == "unpack"
            else self.extract_panel if workspace == "extract"
            else self.output
        )
        raw = panel.output_directory()
        if not raw:
            show_info(self, "尚未设置", "请先选择输出目录。")
            return
        path = normalize_user_path(raw, self._config_dir)
        if not path.is_dir():
            show_error(self, "目录不存在", str(path))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def closeEvent(self, event: QCloseEvent) -> None:
        self.close_requested.emit(event)
