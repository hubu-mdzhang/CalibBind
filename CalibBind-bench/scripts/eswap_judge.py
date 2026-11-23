# -*- coding: utf-8 -*-
"""E-SWAP 判定（实现 = 协议 §E-SWAP 冻结口径，2026-10-23 评审修订版）。

用法: python eswap_judge.py eval_eswap_lfoA_s0.jsonl [eval_eswap_lfoA_s1.jsonl ...]
  （文件为 results_v2/eswap/ 下 A_lfo 三种子 + 参照模型的评测产物）
先于任何结果存在即可运行 --selftest（仅模拟组件，不读评测）。

三分类（题级，分母 239）：新真值命中(e2e) / 旧真值保持(非新且对 original_gt 全对) / 其他。
阴性对照：逐元素 K_j 均匀随机的端到端命中率 p(q)=Π 1/K_j；池化基线 = 固定种子
20261023 × 100,000 模拟；显著高于随机 = 实测 > 模拟 95 百分位（单侧 α=0.05）。
出口：A_lfo 池化 wl 命中 ≥70% 且 wl−lo ≥40pp 且对照不显著 → 1；40–70% → 2；<40% 或异常 → 3。
"""
import json, os, random, sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEED, N_SIM = 20261023, 100_000

# eswap_ds.json ships in eswap/ (fall back to legacy data/ layout)
_ds = os.path.join(BASE, "eswap", "eswap_ds.json")
if not os.path.exists(_ds):
    _ds = os.path.join(BASE, "data", "eswap_ds.json")
eswap = {d["sample_id"]: d for d in
         json.load(open(_ds, encoding="utf-8"))}

def old_key(elem, orig_val):
    """元素级旧真值的候选键（rank 参数转 str，name 参数原标签）。"""
    return str(orig_val) if isinstance(orig_val, int) else orig_val

def classify(path):
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    per_mode = defaultdict(lambda: [0, 0, 0])   # mode -> [新, 旧, 其他]
    per_grp = defaultdict(lambda: [0, 0, 0])    # (mode, grp) -> [新, 旧, 其他]
    ks = {}                                     # sample_id -> [K_j ...]
    grp_of = {"T1": "T1/T3", "T3": "T1/T3", "T2": "T2", "T4": "T4", "T5": "T5"}
    for r in rows:
        q = eswap[r["sample_id"]]
        m = r["mode"]
        g = grp_of[q["task"]]
        new_hit = r["correct"] == r["total"]
        old_hit = False
        if not new_hit:
            orig = q["original_ground_truth"]
            det = r["details"]
            if det and all(d["pred"] == old_key(i, orig[d["param"]]) for i, d in enumerate(det)):
                old_hit = True
        a = per_mode[m]
        a[0 if new_hit else (1 if old_hit else 2)] += 1
        b = per_grp[(m, g)]
        b[0 if new_hit else (1 if old_hit else 2)] += 1
        if m == "with_wavelength":
            ks[r["sample_id"]] = [len(d["probabilities"]) for d in r["details"]]
    return per_mode, per_grp, ks

def sim_baseline(ks):
    rng = random.Random(SEED)
    ps = []
    for qid, kk in ks.items():
        p = 1.0
        for k in kk:
            p /= max(1, k)
        ps.append(p)
    hits = sorted(sum(1 for p in ps if rng.random() < p) / len(ps) for _ in range(N_SIM))
    return hits[int(0.95 * N_SIM)]   # 95 百分位（单侧 α=0.05）

def selftest():
    # 30 题平滑分布：模拟均值必须对齐理论均值（机制校验），p95 > 均值（单侧分位 sanity）
    ks = {f"q{i}": [k] for i, k in enumerate([5, 4, 7, 2, 3, 6, 8, 9, 4, 5] * 3)}
    rng = random.Random(1)
    ps = [1 / k for k in (5, 4, 7, 2, 3, 6, 8, 9, 4, 5) * 3]
    thr = sim_baseline(ks)
    hits = sorted(sum(1 for p in ps if rng.random() < p) / len(ps) for _ in range(2000))
    mean_p = sum(ps) / len(ps)
    emp_mean = sum(hits) / len(hits)
    assert abs(emp_mean - mean_p) < 0.005, (emp_mean, mean_p)
    assert thr > mean_p
    print(f"SELFTEST 模拟组件: 理论均值 {mean_p:.4f} ≈ 经验均值 {emp_mean:.4f}, "
          f"p95={thr:.4f} > 均值 PASS")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        selftest()
        sys.exit(0)
    paths = sys.argv[1:]
    assert paths, "给出评测 jsonl 路径"
    for path in paths:
        tag = os.path.basename(path).replace("eval_", "").replace("_smoke.jsonl", "")
        per_mode, per_grp, ks = classify(path)
        n = sum(per_mode["with_wavelength"])
        p95 = sim_baseline(ks)
        print(f"== {tag} (n={n}, 可定义子集) ==")
        for m in ("with_wavelength", "labels_only"):
            a = per_mode[m]
            tot = sum(a)
            print(f"  {m}: 新 {100*a[0]/tot:.1f}% 旧 {100*a[1]/tot:.1f}% 其他 {100*a[2]/tot:.1f}%"
                  f"（{a[0]}/{a[1]}/{a[2]}）")
        for g in ("T1/T3", "T2", "T4", "T5"):
            a = per_grp[("with_wavelength", g)]
            if not sum(a):
                continue
            tot = sum(a)
            print(f"    含波长·{g}: 新 {100*a[0]/tot:.1f}% 旧 {100*a[1]/tot:.1f}% "
                  f"其他 {100*a[2]/tot:.1f}%（{a[0]}/{a[1]}/{a[2]}，n={tot}）")
        gap = (per_mode["with_wavelength"][0] - per_mode["labels_only"][0]) / n * 100
        ctrl_pct = per_mode["labels_only"][0] / n * 100
        ctrl_hi = ctrl_pct > p95 * 100
        print(f"  wl−lo 差 {gap:+.1f}pp | 对照 {ctrl_pct:.1f}% vs 随机p95 {p95*100:.1f}% "
              f"({'对照异常高→查构造' if ctrl_hi else '对照未检出高于随机'})")
        if "lfoA" in tag:
            new_pct = per_mode["with_wavelength"][0] / n * 100
            if new_pct >= 70 and gap >= 40 and not ctrl_hi:
                v = "出口 1"
            elif 40 <= new_pct < 70:
                v = "出口 2"
            else:
                v = "出口 3"
            if new_pct >= 70 and gap < 40:
                v = "不判出口 1（差值 <40pp，落出口 2 区间报告）" if new_pct >= 40 else v
            print(f"  --> A_lfo 判定: {v}（命中率 {new_pct:.1f}%）")
        print()
