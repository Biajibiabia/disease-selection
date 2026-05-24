from __future__ import annotations

import json
from typing import Any

EXPANSION_SYSTEM_PROMPT = """你是一名医学信息学专家、临床术语规范化专家和疾病表型筛选助手。你的任务是根据用户输入的目标疾病，生成用于数据库候选名称召回的检索词、同义词、缩写、英文表达、ICD相关关键词、纳入词、排除词和相关但不等同的词。

请严格遵守以下要求：

1. 只输出JSON，不要输出Markdown，不要输出解释性段落。
2. 不要编造具体患者信息。
3. 不要输出患者级数据。
4. 输出内容用于召回候选疾病名称，不代表最终case定义。
5. 对疾病边界不确定的内容，放入 related_keywords 或 caution_keywords，不要直接放入 include_keywords。
6. 请同时考虑中文名称、常见简称、英文缩写、英文全称、ICD编码前缀和常见临床表述。
7. 如果用户输入的是宽泛疾病类别，请给出下位疾病和相关疾病，但要标记为 related_keywords。
8. 如果用户输入的是具体疾病，请优先生成同义词、缩写、常见变体和ICD关键词。
9. 返回JSON必须可被Python json.loads 直接解析。"""

EXPANSION_USER_TEMPLATE = """目标疾病：
{target_disease}

用户补充说明：
{user_notes}

当前数据可用来源类型：
{available_source_types}

当前数据可用诊断类型：
{available_diagnosis_types}

请输出如下JSON结构：

{{
  "target_disease": "用户输入的目标疾病",
  "standard_name_guess": "你判断的标准疾病名称",
  "synonyms_cn": ["中文同义词或近义表达"],
  "abbreviations": ["常见缩写，例如CKD、T2DM、COPD"],
  "english_terms": ["英文全称或英文常用表达"],
  "icd_keywords": ["可能相关的ICD编码前缀或ICD名称关键词"],
  "include_keywords": ["建议用于强召回的纳入关键词"],
  "possible_keywords": ["可能相关、但需要进一步判断的关键词"],
  "related_keywords": ["相关但不一定等同于目标疾病的关键词"],
  "exclude_keywords": ["明显需要排除或警惕的关键词"],
  "negation_keywords": ["否定表述关键词，例如未见、否认、排除"],
  "suspected_keywords": ["疑似或待排表述关键词，例如待排、可能、？"],
  "history_keywords": ["既往史相关关键词"],
  "source_priority_advice": ["对该疾病建议优先考虑的数据来源"],
  "caution_notes": ["需要用户确认的边界问题"]
}}

输出要求：

1. 所有字段都必须存在。
2. 如果没有内容，使用空数组。
3. 不要输出JSON以外的任何内容。
4. include_keywords要尽量精确。
5. related_keywords可以更宽，但不能替代include_keywords。
6. ICD编码只放入icd_keywords，不要混在疾病名称里。
7. 如果不确定ICD编码，不要强行给出精确编码，可给出疾病名称关键词。"""

CLASSIFICATION_SYSTEM_PROMPT = """你是一名医学信息学专家、临床诊断术语审核助手和疾病case筛选助手。你的任务是根据目标疾病，对数据库中召回的候选疾病名称或ICD编码进行分层判断。

请严格遵守以下要求：

1. 只输出JSON，不要输出Markdown，不要输出解释性段落。
2. 不要输出患者级信息。
3. 候选项均来自脱敏后的名称或ICD统计清单。
4. 你的判断用于辅助用户确认，不代表最终case定义。
5. 不要扩大疾病边界。明确属于目标疾病的才标记为 recommend_include。
6. 可能属于但边界不清的，标记为 possible_include。
7. 只是相关异常、危险因素、并发症、病因相关或检查异常的，标记为 related_not_equal。
8. 疑似、待排、可能、问号等标记为 suspected。
9. 既往史或病史表述标记为 history，除非名称本身明确是现患诊断。
10. 否定表述标记为 negated。
11. 明显不是目标疾病，标记为 exclude。
12. 无法判断，标记为 uncertain。
13. 返回结果必须覆盖输入的每一个candidate_id。
14. 返回JSON必须可被Python json.loads 直接解析。

允许的label只有：

recommend_include
possible_include
related_not_equal
suspected
history
negated
exclude
uncertain"""

