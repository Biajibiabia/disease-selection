# WHALE/HDR 疾病 case 筛选任务生成工具 MVP

这是一个面向 WHALE/HDR 数据库用户的数据筛选辅助工具。用户输入目标疾病（如慢性肾脏病、糖尿病、脑梗死、冠心病），工具基于已经脱敏的疾病名称清单和 ICD 编码清单召回候选项，并可调用 DeepSeek API 进行医学语义扩展与候选分层。最终产物是提交给数据库管理员审核和执行的数据筛选任务包。

> 本工具不是最终病例判定工具，也不是全自动疾病表型判定系统。自动生成的 SQL/R 代码只供管理员审核，不应由普通用户直接在生产库执行。

## 安装依赖

```bash
pip install -r requirements.txt
```

## 设置 DeepSeek API Key

API Key 必须通过环境变量 `DEEPSEEK_API_KEY` 提供。不要把 Key 写入代码、日志、测试样例或导出的任务包。

```bash
export DEEPSEEK_API_KEY="你的DeepSeek API Key"
```

如果未设置环境变量，Streamlit 页面会提示；工具仍可使用规则兜底完成召回、分层和任务包生成。

## 输入 CSV 格式

### disease_terms.csv

建议字段：

| 字段 | 说明 |
| --- | --- |
| term_id | 疾病名称唯一 ID |
| disease_name | 脱敏后的疾病名称 |
| source_type | 来源类型，如体检结论、临床诊断、既往史、现病史 |
| source_table | 来源表名，可为空 |
| source_field | 来源字段名，可为空 |
| diagnosis_type | 原始诊断类型，可为空，不限定枚举 |
| diagnosis_type_norm | 归并诊断类型，可为空，系统可自动生成 |
| person_count | 人数 |
| visit_count | 诊次数，可为空 |

额外字段会被保留。没有 `diagnosis_type` 字段时仍可运行。

### icd_terms.csv

建议字段：

| 字段 | 说明 |
| --- | --- |
| icd_id | ICD 记录唯一 ID |
| icd_code | ICD 编码 |
| icd_name | ICD 名称 |
| source_type | 来源类型 |
| source_table | 来源表名，可为空 |
| source_field | 来源字段名，可为空 |
| diagnosis_type | 原始诊断类型，可为空 |
| diagnosis_type_norm | 归并诊断类型，可为空 |
| person_count | 人数 |
| visit_count | 诊次数，可为空 |

ICD 编码和疾病名称始终分开处理；ICD 召回支持编码前缀匹配与 ICD 名称关键词匹配。

## 运行 Streamlit

```bash
streamlit run app.py
```

## 工具流程

1. 上传 `disease_terms.csv` 和 `icd_terms.csv`。
2. 自动统计来源类型、原始诊断类型、归并诊断类型。
3. 配置或上传 `diagnosis_type_mapping.yaml`。
4. 输入目标疾病、任务名称和补充说明。
5. 调用 DeepSeek 扩展疾病表达，或在无 API 时使用规则兜底。
6. 用户可手工增删扩展词。
7. 分别召回疾病名称候选和 ICD 候选。
8. 调用 DeepSeek 对候选分层，或使用规则兜底分层。
9. 用户选择严格、宽松、高召回或自定义模式，分别确认疾病名称和 ICD 纳入清单。
10. 生成管理员任务包 ZIP。

## 诊断类型自动归并和人工配置

系统保留原始 `diagnosis_type`，并生成 `diagnosis_type_norm`。如果上传了 `diagnosis_type_mapping.yaml`，配置文件优先生效；否则使用自动关键词规则：

- 包含“出院” → 出院诊断
- 包含“入院” → 入院诊断
- 包含“门诊”或“门急诊” → 门急诊诊断
- 包含“急诊” → 急诊诊断
- 包含“修正” → 修正诊断
- 包含“主要” → 主要诊断
- 包含“次要” → 次要诊断
- 包含“病理” → 病理诊断
- 包含“既往” → 既往史
- 包含“现病” → 现病史
- 包含“体检”或“阳性结论” → 体检结论
- 无法识别 → 未归类诊断

页面中的配置表允许管理员修改映射，并导出 YAML 文件复用。

## DeepSeek API 调用说明

工具通过 OpenAI Python SDK 兼容方式调用 DeepSeek：

- API Key 仅从环境变量 `DEEPSEEK_API_KEY` 读取。
- base_url 为 `https://api.deepseek.com`。
- 模型默认为 `deepseek-v4-pro`。
- 只读取 `response.choices[0].message.content`。
- 不保存、不展示模型推理过程。
- 只向 API 发送脱敏后的疾病名称、ICD 编码、来源类型、诊断类型和人数统计，不发送患者 ID、姓名、身份证、visitid 或病历原文。

## JSON 解析和失败兜底逻辑

- 自动剥离 ```json 代码块。
- 使用 `json.loads` 解析模型输出。
- 缺失字段会自动补齐。
- 解析失败时会调用 JSON 修复 prompt 尝试修复一次。
- 修复仍失败时，扩展阶段回退到目标疾病本身作为纳入关键词；分层阶段用规则判断否定、疑似、纳入、可能、相关或无法判断。
- 解析和 API 警告会写入 `task_summary.md`。

## 管理员任务包

点击“下载管理员任务包 ZIP”后，任务包包含：

- `task_summary.md`：任务摘要和管理员注意事项
- `deepseek_expansion.json`：扩展结果
- `model_classification.json`：模型/规则分层结果
- `disease_name_candidates.csv`：疾病名称候选
- `icd_candidates.csv`：ICD 候选
- `final_included_disease_names.csv`：最终纳入疾病名称
- `final_included_icd_codes.csv`：最终纳入 ICD 编码
- `extract_hdr.sql`：HDR SQL 示例代码
- `extract_local.R`：本地 data.table 提取示例代码
- `diagnosis_type_mapping.yaml`：诊断类型映射
- `disease_terms.csv`、`icd_terms.csv`：本次上传的脱敏输入清单副本，便于复核

CSV 均使用 UTF-8-SIG 导出，便于 Excel 打开。

## SQL/R 代码查看

管理员应重点检查：

1. SQL 中的默认表名和字段名是否匹配真实环境。
2. 疾病名称和 ICD 编码是否符合最终筛选口径。
3. 是否需要加入额外来源类型、诊断类型或日期范围条件。
4. R 代码中的输入文件路径和字段名是否与本地数据一致。

默认 SQL 占位表：

- `hive.hdr.whale_disease_term_inventory`
- `hive.hdr.whale_icd_inventory`

默认字段：`archive_corrected`、`visitid`、`disease_name`、`icd_code`、`source_type`、`diagnosis_type`、`diagnosis_type_norm`。

## 安全注意事项

- 不要上传患者级敏感信息。
- 不要上传姓名、身份证、visitid、完整病历原文。
- 不要在代码中写死 API Key。
- 不要把 API Key 放入任务包。
- DeepSeek API 输入仅应包含脱敏统计清单层面的信息。
- 生成的 SQL/R 代码必须由管理员审核后执行。
