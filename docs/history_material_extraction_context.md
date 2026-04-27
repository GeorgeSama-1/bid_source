# 历史标书材料抽取上下文摘要

## 1. 当前项目目标

当前系统不是最终知识库，而是“历史标书入库前解析与召回验证层”。

第一阶段重点不是数据库，而是先跑通：

- PDF 解析
- 表格抽取
- 章节重建
- Excel 规则和 PDF 实际章节匹配
- 可复用材料抽取
- 材料打包与人工审查
- 后续召回验证

当前明确约束：

- 不建数据库
- 所有中间结果先保存为 JSON / JSONL / CSV / MD / PDF / PNG
- 原始 PDF 必须保留
- 每条材料都要能追溯到来源文件、页码、bbox、block_id
- 程序不能替代人工做最终判断

## 2. 当前“可复用”判断原则

当前只保留 Excel 中：

`是否从往期投标文件中摘取 = 是`

的内容。

这是第一优先级。

`是否提供标准格式 = 是`

这类内容可以作为后续补充策略，但当前主线还是先围绕 `from_history_bid = true`。

## 3. 当前抽取总逻辑

整体流程：

1. Excel 规则表读取为标准归档树。
2. 只保留 `from_history_bid = true` 的规则项。
3. 解析 PDF，提取：
   - text blocks
   - tables
   - images
   - toc
4. 重建 PDF 实际标题结构。
5. 把 Excel 标准路径和 PDF 实际标题做匹配。
6. 对可复用内容做材料打包。

当前材料打包分两类：

### 3.1 普通材料包

适用于一般章节，例如：

- `3.8.13.2、供应链保障措施`
- `3.8.12、高新技术企业`
- `3.8.6.1、企业发布ESG（环境、社会和公司治理）报告`

这类材料包结构为：

```text
章节目录/
  material_meta.json
  ordered_material.json
  original/
    source_pages.pdf
    source_preview.png
    source_capture_status.json
  text_items/
  table_items/
  image_items/
```

其中：

- `original/source_pages.pdf` 保留原 PDF 页格式
- `text_items` 保存结构化文字和阅读版 md
- `table_items` 保存表格结构化结果
- `image_items` 保存独立图片及元数据
- `ordered_material.json` 记录文字、表格、图片在 PDF 中的顺序

### 3.2 复合材料包

适用于 Excel 是一个标准归档锚点，但 PDF 中展开成多个真实主体的情况。

典型例子：

`补充文件 / 财务状况 / 经会计师事务所或审计机构审计的财务会计报表`

PDF 实际上不是只有一个“利润表”，而是：

- `3.7.1、2022 年度财务审计报告`
- `3.7.2、2023 年度财务审计报告`
- `3.7.3、2024 年度财务审计报告`

每个年度主体下面还有多个子项：

- 封面
- 目录
- 审计报告
- 资产负债表
- 利润表
- 现金流量表
- 财务报表附注
- 附件

所以不能把所有东西都塞进 `利润表/` 目录。

正确结构应为：

```text
经会计师事务所或审计机构审计的财务会计报表/
  compound_materials_manifest.json
  3.7.1、2022 年度财务审计报告/
    compound_instance_meta.json
    封面/
    目录/
    审计报告/
    资产负债表/
    利润表/
    现金流量表/
    财务报表附注/
    附件/
  3.7.2、2023 年度财务审计报告/
    ...
  3.7.3、2024 年度财务审计报告/
    ...
```

## 4. 当前命名规则

### 4.1 普通章节中的图片和表格

图片、表格命名默认使用：

`最近的上方有效标题`

例如：

- `利润表_图1.json`
- `财务报表附注_图8.json`
- `供应链保障措施.md`

### 4.2 复合材料中的子项命名

子项目录名使用子标题本身，但会去掉编号前缀，例如：

- `（5）、利润表` -> `利润表`
- `（7）、财务报表附注` -> `财务报表附注`

也就是说，当前已经不再保留 `（5）、利润表_图1.json` 这种命名，而是统一为：

