# 上下文保留型可复用子模块设计

## 1. 背景

当前系统已经可以：

- 基于 Excel 规则表生成 `section_path` 和模块归档目录。
- 从 PDF 中抽取文本块、表格索引、嵌入图片。
- 为部分复合型材料生成 `ordered_material.json`、`material_meta.json`、`compound_instance_meta.json`。

但当前结构仍有一个明显缺口：

- 可复用子模块虽然已经拆开保存，但“原始上下文”与“业务归档约束”尚未被明确分层。
- 后续引用时，系统需要的不只是某段文本或某张图，而是一个可直接套用的“多载体上下文包”。
- 这个上下文包既要保留原始顺序和载体类型，也要满足 Excel 规则表和存储规范文档对章节命名、模块归档的约束。

本设计定义一套新的保存原则：  
**先保留真实解析上下文，再叠加业务归档映射，最终输出可直接复用的子模块。**

## 2. 目标

### 2.1 核心目标

每一个可复用子模块都应当能同时回答以下问题：

- 它在原文档里原本长什么样。
- 它由哪些载体组成：`text` / `table` / `image`。
- 这些载体在原文里的顺序关系是什么。
- 它最终应该归入哪个 Excel 规则章节路径。
- 它在模块目录中应该如何命名和落盘。
- 后续引用时如何按原顺序直接重建。

### 2.2 非目标

本设计当前不追求：

- 直接入数据库。
- 在解析阶段强行把所有内容压平成单一字符串。
- 用业务规则覆盖原始标题和原始上下文。

## 3. 设计原则

### 3.1 两层并存，不互相覆盖

系统必须同时保存两套信息：

- 原始上下文层：来自 PDF、PP-StructureV3、表格抽取、原图抽取的真实结果。
- 业务归档层：来自 Excel 规则表和 `docs/reusable_material_storage_spec.md` 的路径、命名、模块归属约束。

原则：

- 原始上下文层负责“不失真”。
- 业务归档层负责“可管理、可复用、可对齐业务口径”。
- 业务归档层不能抹掉原始上下文层，只能在其上补充映射。

### 3.2 可复用单元不是纯文本，而是上下文包

一个可复用子模块不是一段压扁后的字符串，而是：

- 带顺序的多载体集合
- 带来源追溯信息
- 带章节归档映射

后续引用时，系统优先按上下文包重放，而不是按单一文本替换。

### 3.3 Excel 规则约束作用于归档层

Excel 规则表、Markdown 规范文档应决定：

- 归入哪个 `module_name`
- 归入哪个 `section_path`
- 最终目录结构如何组织
- 最终展示名和规范命名如何确定

但它们不应直接替代：

- 最近上方真实标题
- 页面真实阅读顺序
- 真实载体类型

### 3.4 图片优先保留原始嵌入图

如果 PDF 中存在原始嵌入图片，应优先直接抽取原图，并与页面上下文挂接。

只有在以下情况下才退回页面裁剪：

- PDF 中没有可抽取原图
- 页面为整页扫描图
- 布局区域与嵌入图并非一一对应

## 4. 解析与归档总流程

推荐流程如下：

1. 读取 Excel 规则表，生成 `module_name` / `section_path` / 业务归档约束。
2. 解析 PDF 原始文本块、TOC、嵌入图片元信息。
3. 用 PP-StructureV3 做页面级结构解析，识别页面中的 `text / table / image / title / header / footer`。
4. 对表格区域做表格抽取，对图片区域优先关联 PDF 原始嵌入图。
5. 生成统一的页面材料流 `page_material_stream`。
6. 基于真实标题和章节边界构造可复用子模块。
7. 再将子模块映射到 Excel 规则表定义的模块目录和章节路径。
8. 为每个子模块输出：
   - 原子材料项
   - 编排文件
   - 模块元数据
   - 复合实例索引

## 5. 数据分层

### 5.1 原始上下文层

该层记录“文档真实样貌”，来源于页面解析结果，不依赖业务规则。

建议字段：

- `raw_context_title`
- `nearest_heading`
- `nearest_heading_normalized`
- `container_heading`
- `page_no`
- `bbox`
- `source_type`
- `item_type`
- `reading_order`
- `block_id / table_id / image_id`
- `source_pdf`

### 5.2 业务归档层

该层记录“它最终应该被归到哪里”，来源于 Excel 和存储规范。

建议字段：

- `rule_section_path`
- `rule_module_name`
- `rule_match_source`
- `material_title`
- `material_title_source`
- `material_path`
- `folder_parts`
- `compound_instance_title`

