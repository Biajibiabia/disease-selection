from __future__ import annotations

import json
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd

from .codegen_r import generate_r_code
from .codegen_sql import generate_hdr_sql
from .diagnosis_type import export_mapping_yaml
from .utils import timestamp_string


def _fmt_list(values: list[Any]) -> str:
    return ", ".join(map(str, values)) if values else "无"


def write_task_summary(metadata: dict[str, Any], warnings: list[str] | None = None) -> str:
    expansion = metadata.get("expansion", {}) or {}
    lines = [
        f"# WHALE/HDR疾病case筛选任务摘要",
        "",
        f"- 任务名称: {metadata.get('task_name', '')}",
        f"- 目标疾病: {metadata.get('target_disease', '')}",
        f"- 用户补充说明: {metadata.get('user_notes', '')}",
        f"- 创建时间: {metadata.get('created_at', timestamp_string())}",
        f"- 输入疾病名称文件: {metadata.get('disease_filename', '')}",
        f"- 输入ICD编码文件: {metadata.get('icd_filename', '')}",
        f"- 疾病名称总数: {metadata.get('disease_total', 0)}",
        f"- ICD编码总数: {metadata.get('icd_total', 0)}",
        f"- 用户选择的筛选模式: {metadata.get('selection_mode', '')}",
        f"- 是否纳入既往史: {metadata.get('include_history', False)}",
        f"- 是否纳入现病史: {metadata.get('include_present_history', False)}",
        f"- 是否纳入疑似诊断: {metadata.get('include_suspected', False)}",
        f"- 是否纳入相关但不等同疾病: {metadata.get('include_related', False)}",
        f"- 来源类型选择: {_fmt_list(metadata.get('selected_source_types', []))}",
        f"- 诊断类型选择: {_fmt_list(metadata.get('selected_diagnosis_types', []))}",
        f"- 来源优先级: {_fmt_list(metadata.get('source_priority', []))}",
        f"- 诊断类型优先级: {_fmt_list(metadata.get('diagnosis_priority', []))}",
        "",
        "## DeepSeek扩展词摘要",
        f"- 标准名称猜测: {expansion.get('standard_name_guess', '')}",
        f"- 纳入关键词: {_fmt_list(expansion.get('include_keywords', []))}",
        f"- 可能关键词: {_fmt_list(expansion.get('possible_keywords', []))}",
        f"- 相关关键词: {_fmt_list(expansion.get('related_keywords', []))}",
        f"- ICD关键词: {_fmt_list(expansion.get('icd_keywords', []))}",
        f"- 注意事项: {_fmt_list(expansion.get('caution_notes', []))}",
        "",
        "## 结果统计",
        f"- 疾病名称候选数量: {metadata.get('disease_candidate_count', 0)}",
        f"- ICD候选数量: {metadata.get('icd_candidate_count', 0)}",
        f"- 最终纳入疾病名称数量: {metadata.get('final_disease_count', 0)}",
        f"- 最终纳入ICD编码数量: {metadata.get('final_icd_count', 0)}",
        f"- 是否发生候选截断: {metadata.get('candidate_truncated', False)}",
        f"- API调用是否成功: {metadata.get('api_success', False)}",
        f"- JSON解析是否发生修复: {metadata.get('json_repaired', False)}",
        "",
        "## 需要管理员注意的问题",
    ]
    all_warnings = warnings or metadata.get("warnings", []) or []
    if all_warnings:
        lines.extend([f"- {warning}" for warning in all_warnings])
    else:
        lines.append("- 请审核SQL/R代码中的表名、字段名、最终纳入清单和疾病边界后再执行。")
    return "\n".join(lines) + "\n"


def export_csv_files(output_dir: Path, files: dict[str, pd.DataFrame]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename, df in files.items():
        df.to_csv(output_dir / filename, index=False, encoding="utf-8-sig")


def build_task_zip(
    metadata: dict[str, Any],
    expansion: dict[str, Any],
    disease_candidates: pd.DataFrame,
    icd_candidates: pd.DataFrame,
    final_disease_names: pd.DataFrame,
    final_icd_codes: pd.DataFrame,
    diagnosis_mapping: dict[str, str],
    classification_json: dict[str, Any],
    source_disease_df: pd.DataFrame | None = None,
    source_icd_df: pd.DataFrame | None = None,
) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        (out / "task_summary.md").write_text(write_task_summary({**metadata, "expansion": expansion}), encoding="utf-8")
        (out / "deepseek_expansion.json").write_text(json.dumps(expansion, ensure_ascii=False, indent=2), encoding="utf-8")
        (out / "model_classification.json").write_text(json.dumps(classification_json, ensure_ascii=False, indent=2), encoding="utf-8")
        (out / "extract_hdr.sql").write_text(generate_hdr_sql(final_disease_names, final_icd_codes), encoding="utf-8")
        (out / "extract_local.R").write_text(generate_r_code(), encoding="utf-8")
        (out / "diagnosis_type_mapping.yaml").write_text(export_mapping_yaml(diagnosis_mapping), encoding="utf-8")
        csvs = {
            "disease_name_candidates.csv": disease_candidates,
            "icd_candidates.csv": icd_candidates,
            "final_included_disease_names.csv": final_disease_names,
            "final_included_icd_codes.csv": final_icd_codes,
        }
        if source_disease_df is not None:
            csvs["disease_terms.csv"] = source_disease_df
        if source_icd_df is not None:
            csvs["icd_terms.csv"] = source_icd_df
        export_csv_files(out, csvs)
        zip_path = out / "task_package.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for path in out.iterdir():
                if path.name != "task_package.zip":
                    zf.write(path, arcname=path.name)
        return zip_path.read_bytes()
