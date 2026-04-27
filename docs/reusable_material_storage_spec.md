# 可复用材料存储规范

> 补充说明：
> 虽然本文重点讨论表格类材料，但“独立命名 + 按组成模块归档”的规则，不只适用于表格，也适用于图片、附件、正文片段、混合型可复用材料。

## 1. 目标

本文档定义“标书历史信息入库前解析与召回验证系统”中，表格类可复用材料的保存方式。

当前阶段目标不是建数据库，而是先把以下事情做清楚：

- 表格能不能稳定抽出来。
- 抽出来后应该保存成什么结构。
- 哪些表适合结构化复用，哪些表只适合保留原表。
- 每张表如何追溯到原 PDF、页码、章节、bbox、候选项。

当前阶段统一先保存到 `JSON / JSONL / CSV`，不直接入库。

## 2. 基本原则

- 不丢原始表格：先保留抽取后的二维表数据。
- 不强行结构化：只有明显适合 key-value 抽取的表，才进入 `fields`。
- 不替代人工判断：所有候选默认 `review_status = pending`。
- 必须可追溯：每条表格候选都要能追溯到来源文件、页码、章节、block、table。
- 区分载体：表格、图片、文本混合出现时，不能把整章误当成纯表格。
- 统一命名规则：表格、图片、附件、正文片段，都应该优先按“最近标题”命名。
- 统一归档规则：表格、图片、附件、正文片段，都应该先归入所属“组成模块”目录。

## 2.1 规则适用范围

本文中的以下规则，不只适用于表格，也适用于其他可复用材料：

- 独立命名
- 模块化归档
- 上下文追溯
- 单项 JSON 文件
- 全局索引 + 单项文件并存

适用对象包括：

- 表格
- 图片
- 扫描件附件
- 正文模板片段
- 结构化字段块
- 混合型材料

## 3. 表格命名规则

### 3.1 为什么每张表都要有独立名字

如果表格要进入“可复用候选池”，那么每张表都不应该只靠 `table_id` 标识，而应该有一个人可理解的独立名字。

原因：

- 方便人工审核和分管。
- 方便后续检索和复用。
- 同一章节下可能存在多张表，不命名会混淆。
- 后续拆成单表 JSON 文件时，文件名必须可读。

### 3.2 表名最佳实践

每张表的独立名字，优先使用“离这张表最近的上方标题”。

推荐优先级：

1. 同页中，表格上方最近的标题行
2. 若没有，则取包含它的最近小节标题
3. 若没有，则取所属容器大章标题
4. 最后才回退到 Excel 规则名

这条规则的核心是：

- 表名优先反映 PDF 里的真实上下文
- 不是优先套 Excel 规则名

例如：

- 容器大章：`3.8、招标文件第三章评标办法前附表之三“商务评分标准”涉及的支撑材料`
- 小节：`3.8.1、经营状况`
- 表格上方最近标题：`（1）、绩效评价结果查询`

则推荐表名为：

- `绩效评价结果查询`

同时保留：

- `parent_section_title = 3.8.1、经营状况`
- `container_title = 3.8、招标文件第三章评标办法前附表之三“商务评分标准”涉及的支撑材料`

### 3.3 同样的命名规则也适用于图片和其他材料

这条“最近标题优先”的规则，不应只用于表格。

对于其他可复用材料，也建议使用同样的命名优先级：

1. 同页中，材料上方最近的标题行
2. 若没有，则取包含它的最近小节标题
3. 若没有，则取所属容器大章标题
4. 最后才回退到 Excel 规则名

例如：

- 图片扫描件上方标题：`附：法定代表人（单位负责人）身份证（扫描件）`
- 则图片独立名应优先取：
  - `法定代表人（单位负责人）身份证（扫描件）`

再例如：

- 某一页正文片段上方最近标题：`（1）、绩效评价结果查询`
- 则该正文片段或其关联图片，也应优先挂靠：
  - `绩效评价结果查询`

也就是说：

- 表格取 `table_title`
- 图片取 `image_title`
- 正文片段取 `text_item_title`
- 附件取 `asset_title`

但这些标题的确定原则应尽量统一。

### 3.4 推荐新增字段

每张表建议至少保留：

- `table_id`
- `table_title`
- `table_title_normalized`
- `table_title_source`
- `parent_section_title`
- `container_title`
- `table_index_in_section`
- `table_path`

说明：