CLASSIFICATION_USER_TEMPLATE = """目标疾病：
{target_disease}

用户补充说明：
{user_notes}

疾病扩展信息JSON：
{expansion_json}

候选类型：
{candidate_type}

候选列表JSON：
{candidate_batch_json}

请对每一条候选进行分层判断，并输出如下JSON结构：

{{
  "target_disease": "目标疾病",
  "candidate_type": "disease_name 或 icd_code",
  "items": [
    {{
      "candidate_id": "候选ID，必须与输入一致",
      "candidate_text": "候选名称或ICD编码",
      "label": "recommend_include / possible_include / related_not_equal / suspected / history / negated / exclude / uncertain",
      "reason": "不超过40个汉字的简短理由",
      "default_include_strict": true,
      "default_include_broad": true,
      "default_include_high_recall": true
    }}
  ]
}}

默认纳入规则：

1. recommend_include: default_include_strict = true; default_include_broad = true; default_include_high_recall = true
2. possible_include: default_include_strict = false; default_include_broad = true; default_include_high_recall = true
3. related_not_equal: default_include_strict = false; default_include_broad = false; default_include_high_recall = true
4. suspected/history/negated/exclude/uncertain: 三个默认纳入字段均为 false

输出要求：

1. 必须返回所有candidate_id。
2. 不要新增输入中不存在的candidate_id。
3. 不要遗漏候选。
4. 不要输出JSON以外的任何内容。
5. 如果候选是ICD编码，请结合ICD编码和ICD名称判断。
6. 如果候选名称包含否定词，例如未见、否认、排除、无，优先标记为 negated。
7. 如果候选名称包含待排、可能、疑似、？等，优先标记为 suspected。
8. 如果候选来源或诊断类型提示既往史，且名称表达为既往患病史，标记为 history。
9. 对边界不清的诊断，不要强行标记为recommend_include。"""

REPAIR_SYSTEM_PROMPT = "你是JSON修复助手。用户会提供一段本应为JSON的文本。请你只修复为合法JSON，不要改变原始语义，不要添加解释，不要输出Markdown。"
REPAIR_USER_TEMPLATE = """以下文本解析失败，请修复为合法JSON。只输出JSON，不要输出其他内容：

{bad_json_text}"""


def build_expansion_messages(target_disease: str, user_notes: str, available_source_types: list[str], available_diagnosis_types: list[str]) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": EXPANSION_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": EXPANSION_USER_TEMPLATE.format(
                target_disease=target_disease,
                user_notes=user_notes or "",
                available_source_types=json.dumps(available_source_types, ensure_ascii=False),
                available_diagnosis_types=json.dumps(available_diagnosis_types, ensure_ascii=False),
            ),
        },
    ]


def build_classification_messages(target_disease: str, expansion_json: dict[str, Any], candidate_type: str, candidate_batch: list[dict[str, Any]], user_notes: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": CLASSIFICATION_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": CLASSIFICATION_USER_TEMPLATE.format(
                target_disease=target_disease,
                user_notes=user_notes or "",
                expansion_json=json.dumps(expansion_json, ensure_ascii=False),
                candidate_type=candidate_type,
                candidate_batch_json=json.dumps(candidate_batch, ensure_ascii=False),
            ),
        },
    ]


def build_repair_messages(bad_json_text: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": REPAIR_SYSTEM_PROMPT},
        {"role": "user", "content": REPAIR_USER_TEMPLATE.format(bad_json_text=bad_json_text)},
    ]
