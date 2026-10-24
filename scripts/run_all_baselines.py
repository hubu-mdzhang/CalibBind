#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一键运行全部四类基线 + 汇总对比。

四类基线：
    A  规则知识库（波长推断）        —— 上界参照
    B  向量检索（波段级 + 角色级）    —— 对比知识库粒度
    C  生成式大模型                  —— 含/不含波长两种输入
    D  决策模型 Jev                  —— 含/不含波长两种输入

用法：
    python run_all_baselines.py              # 跑全部（跳过已完成的）
    python run_all_baselines.py --force      # 全部重跑
    python run_all_baselines.py --only rag jev
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent   # 技能根目录
DATA = BASE / "data"

BASELINES = {
    "rag": "rag_band_matcher.py",
    "llm": "llm_band_matcher.py",
    "jev": "jev_band_matcher.py",
}

RESULT_FILES = {
    "规则库": None,                      # 由 build_validation_dataset 产出
    "RAG·波段级": "rag_results_band_level.json",
    "RAG·角色级": "rag_results_role_level.json",
    "LLM·仅标签": "llm_results_labels_only.json",
    "LLM·含波长": "llm_results_with_wavelength.json",
    "Jev·仅标签": "jev_results_labels_only.json",
    "Jev·含波长": "jev_results_with_wavelength.json",
}


def run(script: str, title: str) -> bool:
    print(f"\n{'=' * 60}\n  {title}\n{'=' * 60}")
    f = BASE / script
    if not f.exists():
        # 从上一级目录找
        f = BASE.parent / script
    if not f.exists():
        print(f"  跳过：找不到 {script}")
        return False
    r = subprocess.run([sys.executable, str(f)], cwd=str(BASE))
    return r.returncode == 0


def summarize():
    """汇总所有基线结果。"""
    print(f"\n{'=' * 68}\n  四类基线汇总\n{'=' * 68}")
    head = f"{'方法':<16}{'端到端':>9}{'参数级':>9}{'Top3':>8}{'Brier':>9}{'NLL':>9}{'耗时ms':>9}"
    print(head)
    print("-" * 68)

    rows = []
    # 规则库作为上界
    if (DATA / "dataset_matching.json").exists():
        print(f"{'A 规则库':<16}{'100.0%':>9}{'100.0%':>9}{'-':>8}{'-':>9}{'-':>9}{'0':>9}")
        rows.append({"方法": "规则库", "准确率": 100.0})

    for label, fname in RESULT_FILES.items():
        if not fname:
            continue
        p = DATA / fname
        if not p.exists():
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        acc = d.get("acc", 0) * 100
        par = d.get("role_acc", 0) * 100
        t3 = (f"{d['top3_recall']*100:.1f}%"
              if d.get("top3_recall") is not None else "-")
        br = f"{d['brier']:.4f}" if d.get("brier") is not None else "-"
        nl = f"{d['nll']:.4f}" if d.get("nll") is not None else "-"
        ms = f"{d.get('avg_ms', 0):.0f}"
        print(f"{label:<16}{acc:>8.1f}%{par:>8.1f}%{t3:>8}{br:>9}{nl:>9}{ms:>9}")
        rows.append({"方法": label, "准确率": round(acc, 1),
                     "Brier": d.get("brier"), "NLL": d.get("nll")})

    (DATA / "summary.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n已保存 data/summary.json")


def independence_check():
    """独立性检验 —— 决定结论能否支撑统计显著性。"""
    f = DATA / "dataset_matching.json"
    if not f.exists():
        return
    rows = json.loads(f.read_text(encoding="utf-8"))
    csets = {tuple(sorted(r["band_options"])) for r in rows}
    print(f"\n  样本 {len(rows)} 条 / 唯一候选集 {len(csets)} 种 / "
          f"产品 {len({r['product_name'] for r in rows})} 个")
    if len(csets) < len(rows) * 0.5:
        print("  [提示] 样本存在明显聚类，报告置信区间时应按唯一候选集计算，"
              "不可直接用样本数。")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="强制重跑已完成的基线")
    ap.add_argument("--only", nargs="*", choices=list(BASELINES), help="只跑指定基线")
    a = ap.parse_args()

    todo = a.only or list(BASELINES)
    if not DATA.exists():
        DATA.mkdir(exist_ok=True)

    t0 = time.time()
    for name in todo:
        script = BASELINES[name]
        if not a.force:
            # 已完成的跳过
            done = any((DATA / f).exists() for f in RESULT_FILES
                       if name in f)
            if done:
                print(f"\n[跳过] {name}：结果已存在（--force 可强制重跑）")
                continue
        run(script, f"运行基线 {name}")

    summarize()
    independence_check()
    print(f"\n总耗时 {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
