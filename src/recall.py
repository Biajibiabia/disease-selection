from __future__ import annotations

from typing import Any

import pandas as pd

from .utils import normalize_for_match, normalize_text, to_number


def _keywords(expansion: dict[str, Any], fields: list[str]) -> list[str]:
    values: list[str] = []
    for field in fields:
        value = expansion.get(field, [])
        if isinstance(value, list):
            values.extend(value)
        elif value:
            values.append(str(value))
    return [normalize_text(v) for v in values if normalize_text(v)]


def _priority_rank(value: str, priority: list[str]) -> int:
    return priority.index(value) if value in priority else len(priority) + 1


def calculate_recall_score(match_level: str, person_count: Any = 0, priority_rank: int = 99) -> float:
    base = {"exact": 100, "prefix": 95, "contains": 80, "case_insensitive": 70, "keyword": 60}.get(match_level, 40)
    return base + min(to_number(person_count), 100000) / 100000 - priority_rank / 100


def deduplicate_candidates(df: pd.DataFrame, id_col: str) -> pd.DataFrame:
    if df.empty:
        return df
    return df.sort_values("recall_score", ascending=False).drop_duplicates(subset=[id_col], keep="first").reset_index(drop=True)


def truncate_candidates(df: pd.DataFrame, max_rows: int) -> tuple[pd.DataFrame, bool, int]:
    original = len(df)
    if original > max_rows:
        return df.head(max_rows).copy(), True, original - max_rows
    return df, False, 0


def recall_disease_terms(df: pd.DataFrame, expansion: dict[str, Any], diagnosis_priority: list[str] | None = None, max_rows: int = 2000) -> tuple[pd.DataFrame, dict[str, Any]]:
    if df.empty or "disease_name" not in df.columns:
        return pd.DataFrame(), {"truncated": False, "dropped_count": 0, "original_count": 0}
    result = df.copy()
    if "term_id" not in result.columns:
        result["term_id"] = [f"term_{i}" for i in range(len(result))]
    result["candidate_id"] = result["term_id"].astype(str)
    include_keywords = _keywords(expansion, ["include_keywords", "synonyms_cn", "abbreviations", "english_terms"])
    possible_keywords = _keywords(expansion, ["possible_keywords"])
    all_keywords = include_keywords + possible_keywords
    rows = []
    priority = diagnosis_priority or []
    for _, row in result.iterrows():
        text = normalize_text(row.get("disease_name", ""))
        text_norm = normalize_for_match(text)
        reasons: list[str] = []
        level = ""
        for kw in all_keywords:
            kw_norm = normalize_for_match(kw)
            if not kw_norm:
                continue
            if text == kw:
                reasons.append(f"精确匹配:{kw}")
                level = "exact"
            elif text_norm == kw_norm:
                reasons.append(f"大小写/空格归一匹配:{kw}")
                level = level or "case_insensitive"
            elif kw_norm in text_norm:
                reasons.append(f"包含匹配:{kw}")
                level = level or "contains"
        if reasons:
            norm = normalize_text(row.get("diagnosis_type_norm", ""))
            rank = _priority_rank(norm, priority)
            item = row.to_dict()
            item["candidate_text"] = text
            item["recall_reason"] = "; ".join(reasons[:5])
            item["recall_score"] = calculate_recall_score(level or "keyword", row.get("person_count", 0), rank)
            rows.append(item)
    candidates = pd.DataFrame(rows)
    if candidates.empty:
        return candidates, {"truncated": False, "dropped_count": 0, "original_count": 0}
    candidates = deduplicate_candidates(candidates, "candidate_id").sort_values("recall_score", ascending=False)
    original = len(candidates)
    candidates, truncated, dropped = truncate_candidates(candidates, max_rows)
    return candidates.reset_index(drop=True), {"truncated": truncated, "dropped_count": dropped, "original_count": original}


def recall_icd_terms(df: pd.DataFrame, expansion: dict[str, Any], diagnosis_priority: list[str] | None = None, max_rows: int = 1000) -> tuple[pd.DataFrame, dict[str, Any]]:
    if df.empty or "icd_code" not in df.columns:
        return pd.DataFrame(), {"truncated": False, "dropped_count": 0, "original_count": 0}
    result = df.copy()
    if "icd_id" not in result.columns:
        result["icd_id"] = [f"icd_{i}" for i in range(len(result))]
    if "icd_name" not in result.columns:
        result["icd_name"] = ""
    result["candidate_id"] = result["icd_id"].astype(str)
    icd_keywords = _keywords(expansion, ["icd_keywords"])
    name_keywords = _keywords(expansion, ["standard_name_guess", "target_disease", "include_keywords", "synonyms_cn"])
    rows = []
    priority = diagnosis_priority or []
    for _, row in result.iterrows():
        code = normalize_text(row.get("icd_code", ""))
        name = normalize_text(row.get("icd_name", ""))
        code_norm = normalize_for_match(code).upper()
        name_norm = normalize_for_match(name)
        reasons: list[str] = []
        level = ""
        for kw in icd_keywords:
            kw_clean = normalize_text(kw)
            kw_norm = normalize_for_match(kw_clean).upper()
            if not kw_norm:
                continue
            if code_norm == kw_norm:
                reasons.append(f"ICD精确匹配:{kw_clean}")
                level = "exact"
            elif code_norm.startswith(kw_norm):
                reasons.append(f"ICD前缀匹配:{kw_clean}")
                level = level or "prefix"
            elif normalize_for_match(kw_clean) in name_norm:
                reasons.append(f"ICD名称关键词:{kw_clean}")
                level = level or "keyword"
        for kw in name_keywords:
            kw_norm = normalize_for_match(kw)
            if kw_norm and kw_norm in name_norm:
                reasons.append(f"ICD名称匹配:{kw}")
                level = level or "keyword"
        if reasons:
            norm = normalize_text(row.get("diagnosis_type_norm", ""))
            rank = _priority_rank(norm, priority)
            item = row.to_dict()
            item["candidate_text"] = code
            item["recall_reason"] = "; ".join(reasons[:5])
            item["recall_score"] = calculate_recall_score(level or "keyword", row.get("person_count", 0), rank)
            rows.append(item)
    candidates = pd.DataFrame(rows)
    if candidates.empty:
        return candidates, {"truncated": False, "dropped_count": 0, "original_count": 0}
    candidates = deduplicate_candidates(candidates, "candidate_id").sort_values("recall_score", ascending=False)
    original = len(candidates)
    candidates, truncated, dropped = truncate_candidates(candidates, max_rows)
    return candidates.reset_index(drop=True), {"truncated": truncated, "dropped_count": dropped, "original_count": original}
