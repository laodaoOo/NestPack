"""解压：把 1 级目录下各 2 级目录里的压缩包解到输出的同名两层目录。

规则：1 级目录名与 2 级目录名保持不变；每个压缩包解开后放进对应的
2 级目录，压缩包内若只有一层外壳文件夹则剥掉这一层；与已有内容重名
时按系统习惯追加序号，并记录重命名供界面提示。
"""

from __future__ import annotations

import shutil
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from core.backends import detect_archive_format, get_backend
from core.cancellation import Cancellation, CancelledError
from core.models import FORMAT_7Z, FORMAT_ZIP
from core.unpack.extraction import extract_layer
from core.unpack.workspace import unpack_workspace
from platforms import get_archive_platform


@dataclass(frozen=True)
class ExtractJob:
    """一个待解压的压缩包及其落盘目录。"""

    archive: Path
    target: Path
    archive_format: str


@dataclass
class ExtractOutcome:
    """本次解压的落盘统计、重命名记录与未能解开的压缩包。"""

    output: Path
    archives: int = 0
    entries: int = 0
    renames: list[tuple[str, str]] = field(default_factory=list)
    failures: list[tuple[str, str]] = field(default_factory=list)


def scan_jobs(sources: Sequence[Path], output_dir: Path) -> list[ExtractJob]:
    """扫描 1 级目录的各个 2 级目录，收集其中的压缩包。

    输出目录里的位置按 ``输出 / 1 级目录 / 2 级目录`` 计算，压缩包只按
    文件内容识别，因此伪装扩展名同样会命中。
    """
    jobs: list[ExtractJob] = []
    for source in sources:
        if not source.is_dir():
            raise ValueError(f"解压来源必须是文件夹：{source}")
        for directory in _sorted_children(source):
            if not directory.is_dir():
                continue
            for item in _sorted_children(directory):
                if not item.is_file():
                    continue
                archive_format = detect_archive_format(item)
                if archive_format is None:
                    continue
                if _is_later_volume(item.name, archive_format):
                    continue
                target = output_dir / source.name / directory.name
                jobs.append(ExtractJob(item, target, archive_format))
    return jobs


def _is_later_volume(name: str, archive_format: str) -> bool:
    """分卷套只处理第一卷，后续卷由第一卷的解压一并读取。"""
    match = get_backend(archive_format).volume_name_pattern.fullmatch(name)
    return match is not None and int(match.group(2)) != 1


def extract_archives(
    jobs: Sequence[ExtractJob],
    output_dir: Path,
    *,
    rar_tool: Path | None = None,
    sevenzip_tool: Path | None = None,
    cancel_event: threading.Event | None = None,
    output_cb: Callable[[str], None] | None = None,
    progress_cb: Callable[[int, int, str], None] | None = None,
) -> ExtractOutcome:
    """逐个解开压缩包；单个压缩包失败只记录，不中断其余任务。

    rar_tool / sevenzip_tool 都是尽力提供（可以为 None），只在解到对应
    格式的压缩包而工具缺失时才记为该压缩包失败。
    """
    cancellation = Cancellation(cancel_event)
    outcome = ExtractOutcome(output=output_dir)
    total = len(jobs)
    with unpack_workspace(output_dir, cancellation, output_cb) as work:
        for index, job in enumerate(jobs, start=1):
            cancellation.check()
            if progress_cb is not None:
                progress_cb(index - 1, total, f"正在解压：{job.archive.name}")
            if _extract_job(
                job, work / f"item_{index}", cancellation, output_cb,
                rar_tool, sevenzip_tool, outcome,
            ):
                outcome.archives += 1
            if progress_cb is not None:
                progress_cb(index, total, f"已完成：{job.archive.name}")
    return outcome


def _extract_job(
    job: ExtractJob,
    work: Path,
    cancellation: Cancellation,
    output_cb: Callable[[str], None] | None,
    rar_tool: Path | None,
    sevenzip_tool: Path | None,
    outcome: ExtractOutcome,
) -> bool:
    """解开单个压缩包并把内容并入它的 2 级目录；失败只记录并返回 False。"""
    try:
        tool = _tool_for(job.archive_format, rar_tool, sevenzip_tool)
    except RuntimeError as error:
        outcome.failures.append((job.archive.name, str(error)))
        return False
    work.mkdir()
    try:
        extract_layer(
            tool, get_backend(job.archive_format), job.archive, work,
            (), [], None, 1, cancellation, output_cb,
        )
    except CancelledError:
        raise
    except RuntimeError as error:
        outcome.failures.append((job.archive.name, str(error)))
        return False
    payload = _single_directory(work) or work
    job.target.mkdir(parents=True, exist_ok=True)
    for entry in _sorted_children(payload):
        target = _free_path(job.target, entry.name)
        if target.name != entry.name:
            outcome.renames.append((
                _relative(job.target / entry.name, outcome.output),
                _relative(target, outcome.output),
            ))
        shutil.move(str(entry), str(target))
        outcome.entries += 1
    return True


def _tool_for(
    archive_format: str, rar_tool: Path | None, sevenzip_tool: Path | None,
) -> Path:
    """按压缩格式选工具，缺失时给出可执行的提示。"""
    if archive_format in (FORMAT_7Z, FORMAT_ZIP):
        if sevenzip_tool is None:
            raise RuntimeError(
                f"遇到 {archive_format} 压缩包，但没有可用的 7-Zip 命令行工具；请安装 7-Zip"
            )
        if archive_format == FORMAT_ZIP:
            return get_archive_platform().resolve_tool(
                str(sevenzip_tool), Path.cwd(), kind=FORMAT_ZIP
            )
        return sevenzip_tool
    if rar_tool is None:
        raise RuntimeError(
            "遇到 RAR 压缩包，但没有可用的 WinRAR/rar 命令行工具；请安装 WinRAR"
        )
    return rar_tool


def _single_directory(root: Path) -> Path | None:
    """压缩包内只有一层目录时返回该目录，用于剥掉外壳文件夹。"""
    entries = list(root.iterdir())
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return None


def _free_path(directory: Path, name: str) -> Path:
    """返回不冲突的目标路径；重名时按系统习惯在名称后追加序号。"""
    candidate = directory / name
    if not candidate.exists():
        return candidate
    stem = Path(name).stem
    suffix = Path(name).suffix
    index = 2
    while True:
        candidate = directory / f"{stem} ({index}){suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def _sorted_children(directory: Path) -> list[Path]:
    """按名称不区分大小写排序，保证多次运行的处理顺序稳定。"""
    return sorted(directory.iterdir(), key=lambda item: item.name.casefold())


def _relative(path: Path, root: Path) -> str:
    """重命名记录用相对输出目录的路径展示。"""
    return str(path.relative_to(root))
