from __future__ import annotations

import json
import os

import pandas as pd
import streamlit as st

from src.classifier import apply_user_mode_selection, classify_candidates
from src.deepseek_client import call_expansion, call_json_repair
from src.diagnosis_type import apply_diagnosis_type_mapping, build_default_priority, export_mapping_yaml, load_mapping_yaml
from src.parsers import parse_expansion_response
from src.recall import recall_disease_terms, recall_icd_terms
from src.task_package import build_task_zip
from src.utils import count_distribution, safe_read_csv, timestamp_string, unique_nonempty

st.set_page_config(page_title="WHALE/HDR疾病case筛选任务生成工具", layout="wide")
st.title("WHALE/HDR 疾病case筛选任务生成工具 MVP")
st.caption("仅处理脱敏疾病名称、ICD编码、来源类型、诊断类型和统计人数；生成的SQL/R代码供管理员审核执行。")

if "expansion" not in st.session_state:
    st.session_state.expansion = None
if "disease_candidates" not in st.session_state:
    st.session_state.disease_candidates = pd.DataFrame()
if "icd_candidates" not in st.session_state:
    st.session_state.icd_candidates = pd.DataFrame()
if "disease_classified" not in st.session_state:
    st.session_state.disease_classified = pd.DataFrame()
if "icd_classified" not in st.session_state:
    st.session_state.icd_classified = pd.DataFrame()
if "warnings" not in st.session_state:
    st.session_state.warnings = []
if "api_success" not in st.session_state:
    st.session_state.api_success = False
if "json_repaired" not in st.session_state:
    st.session_state.json_repaired = False

with st.sidebar:
    st.header("运行状态")
    if os.environ.get("DEEPSEEK_API_KEY"):
        st.success("已检测到 DEEPSEEK_API_KEY")
    else:
        st.warning("未检测到 DEEPSEEK_API_KEY；可使用规则兜底流程。")
    use_api = st.checkbox("调用DeepSeek API", value=bool(os.environ.get("DEEPSEEK_API_KEY")))
    st.info("请勿上传患者ID、姓名、身份证、visitid、完整病历原文等患者级敏感信息。")

st.header("1. 数据上传区")
col1, col2 = st.columns(2)
with col1:
    disease_file = st.file_uploader("上传 disease_terms.csv", type=["csv"], key="disease_file")
with col2:
    icd_file = st.file_uploader("上传 icd_terms.csv", type=["csv"], key="icd_file")

@st.cache_data(show_spinner=False)
def _read_uploaded(file):
    return safe_read_csv(file)

disease_df = _read_uploaded(disease_file) if disease_file else pd.DataFrame()
icd_df = _read_uploaded(icd_file) if icd_file else pd.DataFrame()

st.subheader("2. 诊断类型配置区")
mapping_file = st.file_uploader("上传已有 diagnosis_type_mapping.yaml（可选）", type=["yaml", "yml"])
loaded_mapping = load_mapping_yaml(mapping_file) if mapping_file else {}

combined_diag = []
for frame in [disease_df, icd_df]:
    if not frame.empty and "diagnosis_type" in frame.columns:
        combined_diag.extend(frame["diagnosis_type"].tolist())
raw_diag_values = unique_nonempty(combined_diag)
base_mapping = {raw: loaded_mapping.get(raw) or apply_diagnosis_type_mapping(pd.DataFrame({"diagnosis_type": [raw]})).loc[0, "diagnosis_type_norm"] for raw in raw_diag_values}
map_df = pd.DataFrame([{"diagnosis_type": k, "diagnosis_type_norm": v} for k, v in base_mapping.items()])
if not map_df.empty:
    edited_map_df = st.data_editor(map_df, num_rows="dynamic", use_container_width=True, key="mapping_editor")
else:
    edited_map_df = map_df
