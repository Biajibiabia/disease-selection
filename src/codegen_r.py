from __future__ import annotations


def generate_r_code() -> str:
    return r'''# WHALE/HDR 疾病case本地提取示例（管理员/数据工程人员审核后使用）
library(data.table)

disease_terms <- fread("disease_terms.csv", encoding = "UTF-8")
icd_terms <- fread("icd_terms.csv", encoding = "UTF-8")
included_disease_names <- fread("final_included_disease_names.csv", encoding = "UTF-8")
included_icd_codes <- fread("final_included_icd_codes.csv", encoding = "UTF-8")

if (!"archive_corrected" %in% names(disease_terms)) disease_terms[, archive_corrected := NA_character_]
if (!"visitid" %in% names(disease_terms)) disease_terms[, visitid := NA_character_]
if (!"archive_corrected" %in% names(icd_terms)) icd_terms[, archive_corrected := NA_character_]
if (!"visitid" %in% names(icd_terms)) icd_terms[, visitid := NA_character_]

if (nrow(included_disease_names) > 0 && "disease_name" %in% names(included_disease_names)) {
  disease_match <- disease_terms[disease_name %in% included_disease_names$disease_name]
  disease_match[, match_type := "disease_name"]
  disease_match[, matched_value := disease_name]
} else {
  disease_match <- disease_terms[0]
  disease_match[, `:=`(match_type = character(), matched_value = character())]
}

if (nrow(included_icd_codes) > 0 && "icd_code" %in% names(included_icd_codes)) {
  icd_match <- icd_terms[icd_code %in% included_icd_codes$icd_code]
  icd_match[, match_type := "icd_code"]
  icd_match[, matched_value := icd_code]
} else {
  icd_match <- icd_terms[0]
  icd_match[, `:=`(match_type = character(), matched_value = character())]
}

common_cols <- union(names(disease_match), names(icd_match))
case_visit <- unique(rbindlist(list(disease_match, icd_match), use.names = TRUE, fill = TRUE))
case_person <- unique(case_visit[, .(archive_corrected)])

fwrite(case_visit, "case_visit.csv", bom = TRUE)
fwrite(case_person, "case_person.csv", bom = TRUE)
'''
