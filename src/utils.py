from __future__ import annotations

import io
import re
from datetime import datetime
from typing import Any

import pandas as pd


def safe_read_csv(file_or_path: Any) -> pd.DataFrame:
    """Read CSV with common encodings and preserve all columns as strings where possible."""
    if file_or_path is None:
        return pd.DataFrame()
    encodings = ["utf-8-sig", "utf-8", "gb18030", "gbk"]
    last_error: Exception | None = None
    for encoding in encodings:
        try:
            if hasattr(file_or_path, "seek"):
                file_or_path.seek(0)
            return pd.read_csv(file_or_path, encoding=encoding, dtype=str).fillna("")
        except Exception as exc:  # noqa: BLE001 - keep trying encodings
            last_error = exc
    if isinstance(file_or_path, (str, bytes, io.IOBase)):
        raise ValueError(f"CSV读取失败: {last_error}") from last_error
    return pd.DataFrame()


def normalize_text(value: Any) -> str:
    text = "" if value is None else str(value)
    text = text.strip()
    text = re.sub(r"\s+", " ", text)
    return text


def normalize_for_match(value: Any) -> str:
    return normalize_text(value).lower().replace(" ", "")


def escape_sql_string(value: Any) -> str:
    return normalize_text(value).replace("'", "''")


def count_distribution(df: pd.DataFrame, column: str) -> pd.DataFrame:
    if df.empty or column not in df.columns:
        return pd.DataFrame(columns=[column, "count"])
    return df[column].fillna("").replace("", "(空)").value_counts().rename_axis(column).reset_index(name="count")


def timestamp_string() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def to_number(value: Any, default: float = 0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def unique_nonempty(values: list[Any] | pd.Series) -> list[str]:
    return sorted({normalize_text(v) for v in values if normalize_text(v)})
