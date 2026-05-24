from __future__ import annotations

import json
import re
from typing import Any, Callable

EXPANSION_ARRAY_FIELDS = [
    "synonyms_cn",
    "abbreviations",
    "english_terms",
    "icd_keywords",
    "include_keywords",
    "possible_keywords",
    "related_keywords",
    "exclude_keywords",
    "negation_keywords",
    "suspected_keywords",
    "history_keywords",
    "source_priority_advice",
    "caution_notes",
]
EXPANSION_STRING_FIELDS = ["target_disease", "standard_name_guess"]
ALLOWED_LABELS = {
    "recommend_include",
    "possible_include",
    "related_not_equal",
    "suspected",
    "history",
    "negated",
    "exclude",
    "uncertain",
}
DEFAULT_INCLUSION = {
    "recommend_include": (True, True, True),
    "possible_include": (False, True, True),
    "related_not_equal": (False, False, True),
    "suspected": (False, False, False),
    "history": (False, False, False),
    "negated": (False, False, False),
    "exclude": (False, False, False),
    "uncertain": (False, False, False),
}


def strip_code_fence(text: str) -> str:
    text = (text or "").strip()
    match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return text


def parse_json_safely(text: str) -> tuple[Any | None, str | None]:
    try:
        return json.loads(strip_code_fence(text)), None
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


def _ensure_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    return [str(value).strip()]


def validate_and_fill_expansion(data: Any, target_disease: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        data = {}
    result: dict[str, Any] = {}
    result["target_disease"] = str(data.get("target_disease") or target_disease or "")
    result["standard_name_guess"] = str(data.get("standard_name_guess") or target_disease or "")
    for field in EXPANSION_ARRAY_FIELDS:
        result[field] = _ensure_list(data.get(field, []))
    if target_disease and target_disease not in result["include_keywords"]:
        result["include_keywords"].insert(0, target_disease)
    if not result["exclude_keywords"]:
        result["exclude_keywords"] = ["未见", "否认", "排除", "待排"]
    if not result["negation_keywords"]:
        result["negation_keywords"] = ["未见", "否认", "排除", "无"]
    if not result["suspected_keywords"]:
        result["suspected_keywords"] = ["待排", "可能", "疑似", "？", "?"]
    return result


def parse_expansion_response(raw_text: str, target_disease: str, repair_func: Callable[[str], tuple[str, bool, str]] | None = None) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    data, error = parse_json_safely(raw_text)
    if error and repair_func and raw_text:
        warnings.append(f"扩展JSON解析失败，尝试修复: {error}")
        repaired, ok, msg = repair_func(raw_text)
        if ok:
            data, error = parse_json_safely(repaired)
            if error:
                warnings.append(f"扩展JSON修复后仍解析失败: {error}")
            else:
                warnings.append("扩展JSON已由模型修复。")
        else:
            warnings.append(msg)
    if error:
        warnings.append("使用规则兜底扩展结果。")
        data = {"include_keywords": [target_disease]}
    return validate_and_fill_expansion(data, target_disease), warnings


def defaults_for_label(label: str) -> dict[str, bool]:
    strict, broad, high = DEFAULT_INCLUSION.get(label, DEFAULT_INCLUSION["uncertain"])
    return {
        "default_include_strict": strict,
        "default_include_broad": broad,
        "default_include_high_recall": high,
    }


def validate_and_fill_classification(data: Any, candidate_ids: list[str], candidate_type: str) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    raw_items = data.get("items", []) if isinstance(data, dict) else []
    if not isinstance(raw_items, list):
        raw_items = []
        warnings.append("模型分层结果缺少items数组。")
    allowed_ids = {str(x) for x in candidate_ids}
    seen: dict[str, dict[str, Any]] = {}
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        cid = str(item.get("candidate_id", ""))
        if cid not in allowed_ids:
            warnings.append(f"丢弃模型返回的多余candidate_id: {cid}")
            continue
        label = str(item.get("label", "uncertain"))
        if label not in ALLOWED_LABELS:
            warnings.append(f"candidate_id={cid} 的非法label已改为uncertain: {label}")
            label = "uncertain"
        filled = {
            "candidate_id": cid,
            "candidate_text": str(item.get("candidate_text", "")),
            "candidate_type": candidate_type,
            "label": label,
            "reason": str(item.get("reason", ""))[:80],
        }
        defaults = defaults_for_label(label)
        for field, default_value in defaults.items():
            filled[field] = bool(item.get(field, default_value)) if field in item else default_value
        seen[cid] = filled
    for cid in candidate_ids:
        cid = str(cid)
        if cid not in seen:
            defaults = defaults_for_label("uncertain")
            seen[cid] = {
                "candidate_id": cid,
                "candidate_text": "",
                "candidate_type": candidate_type,
                "label": "uncertain",
                "reason": "模型未返回该候选",
                **defaults,
            }
            warnings.append(f"模型遗漏candidate_id，已补uncertain: {cid}")
    return [seen[str(cid)] for cid in candidate_ids], warnings


def parse_classification_response(raw_text: str, candidate_ids: list[str], candidate_type: str, repair_func: Callable[[str], tuple[str, bool, str]] | None = None) -> tuple[list[dict[str, Any]], list[str], bool]:
    warnings: list[str] = []
    repaired_used = False
    data, error = parse_json_safely(raw_text)
    if error and repair_func and raw_text:
        warnings.append(f"分层JSON解析失败，尝试修复: {error}")
        repaired, ok, msg = repair_func(raw_text)
        if ok:
            data, error = parse_json_safely(repaired)
            repaired_used = error is None
            warnings.append("分层JSON已由模型修复。" if repaired_used else f"分层JSON修复后仍解析失败: {error}")
        else:
            warnings.append(msg)
    if error:
        warnings.append("分层JSON解析失败，将使用规则兜底分层。")
        return [], warnings, repaired_used
    items, more_warnings = validate_and_fill_classification(data, candidate_ids, candidate_type)
    return items, warnings + more_warnings, repaired_used