### 5.3 复用编排层

该层服务于后续直接引用，是最终的“可复用上下文包”。

建议字段：

- `material_types`
- `dominant_material_type`
- `ordered_items`
- `render_strategy`
- `original_capture`

## 6. 统一中间模型

建议新增统一页面材料项模型 `MaterialItem`：

```json
{
  "item_id": "item_xxx",
  "item_type": "text",
  "source_type": "pp_structure_text",
  "page_no": 22,
  "bbox": [84, 121, 550, 143],
  "reading_order": 3,
  "raw_context_title": "企业营业执照副本",
  "nearest_heading": "3.4、企业营业执照（或事业单位法人证书或其他组织登记证书）（扫描件）",
  "container_heading": "补充文件",
  "rule_section_path": "商务文件 / 补充文件 / 企业营业执照（或事业单位法人证书或其他组织登记证书）（扫描件）",
  "rule_module_name": "补充文件",
  "material_title": "企业营业执照副本",
  "payload_ref": "text_items/text_001.json"
}
```

`item_type` 取值：

- `text`
- `table`
- `image`

`source_type` 示例：

- `pdf_text`
- `pp_structure_text`
- `pdf_embedded_image`
- `page_cropped_image`
- `pdf_table`
- `pp_structure_table`

## 7. 文件职责重定义

### 7.1 `ordered_material.json`

该文件应升级为**上下文编排文件**，而不是简单索引。

职责：

- 保留子模块内多载体材料的顺序关系。
- 记录每一项是什么类型、来自哪里、在什么位置。
- 作为后续“直接套用”的主要入口文件。

建议结构：

```json
{
  "material_title": "封面",
  "material_path": "商务文件 / 补充文件 / 财务状况 / 经会计师事务所或审计机构审计的财务会计报表 / 3.7.3、2024 年度财务审计报告 / 封面",
  "rule_section_path": "商务文件 / 补充文件 / 财务状况 / 经会计师事务所或审计机构审计的财务会计报表",
  "material_types": ["text", "image"],
  "dominant_material_type": "mixed",
  "items": [
    {
      "order": 1,
      "item_id": "text_001",
      "item_type": "text",
      "page_no": 464,
      "bbox": [72.0, 97.2, 144.3, 109.2],
      "nearest_heading": "（1）、封面",
      "payload_ref": "text_items/封面_文本1.json"
    },
    {
      "order": 2,
      "item_id": "image_001",
      "item_type": "image",
      "page_no": 464,
      "bbox": [72.0, 118.6, 523.3, 755.1],
      "nearest_heading": "（1）、封面",
      "payload_ref": "image_items/封面_图1.json"
    }
  ]
}
```

新增要求：

- `items` 中不再只放零散字段，应放统一格式的“编排项”。
- 每一项都必须带 `item_type`、`order`、`payload_ref`。
- 每一项都应保留 `nearest_heading` 和 `rule_section_path` 的映射痕迹。

### 7.2 `material_meta.json`

该文件应升级为**子模块总说明文件**。

职责：

- 描述该子模块整体是什么。
- 描述它的归档身份和来源范围。
- 描述它包含哪些载体类型。

建议新增字段：

- `material_path`
- `rule_section_path`
- `rule_module_name`
- `material_types`
- `dominant_material_type`
- `raw_context_title`
- `title_mapping`
- `render_strategy`

建议结构：

```json
{
  "material_title": "封面",
  "material_path": "商务文件 / 补充文件 / 财务状况 / 经会计师事务所或审计机构审计的财务会计报表 / 3.7.3、2024 年度财务审计报告 / 封面",
  "rule_section_path": "商务文件 / 补充文件 / 财务状况 / 经会计师事务所或审计机构审计的财务会计报表",
  "rule_module_name": "补充文件",
  "material_types": ["text", "image"],
  "dominant_material_type": "mixed",
  "raw_context_title": "（1）、封面",
  "title_mapping": {
    "raw_context_title": "（1）、封面",
    "nearest_heading": "封面",
    "material_title": "封面"
  },
  "source_file": "/path/source.pdf",
  "source_page_start": 464,
  "source_page_end": 465,
  "original_capture": {
    "available": true
  },
  "review_status": "pending"
}
```

### 7.3 `compound_instance_meta.json`

该文件应升级为**复合实例索引文件**，负责描述一个大实例下有哪些可复用子模块。

职责：