mapping = dict(zip(edited_map_df.get("diagnosis_type", []), edited_map_df.get("diagnosis_type_norm", []))) if not edited_map_df.empty else {}
st.download_button("导出 diagnosis_type_mapping.yaml", export_mapping_yaml(mapping), file_name="diagnosis_type_mapping.yaml")

disease_df = apply_diagnosis_type_mapping(disease_df, mapping) if not disease_df.empty else disease_df
icd_df = apply_diagnosis_type_mapping(icd_df, mapping) if not icd_df.empty else icd_df

c1, c2 = st.columns(2)
c1.metric("疾病名称总数", len(disease_df))
c2.metric("ICD编码总数", len(icd_df))
with st.expander("数据分布", expanded=False):
    a, b, c = st.columns(3)
    with a:
        st.write("source_type分布")
        st.dataframe(pd.concat([count_distribution(disease_df, "source_type"), count_distribution(icd_df, "source_type")]).groupby("source_type", as_index=False)["count"].sum() if (not disease_df.empty or not icd_df.empty) else pd.DataFrame())
    with b:
        st.write("diagnosis_type分布")
        st.dataframe(pd.concat([count_distribution(disease_df, "diagnosis_type"), count_distribution(icd_df, "diagnosis_type")]).groupby("diagnosis_type", as_index=False)["count"].sum() if (not disease_df.empty or not icd_df.empty) else pd.DataFrame())
    with c:
        st.write("diagnosis_type_norm分布")
        st.dataframe(pd.concat([count_distribution(disease_df, "diagnosis_type_norm"), count_distribution(icd_df, "diagnosis_type_norm")]).groupby("diagnosis_type_norm", as_index=False)["count"].sum() if (not disease_df.empty or not icd_df.empty) else pd.DataFrame())

st.header("3. 用户输入区")
col1, col2 = st.columns(2)
with col1:
    target_disease = st.text_input("目标疾病", placeholder="例如：慢性肾脏病")
    task_name = st.text_input("任务名称", value=f"疾病筛选任务_{timestamp_string()}")
with col2:
    user_notes = st.text_area("用户补充说明", placeholder="例如：仅纳入明确诊断，排除疑似病例", height=90)

all_source_types = unique_nonempty(list(disease_df.get("source_type", [])) + list(icd_df.get("source_type", [])))
all_diag_norm = unique_nonempty(list(disease_df.get("diagnosis_type_norm", [])) + list(icd_df.get("diagnosis_type_norm", [])))
default_diag_priority = build_default_priority(all_diag_norm)
selected_sources = st.multiselect("选择纳入来源类型", all_source_types, default=all_source_types)
selected_diag = st.multiselect("选择纳入诊断类型归并", all_diag_norm, default=all_diag_norm)
opts = st.columns(4)
include_history = opts[0].checkbox("纳入既往史", value=False)
include_present_history = opts[1].checkbox("纳入现病史", value=True)
include_suspected = opts[2].checkbox("纳入疑似诊断", value=False)
include_related = opts[3].checkbox("纳入相关但不等同疾病", value=False)

source_priority_text = st.text_area("来源类型优先级（每行一个，越靠前优先级越高）", value="\n".join(all_source_types), height=120)
diag_priority_text = st.text_area("诊断类型优先级（每行一个，越靠前优先级越高）", value="\n".join(default_diag_priority), height=160)
source_priority = [x.strip() for x in source_priority_text.splitlines() if x.strip()]
diag_priority = [x.strip() for x in diag_priority_text.splitlines() if x.strip()]

filtered_disease = disease_df.copy()
filtered_icd = icd_df.copy()
if selected_sources:
    if "source_type" in filtered_disease.columns:
        filtered_disease = filtered_disease[filtered_disease["source_type"].isin(selected_sources)]
    if "source_type" in filtered_icd.columns:
        filtered_icd = filtered_icd[filtered_icd["source_type"].isin(selected_sources)]
