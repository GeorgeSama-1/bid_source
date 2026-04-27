# 标书历史信息入库前解析与召回验证系统 MVP

## 项目目标

当前项目不是最终知识库，也不是完整后端服务，而是“入库前解析与召回验证层”。

第一版聚焦 7 件事：

1. PDF 解析是否准确。
2. 表格是否能抽取。
3. 目录/章节是否能重建。
4. Excel 章节规则是否能和 PDF 真实章节匹配。
5. 可复用候选信息是否能被正确抽取。
6. 候选信息是否能被检索召回。
7. 所有流程是否可配置、可审查、可迭代。

## 为什么第一版不建数据库

这一版的关键问题是“解析与召回链路是否可靠”，不是“如何持久化到正式库”。

如果在 PDF 解析、章节重建、规则匹配、候选抽取、召回验证都还不稳定时就先建库，很容易把错误的数据结构和错误的业务判断固化下来。因此当前阶段全部中间结果都先输出为 JSON / JSONL / CSV，方便人工核查、回放、比对和迭代。

当解析、候选抽取、召回验证稳定后，再将这些中间结果映射到数据库。

## 整体流程

```text
Excel 规则表
  -> section_rules.json
  -> processing_plan.json
  -> PDF 解析 / 表格抽取 / 按需 OCR
  -> text_blocks / tables / ocr_results / merged_blocks
  -> reconstructed_sections.json
  -> section_match_results.json
  -> reusable_candidates.json
  -> chunks.jsonl
  -> retrieval_eval_report.json
```

## 安装方式

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 目录结构

```text
bid_knowledge/
  cli.py
  config/
  parsing/
  matching/
  extraction/
  retrieval/
  schemas/
  utils/

configs/
  manual_config.example.json

data/
  test_queries.json

outputs/

tests/
```

## 输入文件说明

本仓库当前已包含：

- `价格文件-商务文件-技术文件章节分析.xlsx`
- `2、商务文件.pdf`

你也可以替换成其他价格文件 / 商务文件 / 技术文件输入，只要通过 CLI 传入对应路径即可。

## manual_config 如何控制流程

`configs/manual_config.example.json` 用于显式控制：

- 哪些页允许 OCR。
- 哪些章节允许 OCR。
- 哪些章节重点做表格抽取。
- 哪些章节跳过。
- 某章节的 `content_type`、`reuse_method`、`enter_long_term_library`、`review_required`。

设计原则：

- Excel 规则只提供默认策略。
- `manual_config` 的 `section_overrides` 优先级最高。
- 程序只执行规则，不替代人工做最终复用判断。
- 所有候选项默认 `review_status = pending`。

## CLI 命令

### 1. 读取规则表

```bash
python -m bid_knowledge.cli load-rules \
  --rules-xlsx "价格文件-商务文件-技术文件章节分析.xlsx" \
  --out outputs/rules/section_rules.json \
  --report outputs/rules/rule_load_report.json
```

### 2. 生成 processing plan

```bash
python -m bid_knowledge.cli build-plan \
  --rules outputs/rules/section_rules.json \
  --manual-config configs/manual_config.example.json \
  --out outputs/plan/processing_plan.json
```

### 3. 解析 PDF

```bash
python -m bid_knowledge.cli parse-pdf \
  --pdf "2、商务文件.pdf" \
  --plan outputs/plan/processing_plan.json \
  --out-dir outputs/parsed
```

### 4. 抽取表格

```bash
python -m bid_knowledge.cli extract-tables \
  --pdf "2、商务文件.pdf" \
  --plan outputs/plan/processing_plan.json \
  --out outputs/parsed/tables.json
```

### 5. 执行 OCR

```bash
python -m bid_knowledge.cli run-ocr \
  --pdf "2、商务文件.pdf" \
  --plan outputs/plan/processing_plan.json \
  --parsed-dir outputs/parsed \
  --ocr-endpoint http://127.0.0.1:8000/v1/chat/completions \
  --ocr-model paddle-ocr \
  --out outputs/parsed/ocr_results.json
```

说明：

- 只对 `processing_plan` 中明确开启的页执行 OCR。
- 不做全量 OCR。
- OCR 失败会记录到 `ocr_results.json`，不会让整条链路直接崩溃。

### 6. 合并 OCR

```bash
python -m bid_knowledge.cli merge-ocr \
  --blocks outputs/parsed/text_blocks.json \
  --ocr outputs/parsed/ocr_results.json \
  --out outputs/parsed/text_blocks_merged.json
```

### 7. 重建章节

```bash
python -m bid_knowledge.cli build-sections \
  --blocks outputs/parsed/text_blocks_merged.json \
  --toc outputs/parsed/toc.json \
  --rules outputs/rules/section_rules.json \
  --out outputs/structure/reconstructed_sections.json
```