- 保留复合实例级边界。
- 汇总子模块清单。
- 提供子模块之间的顺序和概览。

建议新增字段：

- `instance_path`
- `rule_anchor_path`
- `instance_material_types`
- `children[].material_path`
- `children[].material_types`
- `children[].dominant_material_type`

建议结构：

```json
{
  "material_type": "compound_instance",
  "rule_anchor_path": "商务文件 / 补充文件 / 财务状况 / 经会计师事务所或审计机构审计的财务会计报表",
  "instance_title": "3.7.3、2024 年度财务审计报告",
  "instance_path": "商务文件 / 补充文件 / 财务状况 / 经会计师事务所或审计机构审计的财务会计报表 / 3.7.3、2024 年度财务审计报告",
  "children": [
    {
      "material_title": "封面",
      "material_path": "... / 封面",
      "material_types": ["text", "image"],
      "dominant_material_type": "mixed",
      "ordered_item_count": 4
    }
  ]
}
```

## 8. 原子材料项要求

每类原子项都应独立保存 JSON，并提供统一公共字段。

### 8.1 通用字段

- `item_id`
- `item_type`
- `material_path`
- `material_title`
- `rule_section_path`
- `rule_module_name`
- `page_no`
- `bbox`
- `nearest_heading`
- `container_heading`
- `reading_order`
- `source_file`

### 8.2 文本项

额外字段：

- `text`
- `source_block_id`
- `source_type`

### 8.3 表格项

额外字段：

- `table_rows`
- `table_title`
- `table_title_source`
- `source_table_id`

### 8.4 图片项

额外字段：

- `image_title`
- `image_title_source`
- `file_path`
- `json_path`
- `image_origin`
- `xref`
- `image_rect`

其中 `image_origin` 取值建议：

- `pdf_embedded`
- `page_crop`
- `external_attachment`

## 9. 标题映射规则

每个子模块和每个原子项都应保留三类标题：

### 9.1 原始上下文标题

例如：

- `（1）、封面`
- `附：法定代表人（单位负责人）身份证（扫描件）`

### 9.2 解析归一化标题

例如去前缀、去编号、清理空白后：

- `封面`
- `法定代表人（单位负责人）身份证（扫描件）`

### 9.3 业务归档标题

例如按 Excel 和规范最终落盘：

- `封面`
- `企业营业执照副本`

建议统一保存到：

```json
"title_mapping": {
  "raw_context_title": "（1）、封面",
  "normalized_context_title": "封面",
  "rule_section_path": "商务文件 / 补充文件 / 财务状况 / 经会计师事务所或审计机构审计的财务会计报表",
  "material_title": "封面"
}
```

## 10. 与 Excel 和 Markdown 规范的关系

### 10.1 Excel 规则表约束

Excel 规则表负责：

- 决定模块边界
- 决定 `section_path`
- 决定复合型材料的锚点路径
- 提供规则 fallback

### 10.2 Markdown 存储规范约束

存储规范负责：

- 命名优先级
- 模块目录结构
- 单项 JSON 独立保存
- 上下文追溯要求
- 混合型材料保存要求

### 10.3 二者的作用边界

二者共同作用于“归档层”，但不能覆盖原始上下文层。

最终实现必须满足：

- 原始上下文可回放
- 业务目录可稳定归档
- 后续可直接引用

## 11. 推荐实现顺序

### 阶段一：补中间层

- 新增统一 `MaterialItem` 中间模型。
- 统一 text/table/image 的页面级材料流。

### 阶段二：升级模块输出结构

- 升级 `ordered_material.json`
- 升级 `material_meta.json`
- 升级 `compound_instance_meta.json`

### 阶段三：接入 PP-StructureV3

- 将 PP-StructureV3 输出接入页面级材料流。
- 将原始嵌入图与结构区域建立关联。

### 阶段四：稳定规则映射

- 用 Excel 规则和现有 heading 逻辑做双层映射。
- 对复杂复合实例做专项验证。

## 12. 成功标准

如果以下条件都成立，则视为设计目标达成：

- 任一可复用子模块都能明确区分 `text/table/image`。
- 任一子模块都能按 `ordered_material.json` 恢复原顺序。
- 任一原子项都能追溯到原 PDF 页码、bbox、来源对象。
- 任一子模块都能映射到 Excel 规则表中的业务章节路径。
- 任一复合实例都能保留实例级上下文和子模块级上下文。
- 后续引用时不需要重新猜“哪里是文字、哪里是表格、哪里是图片”。
