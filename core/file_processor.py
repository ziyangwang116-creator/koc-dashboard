from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

import pandas as pd


class ExcelFileReadError(ValueError):
    """A readable per-file error that must not abort the complete batch."""


@dataclass(frozen=True)
class UploadedExcel:
    name: str
    content: bytes


def read_excel_file(uploaded: UploadedExcel) -> pd.DataFrame:
    if not uploaded.content:
        raise ExcelFileReadError("文件为空，无法读取。")
    try:
        dataframe = pd.read_excel(BytesIO(uploaded.content), engine="openpyxl")
    except Exception as exc:
        raise ExcelFileReadError(
            "无法打开该 xlsx 文件，请确认文件未损坏且格式正确。"
        ) from exc
    if dataframe.empty:
        raise ExcelFileReadError("Excel 中没有可处理的数据行。")
    return dataframe