### 8. 匹配章节

```bash
python -m bid_knowledge.cli match-sections \
  --rules outputs/rules/section_rules.json \
  --sections outputs/structure/reconstructed_sections.json \
  --plan outputs/plan/processing_plan.json \
  --out outputs/structure/section_match_results.json
```

### 9. 抽取候选信息

```bash
python -m bid_knowledge.cli extract-candidates \
  --plan outputs/plan/processing_plan.json \
  --matches outputs/structure/section_match_results.json \
  --blocks outputs/parsed/text_blocks_merged.json \
  --tables outputs/parsed/tables.json \
  --out-json outputs/candidates/reusable_candidates.json \
  --out-csv outputs/candidates/candidate_report.csv
```

### 10. 构建检索 chunks

```bash
python -m bid_knowledge.cli build-chunks \
  --candidates outputs/candidates/reusable_candidates.json \
  --out outputs/retrieval/chunks.jsonl
```

### 11. 检索测试

```bash
python -m bid_knowledge.cli search \
  --chunks outputs/retrieval/chunks.jsonl \
  --query "投标人基本情况表 公司基础信息" \
  --top-k 5 \
  --method bm25
```

### 12. 批量召回评估

```bash
python -m bid_knowledge.cli eval-retrieval \
  --chunks outputs/retrieval/chunks.jsonl \
  --queries data/test_queries.json \
  --out outputs/retrieval/retrieval_eval_report.json
```

### 13. 一键流水线

```bash
python -m bid_knowledge.cli pipeline \
  --rules-xlsx "价格文件-商务文件-技术文件章节分析.xlsx" \
  --pdf "2、商务文件.pdf" \
  --manual-config configs/manual_config.example.json \
  --out-dir outputs/demo_run \
  --enable-ocr false
```

如果需要按计划执行 OCR：

```bash
python -m bid_knowledge.cli pipeline \
  --rules-xlsx "价格文件-商务文件-技术文件章节分析.xlsx" \
  --pdf "2、商务文件.pdf" \
  --manual-config configs/manual_config.example.json \
  --out-dir outputs/demo_run \
  --enable-ocr true \
  --ocr-endpoint http://127.0.0.1:8000/v1/chat/completions \
  --ocr-model paddle-ocr
```

## 输出文件说明

标准输出结构如下：

```text
outputs/demo_run/
  rules/
    section_rules.json
    rule_load_report.json
  plan/
    processing_plan.json
  parsed/
    document_meta.json
    toc.json
    text_blocks.json
    text_blocks_merged.json
    tables.json
    images.json
    ocr_results.json
    page_images/
  structure/
    reconstructed_sections.json
    section_match_results.json
  candidates/
    reusable_candidates.json
    candidate_report.csv
  retrieval/
    chunks.jsonl
    retrieval_eval_report.json
```

## OCR 接口配置

支持 CLI 参数和环境变量：

- `OCR_ENDPOINT`
- `OCR_MODEL`
- `OCR_API_KEY`

例如：

```bash
export OCR_ENDPOINT=http://127.0.0.1:8000/v1/chat/completions
export OCR_MODEL=paddle-ocr
export OCR_API_KEY=your_key
```

## 如何做召回测试

1. 先构建 `chunks.jsonl`。
2. 用 `search` 命令做单条查询验证。
3. 用 `eval-retrieval` 对 `data/test_queries.json` 做批量评估。
4. 打开 `retrieval_eval_report.json` 看命中率、命中位置和 top_k 结果。

## 当前 MVP 限制

- 章节重建仍然是“TOC 优先 + 简单标题规则”的初版实现，不保证完美。
- 表格结构还原目前以二维行列为主，没有做复杂跨行跨列恢复。
- OCR 接口假定兼容类 OpenAI Chat Completions 风格返回，复杂自定义协议还需要适配。
- 向量召回是 optional，缺依赖时不会阻断主流程。
- 这一版没有数据库、没有审核 UI、没有对象存储。

## 后续迭代方向

- 数据库入库映射。
- Web 审核界面。
- PostgreSQL + pgvector。
- MinIO 文件存储。
- 更强 OCR 和版面分析。
- 更强表格结构还原。
- 大模型字段抽取与复用建议。
- 人工审核后正式入库。
- AI 写标书时的章节级检索调用。

## 扩展原则

- 不强绑定数据库。
- 不强绑定某一个 OCR 服务。
- 不强绑定某一种 Excel 列名。
- 不强绑定商务文件。
- 不强绑定某一种候选类型。

当前这套系统的职责，是把历史标书从“原始文件”推进到“可审查、可召回、可评估”的状态。
