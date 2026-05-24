from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from .utils import normalize_text

DEFAULT_DIAGNOSIS_PRIORITY = [
    "出院诊断",
    "修正诊断",
    "主要诊断",
    "ICD编码",
    "门急诊诊断",
    "入院诊断",
    "病理诊断",
    "体检结论",
    "既往史",
    "现病史",
    "未归类诊断",
]


def infer_diagnosis_type_norm(raw_value: Any) -> str:
    text = normalize_text(raw_value)
    if not text:
        return "未归类诊断"
    rules = [
        (("出院",), "出院诊断"),
        (("入院",), "入院诊断"),
        (("门急诊", "门诊"), "门急诊诊断"),
        (("急诊",), "急诊诊断"),
        (("修正",), "修正诊断"),
        (("主要",), "主要诊断"),
        (("次要",), "次要诊断"),
        (("病理",), "病理诊断"),
        (("既往",), "既往史"),
        (("现病",), "现病史"),
        (("体检", "阳性结论"), "体检结论"),
    ]
    for keywords, norm in rules:
        if any(keyword in text for keyword in keywords):
            return norm
    return "未归类诊断"


def load_mapping_yaml(file_or_path: Any) -> dict[str, str]:
    if file_or_path is None:
        return {}
    if hasattr(file_or_path, "read"):
        file_or_path.seek(0)
        content = file_or_path.read()
        if isinstance(content, bytes):
            content = content.decode("utf-8")
    else:
        path = Path(file_or_path)
        if not path.exists():
            return {}
        content = path.read_text(encoding="utf-8")
    data = yaml.safe_load(content) or {}
    if isinstance(data, dict) and "mapping" in data:
        data = data.get("mapping") or {}
    return {normalize_text(k): normalize_text(v) for k, v in data.items() if normalize_text(k)}


def export_mapping_yaml(mapping: dict[str, str]) -> str:
    return yaml.safe_dump({"mapping": mapping}, allow_unicode=True, sort_keys=True)


def apply_diagnosis_type_mapping(df: pd.DataFrame, mapping: dict[str, str] | None = None) -> pd.DataFrame:
    result = df.copy()
    if "diagnosis_type" not in result.columns:
        result["diagnosis_type"] = ""
    mapping = mapping or {}

    def norm(row: pd.Series) -> str:
        raw = normalize_text(row.get("diagnosis_type", ""))
        existing = normalize_text(row.get("diagnosis_type_norm", ""))
        if raw in mapping:
            return mapping[raw]
        return existing or infer_diagnosis_type_norm(raw)

    result["diagnosis_type_norm"] = result.apply(norm, axis=1)
    return result


def build_default_priority(observed: list[str]) -> list[str]:
    priority = [x for x in DEFAULT_DIAGNOSIS_PRIORITY if x in observed or x == "ICD编码"]
    for item in observed:
        if item and item not in priority:
            priority.append(item)
    return priority
