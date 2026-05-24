# WHALE/HDR 疾病 case 筛选任务生成工具 MVP

本工具用于**目标疾病筛选任务**的半自动构建：用户给出目标疾病后，系统先做“精准词+模糊词”两段式召回，再由 AI 与用户共同完成终审，最终输出管理员可执行前复核的任务包。

## 一、使用说明（给业务用户）

### 你要做什么
1. 准备并放置本地脱敏清单（无需上传）：
   - `disease_terms.csv`
   - `icd_terms.csv`
2. 在页面输入目标疾病与补充口径。
3. 审核 AI 生成的词汇：
   - 精准词（强匹配）
   - 模糊词（扩展召回）
4. 查看 AI 分层结果，做最终纳入确认。
5. 下载管理员任务包 ZIP。

### 你会得到什么
- 最终纳入疾病名称清单与 ICD 清单。
- AI 分层标签与理由（可追溯）。
- SQL/R 示例与完整任务说明文档。

---

## 二、为什么取消“数据上传区”

本版改为**直接读取本地文件路径**，避免反复上传、降低误传风险，并便于在内网批量处理。

页面中填写：
- `本地 disease_terms.csv 路径`（默认 `data/disease_terms.csv`）
- `本地 icd_terms.csv 路径`（默认 `data/icd_terms.csv`）

---

## 三、核心筛选流程（对应产品逻辑）

1. **目标疾病理解（AI）**
   - 基于用户输入疾病，生成精准词与模糊词。
2. **规则召回**
   - 精准词：直接强匹配进入候选池。
   - 模糊词：召回相关疾病（并去重，避免重复纳入）。
3. **AI 二次判断**
   - 对模糊召回项进行标签判断与理由标注。
4. **用户终审**
   - 用户决定是否纳入最终疾病池。

> 示例：目标“慢性肾脏病”
> - 精准词：CKD、慢性肾病、慢性肾脏病
> - 模糊词：肾病、肾、肾功能异常

---

## 四、安装与运行

```bash
pip install -r requirements.txt
streamlit run app.py
```

可选：配置 DeepSeek API（未配置也可走规则兜底）

```bash
export DEEPSEEK_API_KEY="你的DeepSeek API Key"
```

---

## 五、本地 CSV 字段建议

### disease_terms.csv
关键字段：`term_id`, `disease_name`, `source_type`, `diagnosis_type`, `person_count`。

### icd_terms.csv
关键字段：`icd_id`, `icd_code`, `icd_name`, `source_type`, `diagnosis_type`, `person_count`。

其余字段可保留，系统会尽量透传到候选结果。

---

## 六、AI Prompt 设计要点（已在代码中实现）

- 扩展阶段强制输出结构化 JSON。
- 明确区分：
  - `include_keywords` = 精准词（强匹配）
  - `possible_keywords`/`related_keywords` = 模糊词（需复核）
- 分层阶段只允许固定标签，避免“自由发挥”。
- 解析失败时自动 JSON 修复；仍失败则规则兜底。

---

## 七、管理员任务包内容

下载 ZIP 后包含：
- `task_summary.md`
- `deepseek_expansion.json`
- `model_classification.json`
- `disease_name_candidates.csv`
- `icd_candidates.csv`
- `final_included_disease_names.csv`
- `final_included_icd_codes.csv`
- `extract_hdr.sql`
- `extract_local.R`
- `diagnosis_type_mapping.yaml`
- 本次读取的 `disease_terms.csv`、`icd_terms.csv` 副本

---

## 八、安全说明

- 仅处理脱敏统计级数据。
- 不应包含患者ID、姓名、身份证、visitid、病历原文。
- API Key 仅从环境变量读取，不写入代码与任务包。
- SQL/R 示例必须由管理员审核后执行。