if selected_diag:
    filtered_disease = filtered_disease[filtered_disease["diagnosis_type_norm"].isin(selected_diag)] if not filtered_disease.empty else filtered_disease
    filtered_icd = filtered_icd[filtered_icd["diagnosis_type_norm"].isin(selected_diag)] if not filtered_icd.empty else filtered_icd

st.header("4. 自动扩展区")
if st.button("生成/刷新疾病表达扩展", disabled=not target_disease):
    raw, ok, msg = call_expansion(target_disease, user_notes, all_source_types, raw_diag_values) if use_api else ("", False, "已选择不调用API。")
    expansion, warnings = parse_expansion_response(raw, target_disease, call_json_repair)
    st.session_state.expansion = expansion
    st.session_state.warnings.extend(warnings + ([msg] if msg else []))
    st.session_state.api_success = st.session_state.api_success or ok

expansion = st.session_state.expansion or {
    "target_disease": target_disease,
    "standard_name_guess": target_disease,
    "synonyms_cn": [],
    "abbreviations": [],
    "english_terms": [],
    "icd_keywords": [],
    "include_keywords": [target_disease] if target_disease else [],
    "possible_keywords": [],
    "related_keywords": [],
    "exclude_keywords": ["未见", "否认", "排除", "待排"],
    "negation_keywords": ["未见", "否认", "排除", "无"],
    "suspected_keywords": ["待排", "可能", "疑似", "？", "?"],
    "history_keywords": [],
    "source_priority_advice": [],
    "caution_notes": [],
}

editable_fields = ["synonyms_cn", "abbreviations", "english_terms", "icd_keywords", "include_keywords", "possible_keywords", "related_keywords", "exclude_keywords", "negation_keywords", "suspected_keywords", "history_keywords", "caution_notes"]
cols = st.columns(2)
for i, field in enumerate(editable_fields):
    with cols[i % 2]:
        text_value = st.text_area(field, value="\n".join(expansion.get(field, [])), height=100, key=f"exp_{field}")
        expansion[field] = [x.strip() for x in text_value.splitlines() if x.strip()]
expansion["target_disease"] = target_disease or expansion.get("target_disease", "")
expansion["standard_name_guess"] = st.text_input("standard_name_guess", value=expansion.get("standard_name_guess", target_disease))
st.session_state.expansion = expansion

st.header("5. 候选召回区")
if st.button("执行候选召回", disabled=not target_disease):
    disease_candidates, disease_trunc = recall_disease_terms(filtered_disease, expansion, diag_priority)
    icd_candidates, icd_trunc = recall_icd_terms(filtered_icd, expansion, diag_priority)
    st.session_state.disease_candidates = disease_candidates
    st.session_state.icd_candidates = icd_candidates
    st.session_state.truncation = {"disease": disease_trunc, "icd": icd_trunc}

disease_candidates = st.session_state.disease_candidates
icd_candidates = st.session_state.icd_candidates
c1, c2 = st.columns(2)
c1.metric("疾病名称候选", len(disease_candidates))
c2.metric("ICD候选", len(icd_candidates))
with st.expander("疾病名称候选", expanded=True):
    st.dataframe(disease_candidates, use_container_width=True)
with st.expander("ICD编码候选", expanded=True):
    st.dataframe(icd_candidates, use_container_width=True)

st.header("6. 模型分层区")
if st.button("执行模型分层/规则兜底", disabled=disease_candidates.empty and icd_candidates.empty):
    disease_classified, d_meta = classify_candidates(disease_candidates, "disease_name", target_disease, expansion, user_notes, use_api=use_api)
    icd_classified, i_meta = classify_candidates(icd_candidates, "icd_code", target_disease, expansion, user_notes, use_api=use_api)
    st.session_state.disease_classified = disease_classified
    st.session_state.icd_classified = icd_classified
    st.session_state.warnings.extend(d_meta.get("warnings", []) + i_meta.get("warnings", []))
    st.session_state.api_success = st.session_state.api_success or d_meta.get("api_success", False) or i_meta.get("api_success", False)
    st.session_state.json_repaired = st.session_state.json_repaired or d_meta.get("json_repaired", False) or i_meta.get("json_repaired", False)

