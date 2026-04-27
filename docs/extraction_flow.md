# 标书历史材料抽取流程

当前程序只保存 Excel 中“是否从往期投标文件中摘取”为“是”的内容。Excel 负责定义标准归档位置，PDF 负责提供真实材料标题、页码、图片、表格和正文。

```mermaid
flowchart TD
    A[Excel 章节规则表] --> B[读取规则并筛选 from_history_bid = true]
    C[manual_config.json] --> D[人工控制规则]
    D --> D1[OCR 页码和章节]
    D --> D2[跳过章节和覆盖策略]
    D --> D3[复合材料规则 compound_material_rules]

    B --> E[生成 processing_plan]
    D --> E

    F[原始 PDF] --> G[PyMuPDF 解析]
    G --> G1[text_blocks: text + page + bbox + block_id]
    G --> G2[images: image + page + rect]
    G --> G3[toc]
    F --> H[pdfplumber 抽取 tables]

    G1 --> I[重建 PDF 真实标题结构]
    G3 --> I
    I --> J[Excel 标准路径和 PDF 标题匹配]
    E --> J

    J --> K{是否命中复合材料规则?}

    K -- 否 --> L[普通材料包]
    L --> L1[按 Excel 路径建文件夹]
    L --> L2[按最近有效标题命名图片/表格/文字]
    L --> L3[保存 original/source_pages.pdf]
    L --> L4[保存 text_items/table_items/image_items]
    L --> L5[保存 ordered_material.json 和 material_meta.json]

    K -- 是 --> M[复合材料包]
    M --> M1[Excel anchor_path 作为归档锚点]
    M --> M2[用 instance_title_patterns 找 PDF 真实主体]
    M2 --> M3[例如 2022年度财务报表 / 2023年度财务报表]
    M3 --> M4[在每个主体内自动识别 child_titles]
    M4 --> M5[目录 / 审计报告 / 资产负债表 / 利润表 / 附注等]
    M5 --> M6[每个子项独立保存完整材料包]

    L5 --> N[outputs/history_run/modules]
    M6 --> N
    N --> O[人工审查]
    O --> P[后续正式入库或召回测试]
```

## 当前抽取逻辑

1. Excel 是标准归档树。程序先只取 `from_history_bid = true` 的规则，不保存不可复用内容。
2. 普通章节按 Excel 路径建文件夹，再用 PDF 中最近的上方有效标题给文字、图片、表格命名。
3. 每个可复用章节都会生成完整材料包：`material_meta.json`、`ordered_material.json`、`original/source_pages.pdf`、`original/source_preview.png`、`text_items`、`table_items`、`image_items`。
4. 如果 PDF 中出现多个真实主体，而 Excel 只是一个归档锚点，就走复合材料包逻辑。
5. 复合材料包中，`instance_title_patterns` 负责识别主体，例如 `2022年度财务报表`；主体下面的子项由程序自动识别，不要求人工穷举。
6. `child_title_exclude_patterns` 用来过滤页眉、页码、公司名等噪声；`child_title_rename_map` 用来把不同叫法归一。

## 财务报表示例

标准归档锚点：

```text
商务文件 / 补充文件 / 财务状况 / 经会计师事务所或审计机构审计的财务会计报表
```

PDF 真实结构：

```text
2022年度财务报表/
  目录/
  审计报告/
  资产负债表/
  利润表/
  现金流量表/
  财务报表附注/

2023年度财务报表/
  目录/
  审计报告/
  资产负债表/
  利润表/
  ...
```

输出结构：

```text
modules/
  补充文件/
    财务状况/
      经会计师事务所或审计机构审计的财务会计报表/
        2022年度财务报表/
          目录/
          审计报告/
          资产负债表/
          利润表/
          财务报表附注/
        2023年度财务报表/
          目录/
          利润表/
          ...
```

核心原则：Excel 定归档位置，PDF 定真实材料实例，最近标题定材料名称，配置规则负责纠偏。
