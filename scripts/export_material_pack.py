#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bid_knowledge.export.lightweight_material_pack import export_lightweight_material_pack


def main() -> None:
    parser = argparse.ArgumentParser(description="Export a lightweight material package with material.md, image files, and table JSON files.")
    parser.add_argument("--output-dir", required=True, help="Pipeline output directory, for example outputs/structure_run_v6")
    parser.add_argument("--package-dir", default=None, help="Optional temporary package directory. Defaults to <output-dir>/material_pack")
    parser.add_argument("--zip", dest="zip_path", default=None, help="Optional zip output path. Defaults to <output-dir>/material_pack.zip")
    args = parser.parse_args()

    result = export_lightweight_material_pack(
        args.output_dir,
        package_dir=args.package_dir,
        zip_path=args.zip_path,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