- `利润表_图1.json`
- `审计报告_图1.json`
- `目录_图1.json`

## 5. 已经修正过的关键问题

### 5.1 商务评分标准索引表

之前已经实现：

- 从 PDF 中解析 `商务评审索引表`
- 识别大项、小项、页码、标题
- 将其和 Excel 的“商务评分标准涉及的支撑材料”做对齐
- 基于索引页码和标题去限定材料抽取范围

### 5.2 图片噪声过滤

已经处理：

- 左上角重复 logo
- 很小的装饰性图片
- 印章/签名类明显噪声的部分问题

但后续仍可能继续加强过滤策略。

### 5.3 纯文字材料

已经支持纯文字材料独立保存，不再只处理图片和表格。

例如：

- `供应链保障措施`
- `创新激励机制`
- `高新技术企业`

### 5.4 财务报表误归类问题

之前错误情况：

- `目录_图1.json`
- `财务报表附注_图8.json`

被错误放进：

`.../利润表/image_items/`

现在已修正为按年度主体 + 子项拆分保存。

## 6. 当前复合材料规则机制

程序现在支持：

- 默认内置复合材料规则
- `manual_config` 中追加 `compound_material_rules`

当前内置示例主要用于财务报表：

```json
{
  "excel_anchor_path": "商务文件 / 补充文件 / 财务状况 / 经会计师事务所或审计机构审计的财务会计报表",
  "instance_title_patterns": [
    "20\\d{2}.*(?:会计|财务|审计).*(?:报表|报告)"
  ],
  "auto_detect_children": true,
  "store_unlisted_children": true,
  "child_title_include_patterns": [],
  "child_title_exclude_patterns": [
    "商务投标文件",
    "国网.*公司",
    "^\\d+$"
  ],
  "child_title_rename_map": {
    "合并利润表": "利润表",
    "母公司利润表": "利润表"
  }
}
```

其中：

- `excel_anchor_path`：Excel 标准归档锚点
- `instance_title_patterns`：PDF 中真实主体识别规则
- `auto_detect_children`：子项由程序自动识别
- `store_unlisted_children`：即使 Excel 没列出，也允许保留该主体下其他子项
- `child_title_exclude_patterns`：过滤噪声标题
- `child_title_rename_map`：对子项标题做归一化

## 7. 当前程序文件和关键模块

关键模块：

- `bid_knowledge/parsing/module_packager.py`
  - 普通材料包
  - 复合材料包
  - 原格式页导出
  - ordered material
- `bid_knowledge/parsing/review_index_parser.py`
  - 商务评审索引表解析
- `bid_knowledge/cli.py`
  - `package-materials`
  - `pipeline`
- `configs/manual_config.example.json`
  - OCR、章节覆盖、复合材料规则
- `docs/extraction_flow.md`
  - 当前抽取流程图

## 8. 当前流程图文档

已存在：

- [docs/extraction_flow.md](./extraction_flow.md)

该文档描述了：

- Excel -> processing_plan -> PDF 解析 -> 匹配 -> 普通材料包 / 复合材料包 -> 输出目录

## 9. 当前验证状态

最近一次测试状态：

- `56 passed`

已验证：

- 普通章节材料包
- 商务评审索引子项打包
- 纯文字章节保存
- 原格式 PDF 页导出
- 财务报表复合材料包
- 目录/利润表/附注不再错归到同一目录

## 10. 当前仍需继续观察和迭代的问题

后续仍然值得继续优化：

- 印章、签名、极小噪声图片的进一步过滤
- 复合材料子项自动识别的稳定性
- 图片和表格跨页边界切分
- 复杂目录和正文标题不完全一致时的匹配增强
- 更多复合材料场景：
  - 项目业绩材料
  - 人员资质材料
  - 证书/专利材料
  - 其他年度型/多实例材料

## 11. 对新窗口最重要的一句话

当前系统的核心原则是：

**Excel 定义标准归档锚点，PDF 提供真实主体和真实子项，程序负责把可复用内容按“普通材料包”或“复合材料包”保存，并保留原格式页、文字、图片、表格和顺序信息。**