- `table_title_source` 可取：
  - `nearest_heading`
  - `section_title`
  - `container_title`
  - `rule_fallback`
- `table_path` 表示表级路径，便于后续独立管理

示例：

```json
{
  "table_id": "table_xxx",
  "table_title": "绩效评价结果查询",
  "table_title_normalized": "绩效评价结果查询",
  "table_title_source": "nearest_heading",
  "parent_section_title": "3.8.1、经营状况",
  "container_title": "3.8、招标文件第三章评标办法前附表之三“商务评分标准”涉及的支撑材料",
  "table_index_in_section": 1,
  "table_path": "商务文件 / 商务评分标准涉及的支撑材料 / 经营状况 / 绩效评价结果查询"
}
```

## 4. 模块化归档规则

### 4.1 为什么要按组成模块包裹

每个 PDF 的解析产物，不建议平铺散落在一个目录下，而建议先按“组成模块”归档。

原因：

- 更符合业务理解方式
- 更方便多人分管
- 更方便按模块局部重跑和修订
- 更方便后续扩展到技术文件、价格文件

### 4.2 一级归档单位

推荐把“组成模块”作为一级归档单位。

例如：

- `补充文件`
- `投标人基本情况表`
- `法定代表人授权委托书`
- `“商务评分标准”涉及的支撑材料`

### 4.3 推荐目录结构

```text
outputs/<run_id>/
  document/
    source.pdf
    document_meta.json
    toc.json

  modules/
    商务评分标准涉及的支撑材料/
      module_meta.json
      sections.json
      text_blocks.json
      tables.json
      table_items/
        table_001_绩效评价结果查询.json
        table_002_履约优秀证明清单.json
      images.json
      image_items/
      candidates.json

    法定代表人授权委托书/
      module_meta.json
      sections.json
      text_blocks.json
      tables.json
      table_items/
      images.json
      image_items/
      candidates.json

  global/
    reconstructed_sections.json
    section_match_results.json
    reusable_candidates.json
    candidate_report.csv
```

### 4.4 模块内保存原则

模块目录下建议同时保留：

- 原始文本块
- 原始表格索引
- 单表 JSON 文件
- 原始图片索引
- 单图片 JSON / 图片文件
- 模块级候选清单
- 其他附件索引
- 单附件 JSON / 原始附件文件

全局目录只保留：

- 汇总索引
- 章节重建结果
- 规则匹配结果
- 全量候选汇总

### 4.5 该归档规则同样适用于图片和其他格式

“按组成模块包裹”的归档规则，不应只用于表格。

图片、扫描件、正文片段、附件，也建议放在相同模块目录下管理。

例如：

```text
modules/
  商务评分标准涉及的支撑材料/
    table_items/
      table_001_绩效评价结果查询.json
    image_items/
      image_001_2025年国网山东省电力公司物资公司1000kV昌乐站（评价优秀）.json
      image_001_2025年国网山东省电力公司物资公司1000kV昌乐站（评价优秀）.jpeg
    text_items/
      text_001_企业名称变更原因说明.json
    asset_items/
      asset_001_法定代表人（单位负责人）身份证（扫描件）.json
      asset_001_法定代表人（单位负责人）身份证（扫描件）.jpeg
```

这样做的好处是：

- 一个模块下的所有复用材料都集中
- 表、图、文、附件不会分散
- 后续人工审核和模块分管更清晰

## 5. 当前推荐保存层次

### 5.1 原始表格层

文件：

- `outputs/.../parsed/tables.json`

用途：

- 保留 PDF 表格抽取结果原貌。
- 用于人工核对“表格有没有抽歪”。
- 用于后续重新做结构化抽取。

单表最少保留字段：

- `table_id`
- `page_no`
- `rows`
- `bbox`
- `source_type`

示例：

```json
{
  "table_id": "table_xxx",
  "page_no": 574,
  "rows": [
    ["项目名称", "评价开始日期", "评价截止日期"],
    ["01-2025年...", "2022-07-01", "2025-06-30"]
  ],
  "bbox": null,
  "source_type": "pdf_table"
}
```

### 5.2 候选复用层

文件：

- `outputs/.../candidates/reusable_candidates.json`

用途：

- 给后续人工审核和 AI 检索使用。
- 将“原始表格”转换成“待审核可复用候选”。

表格类候选建议保留字段：