disease_classified = st.session_state.disease_classified
icd_classified = st.session_state.icd_classified
with st.expander("疾病名称分层结果", expanded=True):
    st.dataframe(disease_classified, use_container_width=True)
with st.expander("ICD编码分层结果", expanded=True):
    st.dataframe(icd_classified, use_container_width=True)

st.header("7. 用户确认区")
selection_mode = st.radio("筛选模式", ["严格模式", "宽松模式", "高召回模式", "自定义模式"], horizontal=True)
custom_disease_ids = []
custom_icd_ids = []
if selection_mode == "自定义模式":
    custom_disease_ids = st.multiselect("手动勾选疾病名称候选ID", disease_classified.get("candidate_id", pd.Series(dtype=str)).astype(str).tolist()) if not disease_classified.empty else []
    custom_icd_ids = st.multiselect("手动勾选ICD候选ID", icd_classified.get("candidate_id", pd.Series(dtype=str)).astype(str).tolist()) if not icd_classified.empty else []

selected_disease_df = apply_user_mode_selection(disease_classified, selection_mode, include_history, include_present_history, include_suspected, include_related, custom_disease_ids) if not disease_classified.empty else disease_classified
selected_icd_df = apply_user_mode_selection(icd_classified, selection_mode, include_history, include_present_history, include_suspected, include_related, custom_icd_ids) if not icd_classified.empty else icd_classified
final_disease = selected_disease_df[selected_disease_df["final_include"]].copy() if not selected_disease_df.empty else pd.DataFrame()
final_icd = selected_icd_df[selected_icd_df["final_include"]].copy() if not selected_icd_df.empty else pd.DataFrame()
st.write(f"最终纳入疾病名称：{len(final_disease)} 条；最终纳入ICD编码：{len(final_icd)} 条")
st.dataframe(final_disease, use_container_width=True)
st.dataframe(final_icd, use_container_width=True)

st.header("8. 管理员任务包生成区")
metadata = {
    "task_name": task_name,
    "target_disease": target_disease,
    "user_notes": user_notes,
    "created_at": timestamp_string(),
    "disease_filename": getattr(disease_file, "name", ""),
    "icd_filename": getattr(icd_file, "name", ""),
    "disease_total": len(disease_df),
    "icd_total": len(icd_df),
    "selection_mode": selection_mode,
    "include_history": include_history,
    "include_present_history": include_present_history,
    "include_suspected": include_suspected,
    "include_related": include_related,
    "selected_source_types": selected_sources,
    "selected_diagnosis_types": selected_diag,
    "source_priority": source_priority,
    "diagnosis_priority": diag_priority,
    "disease_candidate_count": len(disease_candidates),
    "icd_candidate_count": len(icd_candidates),
    "final_disease_count": len(final_disease),
    "final_icd_count": len(final_icd),
    "candidate_truncated": any(x.get("truncated") for x in getattr(st.session_state, "truncation", {}).values()) if hasattr(st.session_state, "truncation") else False,
    "api_success": st.session_state.api_success,
    "json_repaired": st.session_state.json_repaired,
    "warnings": st.session_state.warnings,
}
classification_json = {
    "disease_name": disease_classified.to_dict(orient="records") if not disease_classified.empty else [],
    "icd_code": icd_classified.to_dict(orient="records") if not icd_classified.empty else [],
}
zip_bytes = build_task_zip(metadata, expansion, selected_disease_df, selected_icd_df, final_disease, final_icd, mapping, classification_json, disease_df, icd_df)
st.download_button("下载管理员任务包 ZIP", data=zip_bytes, file_name=f"{task_name or 'whale_hdr_task'}_{timestamp_string()}.zip", mime="application/zip")

if st.session_state.warnings:
    with st.expander("解析/API/流程警告", expanded=False):
        st.write("\n".join(f"- {w}" for w in st.session_state.warnings))
