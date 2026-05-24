from __future__ import annotations

import pandas as pd

from .utils import escape_sql_string, normalize_text


def _cte_values(values: list[str], alias: str) -> str:
    if not values:
        return f"    SELECT CAST(NULL AS VARCHAR) AS {alias} WHERE 1 = 0"
    lines = [f"    SELECT '{escape_sql_string(values[0])}' AS {alias}"]
    for value in values[1:]:
        lines.append(f"    UNION ALL SELECT '{escape_sql_string(value)}'")
    return "\n".join(lines)


def generate_hdr_sql(final_disease_names: pd.DataFrame, final_icd_codes: pd.DataFrame) -> str:
    disease_values = []
    if not final_disease_names.empty and "disease_name" in final_disease_names.columns:
        disease_values = [normalize_text(x) for x in final_disease_names["disease_name"].tolist() if normalize_text(x)]
    icd_values = []
    if not final_icd_codes.empty and "icd_code" in final_icd_codes.columns:
        icd_values = [normalize_text(x) for x in final_icd_codes["icd_code"].tolist() if normalize_text(x)]
    return f"""-- WHALE/HDR 疾病case筛选SQL（管理员审核后执行）
-- 请管理员根据真实环境替换表名和字段名；本SQL不会直接连接任何生产库。
-- 默认疾病名称清单表: hive.hdr.whale_disease_term_inventory
-- 默认ICD清单表: hive.hdr.whale_icd_inventory
-- 默认患者字段: archive_corrected；默认就诊字段: visitid

WITH included_disease_terms AS (
{_cte_values(disease_values, 'disease_name')}
),
disease_match AS (
    SELECT DISTINCT
        a.archive_corrected,
        a.visitid,
        'disease_name' AS match_type,
        a.disease_name AS matched_value,
        a.source_type,
        a.diagnosis_type,
        a.diagnosis_type_norm
    FROM hive.hdr.whale_disease_term_inventory a
    JOIN included_disease_terms b
      ON a.disease_name = b.disease_name
),
included_icd_codes AS (
{_cte_values(icd_values, 'icd_code')}
),
icd_match AS (
    SELECT DISTINCT
        a.archive_corrected,
        a.visitid,
        'icd_code' AS match_type,
        a.icd_code AS matched_value,
        a.source_type,
        a.diagnosis_type,
        a.diagnosis_type_norm
    FROM hive.hdr.whale_icd_inventory a
    JOIN included_icd_codes b
      ON a.icd_code = b.icd_code
)
SELECT DISTINCT *
FROM (
    SELECT * FROM disease_match
    UNION ALL
    SELECT * FROM icd_match
) t;
"""