- `candidate_id`
- `rule_id`
- `section_path`
- `title`
- `candidate_type`
- `material_types`
- `dominant_material_type`
- `material_evidence`
- `content`
- `fields`
- `source_file`
- `source_page`
- `source_page_end`
- `source_container_title`
- `source_bbox`
- `source_block_ids`
- `review_status`
- `valid_status`

说明：

- `content`：用于保存人可读版本，适合预览、检索、审核。
- `fields`：仅在明确能稳定抽成字段时使用。
- `material_types`：例如 `["table"]`、`["text","table"]`、`["text","table","image"]`
- `dominant_material_type`：例如 `table` 或 `mixed`

### 5.3 审核报表层

文件：

- `outputs/.../candidates/candidate_report.csv`

用途：

- 给人工快速筛选表格类候选。
- 快速查看哪些候选是 `table`，哪些是 `mixed`。

## 6. 表格类材料的分类建议

### 6.1 结构化字段表

典型例子：

- 投标人基本情况表
- 股权信息表
- 人员信息表
- 财务信息表

建议保存方式：

- 原始表保留到 `tables.json`
- 候选里同时保留：
  - `rows` 对应的可读内容到 `content`
  - 可稳定抽取的 key-value 到 `fields`

适用原因：

- 后续适合做字段填充。
- 同类表往往字段较稳定。

### 6.2 证明型汇总表

典型例子：

- 商务评分标准支撑材料中的业绩汇总表
- 履约证明清单表
- 评分支撑材料统计表

建议保存方式：

- 必保留原始 `rows`
- `content` 保存表格的文本化结果
- `fields` 可以为空，或只抽取少量高确定性字段

适用原因：

- 这类表经常列很多行，结构比较长。
- 强行抽字段容易损失信息。

### 6.3 混合型章节里的表格

典型例子：

- 同一章节下既有评分表，又有扫描件证明材料
- 同一章节既有汇总表，又有履约证明图片

建议保存方式：

- 候选标记：
  - `material_types` 包含 `table`
  - `dominant_material_type = mixed`
- 不要把整章误判成纯结构化表
- 必要时后续再拆成“表格子候选”和“图片子候选”

## 7. 当前字段使用建议

### 7.1 `content`

推荐用途：

- 存表格的人类可读文本。
- 用于检索、审核、预览。

不建议：

- 用 `content` 替代原始表格。

### 7.2 `fields`

推荐用途：

- 仅保存高确定性的结构化字段。

适合进入 `fields` 的情况：

- 表头稳定。
- 行列关系清楚。
- 字段意义明确。
- 后续明显要用于模板填充。

不适合进入 `fields` 的情况：

- 表格太长，且是明细清单。
- 表头复杂、跨行跨列严重。
- 本质是证明材料，不是字段卡片。

### 7.3 `material_types` 和 `dominant_material_type`

推荐规则：

- 只有表格：`material_types=["table"]`，`dominant_material_type="table"`
- 表格 + 正文：`material_types=["text","table"]`，`dominant_material_type="mixed"`
- 表格 + 图片：`material_types=["table","image"]`，`dominant_material_type="mixed"`
- 表格 + 正文 + 图片：`material_types=["text","table","image"]`，`dominant_material_type="mixed"`

## 8. 追溯要求

每个表格类候选至少应能追溯到：

- 来源 PDF 文件
- 所属组成模块
- 起止页码
- 所属大章标题
- 所属小节标题
- 表格独立标题
- 发现实例标题
- 表格 `table_id`
- 相关文本块 `block_id`
- 页级 bbox

如果当前某个字段抽不到，不要伪造，允许为空，但要保留结构位置。

对于图片、附件、正文片段，也应遵循同样的追溯原则：

- 来源 PDF 文件
- 所属组成模块
- 所属大章标题
- 所属小节标题
- 独立材料标题
- 页码
- bbox
- 关联 block_id / image_id / asset_id

## 9. 当前实现建议

当前 MVP 推荐做法：

1. 先按组成模块建目录
2. 每个模块下保留：
   - `tables.json`
   - `table_items/*.json`
3. 每张表优先按“最近标题”命名
4. 候选层判断该表属于：
   - `structured_field`
   - `template_text`
   - `reusable_text`
   - `mixed`
5. 若明显适合字段化，再写入 `fields`
6. 若只是证明性表格，则保留：
   - 原始 `rows`
   - 文本化 `content`
   - 追溯信息

同一套思路也适用于图片和其他材料：

