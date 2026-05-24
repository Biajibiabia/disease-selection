from __future__ import annotations

from typing import Any, Callable

import pandas as pd

from .deepseek_client import call_classification_batch, call_json_repair
from .parsers import defaults_for_label, parse_classification_response
from .utils import normalize_for_match, normalize_text


def batch_candidates(candidates: pd.DataFrame, batch_size: int = 150) -> list[pd.DataFrame]:
    return [candidates.iloc[i : i + batch_size].copy() for i in range(0, len(candidates), batch_size)]


def _contains_any(text: str, keywords: list[str]) -> bool:
    norm = normalize_for_match(text)
    return any(normalize_for_match(k) and normalize_for_match(k) in norm for k in keywords)


def fallback_rule_classification(candidates: pd.DataFrame, candidate_type: str, expansion: dict[str, Any]) -> list[dict[str, Any]]:
    negation = expansion.get("negation_keywords", ["未见", "否认", "排除", "无"])
    suspected = expansion.get("suspected_keywords", ["待排", "可能", "疑似", "？", "?"])
    include = expansion.get("include_keywords", []) + expansion.get("synonyms_cn", []) + expansion.get("abbreviations", [])
    possible = expansion.get("possible_keywords", [])
    related = expansion.get("related_keywords", [])
    rows: list[dict[str, Any]] = []
    for _, row in candidates.iterrows():
        text = normalize_text(row.get("candidate_text") or row.get("disease_name") or row.get("icd_code") or "")
        combined = " ".join([text, normalize_text(row.get("icd_name", "")), normalize_text(row.get("diagnosis_type_norm", "")), normalize_text(row.get("source_type", ""))])
        if _contains_any(combined, negation):
            label, reason = "negated", "命中否定词"
        elif _contains_any(combined, suspected):
            label, reason = "suspected", "命中疑似词"
        elif "既往史" in combined:
            label, reason = "history", "来源或类型为既往史"
        elif _contains_any(combined, include):
            label, reason = "recommend_include", "命中纳入词"
        elif _contains_any(combined, possible):
            label, reason = "possible_include", "命中可能词"
        elif _contains_any(combined, related):
            label, reason = "related_not_equal", "命中相关词"
        else:
            label, reason = "uncertain", "规则无法判断"
        rows.append({
            "candidate_id": str(row.get("candidate_id", "")),
            "candidate_text": text,
            "candidate_type": candidate_type,
            "label": label,
            "reason": reason,
            **defaults_for_label(label),
        })
    return rows


def _candidate_payload(batch: pd.DataFrame, candidate_type: str) -> list[dict[str, Any]]:
    fields = ["candidate_id", "candidate_text", "disease_name", "icd_code", "icd_name", "source_type", "diagnosis_type", "diagnosis_type_norm", "person_count", "recall_reason", "recall_score"]
    payload = []
    for _, row in batch.iterrows():
        item = {field: row.get(field, "") for field in fields if field in batch.columns}
        item["candidate_type"] = candidate_type
        payload.append(item)
    return payload


def classify_candidates(candidates: pd.DataFrame, candidate_type: str, target_disease: str, expansion: dict[str, Any], user_notes: str, use_api: bool = True, batch_size: int = 150, classification_api: Callable[..., tuple[str, bool, str]] = call_classification_batch) -> tuple[pd.DataFrame, dict[str, Any]]:
    if candidates.empty:
        return candidates.copy(), {"api_success": False, "warnings": [], "json_repaired": False}
    all_items: list[dict[str, Any]] = []
    warnings: list[str] = []
    api_success = False
    json_repaired = False
    for batch in batch_candidates(candidates, batch_size):
        if use_api:
            raw, ok, msg = classification_api(target_disease, expansion, candidate_type, _candidate_payload(batch, candidate_type), user_notes)
            if ok:
                ids = [str(x) for x in batch["candidate_id"].tolist()]
                parsed_items, parse_warnings, repaired = parse_classification_response(raw, ids, candidate_type, call_json_repair)
                warnings.extend(parse_warnings)
                json_repaired = json_repaired or repaired
                if parsed_items:
                    all_items.extend(parsed_items)
                    api_success = True
                    continue
            warnings.append(msg or "模型分层失败，使用规则兜底。")
        all_items.extend(fallback_rule_classification(batch, candidate_type, expansion))
    class_df = pd.DataFrame(all_items)
    merged = candidates.merge(class_df, on="candidate_id", how="left", suffixes=("", "_model"))
    for col in ["label", "reason", "default_include_strict", "default_include_broad", "default_include_high_recall"]:
        if col not in merged.columns:
            merged[col] = "" if col in ["label", "reason"] else False
    return merged, {"api_success": api_success, "warnings": warnings, "json_repaired": json_repaired}


def apply_user_mode_selection(df: pd.DataFrame, mode: str, include_history: bool, include_present_history: bool, include_suspected: bool, include_related: bool, selected_ids: list[str] | None = None) -> pd.DataFrame:
    result = df.copy()
    if result.empty:
        result["final_include"] = []
        return result
    if mode == "严格模式":
        include = result["label"].eq("recommend_include")
    elif mode == "宽松模式":
        include = result["label"].isin(["recommend_include", "possible_include"])
    elif mode == "高召回模式":
        include = result["label"].isin(["recommend_include", "possible_include", "related_not_equal"])
    else:
        selected = set(selected_ids or [])
        include = result["candidate_id"].astype(str).isin(selected)
    if not include_suspected:
        include &= ~result["label"].eq("suspected")
    if not include_history:
        include &= ~result["label"].eq("history")
        include &= ~result.get("diagnosis_type_norm", pd.Series(index=result.index, dtype=str)).fillna("").eq("既往史")
    if not include_present_history:
        include &= ~result.get("diagnosis_type_norm", pd.Series(index=result.index, dtype=str)).fillna("").eq("现病史")
    if not include_related:
        include &= ~result["label"].eq("related_not_equal")
    result["final_include"] = include
    return result
