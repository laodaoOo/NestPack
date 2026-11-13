"""分卷大小的界面换算：数字与 KB / MB / GB 单位互转（无 Qt 依赖）。"""

from __future__ import annotations

import math
import re

# 分卷单位下拉选项：(显示名, 配置后缀)。RAR、7z 与 ZIP 后端都按 k/m/g 识别单位。
VOLUME_UNIT_OPTIONS = (
    ("KB", "k"),
    ("MB", "m"),
    ("GB", "g"),
)

# 新建分卷时默认选中的单位。
DEFAULT_VOLUME_UNIT = "m"

# 已保存的分卷写法：数字加可选单位，与 core.config.validation 保持一致。
VOLUME_SIZE_PATTERN = re.compile(r"^(?P<number>\d+(?:\.\d+)?)(?P<unit>[bBkKmMgG]?)$")

# 纯字节写法换算时依次尝试的单位，按 1024 进制。
BYTE_UNITS = (("g", 1024**3), ("m", 1024**2), ("k", 1024))


def split_volume_size(value: str | None) -> tuple[str, str]:
    """把配置里的分卷大小拆成输入框数字与单位后缀。

    带 k / m / g 的写法原样保留数字；纯字节写法换算成能整除的最大单位，
    除不尽时按 KB 向上取整。
    """
    match = VOLUME_SIZE_PATTERN.match((value or "").strip())
    if match is None:
        return "", DEFAULT_VOLUME_UNIT
    number = match.group("number")
    unit = match.group("unit").lower()
    if unit in {"k", "m", "g"}:
        return number, unit
    return _whole_unit_from_bytes(float(number))


def join_volume_size(number: str, unit: str) -> str | None:
    """把输入框数字与单位后缀拼成配置写法；数字为空表示不分卷。"""
    digits = number.strip()
    return f"{digits}{unit}" if digits else None


def _whole_unit_from_bytes(size: float) -> tuple[str, str]:
    """把纯字节大小换算成 KB / MB / GB，返回数字文本与单位后缀。"""
    for unit, base in BYTE_UNITS:
        if size >= base and size % base == 0:
            return f"{size / base:g}", unit
    return str(max(1, math.ceil(size / 1024))), "k"