- 图片先保留原始图片及索引
- 正文片段先保留原始文本块及索引
- 附件先保留原始文件及元数据
- 后续再生成候选层 JSON

## 10. 单表 JSON 推荐结构

每张表建议拆成独立 JSON 文件，文件名使用：

- `table_<顺序号>_<表名>.json`

示例：

```text
table_001_绩效评价结果查询.json
table_002_投标保证金明细表.json
```

示例内容：

```json
{
  "table_id": "table_xxx",
  "table_title": "绩效评价结果查询",
  "table_title_source": "nearest_heading",
  "module_name": "商务评分标准涉及的支撑材料",
  "parent_section_title": "3.8.1、经营状况",
  "container_title": "3.8、招标文件第三章评标办法前附表之三“商务评分标准”涉及的支撑材料",
  "table_path": "商务文件 / 商务评分标准涉及的支撑材料 / 经营状况 / 绩效评价结果查询",
  "page_no": 574,
  "bbox": null,
  "rows": [
    ["项目名称", "评价开始日期", "评价截止日期"]
  ],
  "review_status": "pending",
  "source_file": "商务文件.pdf"
}
```

## 10.1 单图片 / 单附件 / 单文本片段 JSON 也建议独立保存

推荐保持一致的设计风格：

- 单表：一个 JSON
- 单图片：一个 JSON
- 单正文片段：一个 JSON
- 单附件：一个 JSON

例如：

```json
{
  "image_id": "image_xxx",
  "image_title": "法定代表人（单位负责人）身份证（扫描件）",
  "module_name": "法定代表人授权委托书",
  "parent_section_title": "4、法定代表人授权委托书",
  "container_title": "附：法定代表人（单位负责人）身份证（扫描件）",
  "page_no": 834,
  "bbox": [72.0, 476.0, 296.25, 615.5],
  "source_file": "商务文件.pdf",
  "review_status": "pending"
}
```

## 11. 一个实际例子

以商务文件中的：

- Excel 规则：`“商务评分标准”涉及的支撑材料 / 一、履约能力评价 / 经营状况`
- PDF 大章：`3.8、招标文件第三章评标办法前附表之三“商务评分标准”涉及的支撑材料`

该章节下可能同时出现：

- 评分汇总表
- 履约证明表
- 业主出具证明图片

此时建议：

- 不把它保存成单一 `table`
- 先放到模块目录：
  - `modules/商务评分标准涉及的支撑材料/`
- 候选标记为：
  - `material_types=["text","table","image"]`
  - `dominant_material_type="mixed"`
- 若表格上方最近标题是 `绩效评价结果查询`，则单表文件命名为：
  - `table_001_绩效评价结果查询.json`
- 后续如有需要，再拆分成：
  - 表格子候选
  - 图片子候选

## 11.1 商务评审索引表的使用边界

商务文件中的 `商务评审索引表` 只用于增强定位：

- `补充文件 / “商务评分标准”涉及的支撑材料`

该索引表中的“评审要素、评审细则、页码、标题”可以作为这一分支的优先定位依据。比如：

- `一、履约能力评价 / 经营状况`
- `一、履约能力评价 / 售后服务`
- `二、高质量发展评价 / 研发团队规模`

这些评审要素下面如果出现 `3.8.1.1`、`3.8.2.1`、`3.8.10.2` 这类索引标题，应在对应评审要素目录下继续建立细项目录。细项目录内的表格、图片、正文片段，仍然按照 PDF 中“最近上方有效标题”命名。

该索引表不适用于 `补充文件` 下的其他分支，例如：

- `企业名称变更`
- `企业营业执照（或事业单位法人证书或其他组织登记证书）（扫描件）`
- `投标人基本情况表`
- `财务状况`
- `符合招标文件投标人资格要求的证明文件`

这些内容仍按 Excel 层级和 PDF 真实标题重新定位，不使用 `商务评审索引表` 的页码和标题。

## 12. 当前阶段不做的事

当前阶段不做：

- 不直接建数据库表结构
- 不直接做 SQLAlchemy 模型
- 不强行把所有表格压平为统一 schema
- 不自动决定是否正式入长期库

## 13. 后续迭代建议

后续可以继续增强：

- 增加 `table_sub_candidates.json`
- 为长表增加行级 chunk
- 对跨页表做自动合并
- 对复杂表头做结构恢复
- 用大模型辅助抽取字段
- 人工审核后再映射到数据库
