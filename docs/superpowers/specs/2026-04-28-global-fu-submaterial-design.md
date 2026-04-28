# Global `附：` Submaterial Design

## Goal

Make `附：xxx` / `附:xxx` a global, cross-section submaterial rule so reusable packages preserve:

- the parent section's original item order
- the distinction between `text`, `table`, and `image`
- a separately reusable child package whose title is the text after `附：`

This rule must apply to any section, not only `4、法定代表人授权委托书`.

## Problem

The current pipeline already recognizes `附：...` as heading-like text in some places, but it does not treat it as a general-purpose packaging boundary across all modules.

That leaves two gaps:

1. A parent section may contain a meaningful attachment block, but the block is only represented as loose items instead of a reusable child package.
2. The preferred attachment title rule from the storage spec is not enforced uniformly during module packaging.

For example:

- parent section: `4、法定代表人授权委托书`
- inline attachment anchor: `附：法定代表人（单位负责人）身份证（扫描件）`

Desired result:

- parent module remains `法定代表人授权委托书`
- a child submaterial is created under that module
- the child submaterial title becomes `法定代表人（单位负责人）身份证（扫描件）`
- the child package preserves its internal `text/table/image` order
- the parent package retains its full sequence and a reference back to the child package

## Scope

In scope:

- detect `附：xxx` / `附:xxx` as a global child-package anchor
- create submaterial packages under the current matched section/module
- normalize child titles by removing only the `附：` prefix
- preserve both parent-order context and child-package reusability
- make the output explicit in `ordered_material.json`, `material_meta.json`, and related manifests
- add regression tests for non-`法定代表人授权委托书` sections

Out of scope:

- changing Excel matching logic for top-level section boundaries
- changing how PP-StructureV3 detects page regions
- introducing a brand-new document model beyond the current package schemas

## Existing Constraints

### Excel and Markdown remain the outer rule system

Excel still decides:

- module boundaries
- section paths
- fallback business naming

The Markdown storage spec still decides:

- naming priority
- path shape
- traceability requirements

The new `附：` rule only applies inside an already matched section/module.

### PP-StructureV3 remains the structural backbone

PP-StructureV3 is still the required source for page-level context preservation:

- which content is `text`
- which content is `table`
- which content is `image`
- item order within a page/section

The new rule does not replace that. It groups a subset of those items into child packages.

## Design

### 1. Attachment anchor semantics

Any heading-like text that matches `^附[:：]\s*` is treated as a child-package anchor within the current section context.

Examples:

- `附：法定代表人（单位负责人）身份证（扫描件）`
- `附: 被授权人身份证（扫描件）`
- `附：营业执照副本`

The normalized child-package title is the text after the prefix:

- `法定代表人（单位负责人）身份证（扫描件）`
- `被授权人身份证（扫描件）`
- `营业执照副本`

### 2. Parent package behavior

The parent package must continue to preserve the full original order of material items. This matters because the user wants to reuse the whole section later without losing context.

So the parent `ordered_material.json` should still list all parent-visible content in order, while also carrying explicit submaterial references where applicable.

That means the parent package is not reduced to a shallow index. It remains a full context package.

### 3. Child package behavior

Each `附：xxx` anchor creates a child submaterial package under the current parent module or section package.

The child package:

- gets its own directory
- gets its own `ordered_material.json`
- gets its own `material_meta.json`
- contains the items that belong to the anchor span
- preserves internal `text/table/image` order

Attachment span boundary:

- starts at the anchor block
- ends at the next sibling heading/anchor within the same parent section
- if no next sibling heading exists, it extends to the end of the parent section span

### 4. Title mapping rules

Each child package must retain:

- `raw_context_title`: the original anchor text, such as `附：法定代表人（单位负责人）身份证（扫描件）`
- `normalized_context_title`: the de-prefixed title
- `material_title`: the same normalized title unless a later business fallback explicitly overrides it
- `parent_section_title`: the enclosing section title

This keeps both traceability and clean reusable naming.

### 5. Output representation

At minimum, the output should support:

- parent package with ordered items
- child package with ordered items
- parent-to-child reference

Recommended parent item shape for a child package reference:

```json
{
  "order": 6,
  "item_type": "submaterial",
  "payload_ref": "submaterials/法定代表人（单位负责人）身份证（扫描件）/ordered_material.json",
  "nearest_heading": "附：法定代表人（单位负责人）身份证（扫描件）",
  "material_path": "商务文件 / 法定代表人授权委托书 / 法定代表人（单位负责人）身份证（扫描件）"
}
```

This does not require the parent package to remove its own atomic items immediately, but the representation must be explicit enough for downstream reuse.

### 6. Naming and directory rules

Directory names and asset names should use the normalized child title, not the raw `附：` form.

Example:

```text
modules/
  法定代表人授权委托书/
    ordered_material.json
    submaterials/
      法定代表人（单位负责人）身份证（扫描件）/
        ordered_material.json
        material_meta.json
        image_items/
```

If the current codebase must remain closer to its existing path shape, the same naming rule still applies even if the directory remains directly nested without an explicit `submaterials/` layer.

## Data Flow

1. Section candidate is matched from Excel rules.
2. PP-Structure/PDF parsing provides ordered page-level material items.
3. Heading utilities identify `附：` anchors among heading candidates.
4. Module packager groups items under the current parent section.
5. For each `附：` anchor, the packager creates a child-package span.
6. Parent and child package manifests are written with traceable title mapping.

## Error Handling

- If an `附：` anchor exists but no material items fall under it, write a child package with empty `items` and a review-needed marker rather than silently dropping it.
- If two normalized child titles collide within the same parent package, suffix later directories and payload refs with `_2`, `_3`, etc. while keeping the display `material_title` unchanged.
- If a candidate has no explicit `附：` anchor, packaging falls back to the existing nearest-heading logic.

## Testing

Required regression coverage:

1. `附：` anchors are treated as headings globally, not only in attachment-specific exporters.
2. A non-authorization section with `附：xxx` creates a child package.
3. The child package title strips the prefix correctly.
4. Parent package order is preserved and contains a child-package reference.
5. Child package preserves its own `text/table/image` ordering.
6. Duplicate `附：` titles under one parent are disambiguated safely.

## Recommendation

Implement this as a general module-packaging rule, not a one-off special case in `法定代表人授权委托书`.

That keeps the behavior consistent with the storage spec, matches the user's reuse goal, and avoids a growing list of section-specific exceptions.
