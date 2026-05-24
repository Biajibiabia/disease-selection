from __future__ import annotations

import os
from pathlib import Path

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

for k, v in {
    "expansion": None,
    "disease_candidates": pd.DataFrame(),
    "icd_candidates": pd.DataFrame(),
    "disease_classified": pd.DataFrame(),
    "icd_classified": pd.DataFrame(),
    "warnings": [],
    "api_success": False,
    "json_repaired": False,
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

with st.sidebar:
    st.header("运行状态")
    if os.environ.get("DEEPSEEK_API_KEY"):
        st.success("已检测到 DEEPSEEK_API_KEY")
    else:
        st.warning("未检测到 DEEPSEEK_API_KEY；可使用规则兜底流程。")
    use_api = st.checkbox("调用DeepSeek API", value=bool(os.environ.get("DEEPSEEK_API_KEY")))
    st.info("请勿上传患者ID、姓名、身份证、visitid、完整病历原文等患者级敏感信息。")

st.header("0. 使用说明")
with st.expander("我需要做什么？会得到什么？", expanded=True):
    st.markdown(
        """
- **你需要做的事**：
  1) 确认本地两份脱敏清单路径（疾病名称清单、ICD清单）；
  2) 输入目标疾病与补充口径；
  3) 审核 AI 给出的**精准词**与**模糊词**；
  4) 复核候选分层并确认最终纳入结果。
- **系统会帮你做的事**：
  1) 从数十万级疾病记录中按规则快速召回；
  2) 对模糊召回候选做 AI 语义判断与标注；
  3) 生成管理员可复核执行的任务包（CSV + SQL + R）。
- **你将获得**：
  - 最终纳入疾病名称/ICD清单；
  - 全流程可追溯的分层和筛选依据；
  - 可提交给管理员的标准 ZIP 任务包。
        """
    )

st.header("1. 读取本地数据")
col1, col2 = st.columns(2)
with col1:
    disease_path = st.text_input("本地 disease_terms.csv 路径", value="data/disease_terms.csv")
with col2:
    icd_path = st.text_input("本地 icd_terms.csv 路径", value="data/icd_terms.csv")

@st.cache_data(show_spinner=False)
def _read_local(path_text: str) -> pd.DataFrame:
    path = Path(path_text).expanduser()
    if not path.exists() or not path.is_file():
        return pd.DataFrame()
    return safe_read_csv(path)

disease_df = _read_local(disease_path)
icd_df = _read_local(icd_path)
if disease_df.empty:
    st.warning(f"未读取到疾病名称清单：{disease_path}")
if icd_df.empty:
    st.warning(f"未读取到ICD清单：{icd_path}")

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
edited_map_df = st.data_editor(map_df, num_rows="dynamic", use_container_width=True, key="mapping_editor") if not map_df.empty else map_df
mapping = dict(zip(edited_map_df.get("diagnosis_type", []), edited_map_df.get("diagnosis_type_norm", []))) if not edited_map_df.empty else {}
st.download_button("导出 diagnosis_type_mapping.yaml", export_mapping_yaml(mapping), file_name="diagnosis_type_mapping.yaml")

disease_df = apply_diagnosis_type_mapping(disease_df, mapping) if not disease_df.empty else disease_df
icd_df = apply_diagnosis_type_mapping(icd_df, mapping) if not icd_df.empty else icd_df

st.header("3. 用户输入与口径")
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

filtered_disease, filtered_icd = disease_df.copy(), icd_df.copy()
if selected_sources:
    if "source_type" in filtered_disease.columns:
        filtered_disease = filtered_disease[filtered_disease["source_type"].isin(selected_sources)]
    if "source_type" in filtered_icd.columns:
        filtered_icd = filtered_icd[filtered_icd["source_type"].isin(selected_sources)]
if selected_diag:
    filtered_disease = filtered_disease[filtered_disease["diagnosis_type_norm"].isin(selected_diag)] if not filtered_disease.empty else filtered_disease
    filtered_icd = filtered_icd[filtered_icd["diagnosis_type_norm"].isin(selected_diag)] if not filtered_icd.empty else filtered_icd

st.header("4. AI词汇理解（精准词 / 模糊词）")
if st.button("生成/刷新疾病表达扩展", disabled=not target_disease):
    raw, ok, msg = call_expansion(target_disease, user_notes, all_source_types, raw_diag_values) if use_api else ("", False, "已选择不调用API。")
    expansion, warnings = parse_expansion_response(raw, target_disease, call_json_repair)
    st.session_state.expansion = expansion
    st.session_state.warnings.extend(warnings + ([msg] if msg else []))
    st.session_state.api_success = st.session_state.api_success or ok

expansion = st.session_state.expansion or {"target_disease": target_disease, "standard_name_guess": target_disease, "synonyms_cn": [], "abbreviations": [], "english_terms": [], "icd_keywords": [], "include_keywords": [target_disease] if target_disease else [], "possible_keywords": [], "related_keywords": [], "exclude_keywords": ["未见", "否认", "排除", "待排"], "negation_keywords": ["未见", "否认", "排除", "无"], "suspected_keywords": ["待排", "可能", "疑似", "？", "?"], "history_keywords": [], "source_priority_advice": [], "caution_notes": []}

st.subheader("4a. 精准词（规则强匹配）")
include_keywords_text = st.text_area("include_keywords", value="\n".join(expansion.get("include_keywords", [])), height=120)
expansion["include_keywords"] = [x.strip() for x in include_keywords_text.splitlines() if x.strip()]

st.subheader("4b. 模糊词（扩展召回 + AI复核）")
possible_keywords_text = st.text_area("possible_keywords", value="\n".join(expansion.get("possible_keywords", [])), height=100)
related_keywords_text = st.text_area("related_keywords", value="\n".join(expansion.get("related_keywords", [])), height=100)
expansion["possible_keywords"] = [x.strip() for x in possible_keywords_text.splitlines() if x.strip()]
expansion["related_keywords"] = [x.strip() for x in related_keywords_text.splitlines() if x.strip()]

other_fields = ["synonyms_cn", "abbreviations", "english_terms", "icd_keywords", "exclude_keywords", "negation_keywords", "suspected_keywords", "history_keywords", "caution_notes"]
for field in other_fields:
    text_value = st.text_area(field, value="\n".join(expansion.get(field, [])), height=90, key=f"exp_{field}")
    expansion[field] = [x.strip() for x in text_value.splitlines() if x.strip()]
st.session_state.expansion = expansion

st.header("5. 候选召回（精准优先 + 模糊补充）")
if st.button("执行候选召回", disabled=not target_disease):
    diag_priority = build_default_priority(selected_diag)
    st.session_state.disease_candidates, disease_trunc = recall_disease_terms(filtered_disease, expansion, diag_priority)
    st.session_state.icd_candidates, icd_trunc = recall_icd_terms(filtered_icd, expansion, diag_priority)
    st.session_state.truncation = {"disease": disease_trunc, "icd": icd_trunc}

st.dataframe(st.session_state.disease_candidates, use_container_width=True)
st.dataframe(st.session_state.icd_candidates, use_container_width=True)

st.header("6. AI分层与用户终审")
if st.button("执行模型分层/规则兜底", disabled=st.session_state.disease_candidates.empty and st.session_state.icd_candidates.empty):
    disease_classified, d_meta = classify_candidates(st.session_state.disease_candidates, "disease_name", target_disease, expansion, user_notes, use_api=use_api)
    icd_classified, i_meta = classify_candidates(st.session_state.icd_candidates, "icd_code", target_disease, expansion, user_notes, use_api=use_api)
    st.session_state.disease_classified, st.session_state.icd_classified = disease_classified, icd_classified
    st.session_state.warnings.extend(d_meta.get("warnings", []) + i_meta.get("warnings", []))

selection_mode = st.radio("筛选模式", ["严格模式", "宽松模式", "高召回模式", "自定义模式"], horizontal=True)
selected_disease_df = apply_user_mode_selection(st.session_state.disease_classified, selection_mode, False, True, False, False, []) if not st.session_state.disease_classified.empty else st.session_state.disease_classified
selected_icd_df = apply_user_mode_selection(st.session_state.icd_classified, selection_mode, False, True, False, False, []) if not st.session_state.icd_classified.empty else st.session_state.icd_classified
final_disease = selected_disease_df[selected_disease_df["final_include"]].copy() if not selected_disease_df.empty else pd.DataFrame()
final_icd = selected_icd_df[selected_icd_df["final_include"]].copy() if not selected_icd_df.empty else pd.DataFrame()
st.write(f"最终纳入疾病名称：{len(final_disease)} 条；最终纳入ICD编码：{len(final_icd)} 条")

st.header("7. 管理员任务包生成")
metadata = {"task_name": task_name, "target_disease": target_disease, "user_notes": user_notes, "created_at": timestamp_string(), "disease_filename": disease_path, "icd_filename": icd_path, "disease_total": len(disease_df), "icd_total": len(icd_df), "selection_mode": selection_mode, "selected_source_types": selected_sources, "selected_diagnosis_types": selected_diag, "disease_candidate_count": len(st.session_state.disease_candidates), "icd_candidate_count": len(st.session_state.icd_candidates), "final_disease_count": len(final_disease), "final_icd_count": len(final_icd), "warnings": st.session_state.warnings}
classification_json = {"disease_name": st.session_state.disease_classified.to_dict(orient="records") if not st.session_state.disease_classified.empty else [], "icd_code": st.session_state.icd_classified.to_dict(orient="records") if not st.session_state.icd_classified.empty else []}
zip_bytes = build_task_zip(metadata, expansion, selected_disease_df, selected_icd_df, final_disease, final_icd, mapping, classification_json, disease_df, icd_df)
st.download_button("下载管理员任务包 ZIP", data=zip_bytes, file_name=f"{task_name or 'whale_hdr_task'}_{timestamp_string()}.zip", mime="application/zip")
