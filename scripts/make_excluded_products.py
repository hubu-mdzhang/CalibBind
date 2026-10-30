# -*- coding: utf-8 -*-
"""生成 data/EXCLUDED_PRODUCTS.md（排除产品名单，全部字段由数据计算，不手抄）。"""
import hashlib
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
D = Path(__file__).resolve().parent.parent / "data"


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()[:12]


dp = json.load(open(D / "dataset_products.json", encoding="utf-8"))
bench = json.load(open(D / "dataset_matching_extended.json", encoding="utf-8"))
in_bench = {r["product_name"] for r in bench}
prods = [p for c in dp for p in c["products"]]
defined = [p for p in prods if p.get("bands")]
excluded = [p for p in defined
            if p["name"] not in in_bench and (p.get("alias") or "") not in in_bench]
single = [p for p in excluded if len(p["bands"]) == 1]
multi = [p for p in excluded if len(p["bands"]) > 1]

assert len(defined) == 49 and len(in_bench) == 33 and len(excluded) == 16, "口径断言失败"
assert len(single) == 13 and len(multi) == 3, "分类断言失败"

L = ["# Excluded products（未进入基准的波段定义产品）", "",
     "由 `data/dataset_products.json`（56 个波段类产品，49 个具波段定义）与",
     "`data/dataset_matching_extended.json`（33 个基准产品）程序化对账生成；",
     "复算脚本断言：49 − 33 = 16 = 单波段 13 + 多波段 3。", ""]
L += ["## 多波段产品（3 个：与任何算子未构成有效候选选择题）", "",
      "| 产品 | 类别 | 波段数 |", "|---|---|---|"]
for p in sorted(multi, key=lambda x: x["name"]):
    L.append(f"| `{p['name']}` | {p['catalogName']} | {len(p['bands'])} |")
L += ["", "## 单波段产品（13 个：仅一个候选成员，不构成候选选择任务）", "",
      "| 产品 | 类别 |", "|---|---|"]
for p in sorted(single, key=lambda x: (x["catalogName"], x["name"])):
    L.append(f"| `{p['name']}` | {p['catalogName']} |")
L += ["", "## 溯源", "",
      f"- `dataset_products.json` sha256[:12] = `{sha(D / 'dataset_products.json')}`",
      f"- `dataset_matching_extended.json` sha256[:12] = `{sha(D / 'dataset_matching_extended.json')}`",
      "- 生成脚本：`scripts/make_excluded_products.py`（本文件由其输出，勿手改）"]

out = D / "EXCLUDED_PRODUCTS.md"
out.write_text("\n".join(L) + "\n", encoding="utf-8")
print("已生成", out)
print("\n".join(L[:12]))
