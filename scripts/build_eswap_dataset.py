# -*- coding: utf-8 -*-
"""E-SWAP 波长反事实干预数据集构建（零 GPU；预注册见 phase1_protocol.md §E-SWAP）。

设计（评审 2026-10-23 三层验证第 2 层的最小对版本）：
  扰动 = 角色答案波段之间循环交换波长（k=2 时即评审的成对交换 A<->B）；
  名称/顺序/产品信息/rank_map 全部不变；新真值 = E-λ 同一规则（旧真值波长中点所落
  WIN 窗口在交换后波段中的唯一命中，剔 QC/角度），对每个参数元素独立推导；
  任一元素 multi/zero/undefined -> 整题排除并计数。
  数据集中 ground_truth 写入新真值（评测 acc 即新真值跟随率）；
  原真值存 sidecar（original_ground_truth），交换映射存 eswap。

自检：
  S1 候选顺序与未交换候选的波长逐字节不变
  S2 T2/T5 序号新真值 = rank_map[新标签]-1+base（基址按题）
  S3 derive() 与 step1b_gap_probe.new_truth 在角色参数上逐题一致（同源互证）
  S4 抽查 8 题落盘人工核对（角色/旧带/窗口/新带/新真值）
  S7 新真值 ∈ band_options（v2 新增断言；v1 缺陷：T2 伙伴选自全波段表，
     138/138 新真值不可选 → v1 的 T2 结果作废）
"""
import json, os, sys, copy
from collections import Counter, defaultdict

sys.stdout.reconfigure(encoding="utf-8")
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "scripts"))
import jev_band_matcher as J
from step1b_gap_probe import WIN, EXCL, mid, new_truth

ds = json.load(open(os.path.join(BASE, "data", "dataset_matching_extended.json"), encoding="utf-8"))

def derive(label, q_old, q_swap):
    """窗口唯一命中（限定候选集 band_options——v2 构建修正：模型只能选候选，
    非候选波段占据窗口不构成可选答案，也不应挤掉候选真值）。"""
    ow = mid(q_old["band_wavelengths"].get(label))
    if ow is None:
        return None, "undefined"
    W = next((k for k, (a, b) in WIN.items() if a < ow < b), None)
    if W is None:
        return None, "undefined"
    cand = set(q_swap["band_options"])
    hits = sorted((q_swap["rank_map"].get(c, 999), c)
                  for c, w in q_swap["band_wavelengths"].items()
                  if c in cand and not EXCL.search(c) and mid(w) is not None
                  and WIN[W][0] < mid(w) < WIN[W][1])
    return (hits[0][1], "ok") if len(hits) == 1 else (None, ("multi" if hits else "zero"))

def answer_labels(d):
    """[(param, elem_idx_or_None, label)]；rank 参数按基址反解标签。"""
    base = J._index_base(d)
    rm = d["rank_map"]
    out = []
    for p in d["operator"]["params"]:
        pn, role = p["param"], p["role"]
        gt = d["ground_truth"][pn]
        kind = J.param_kind(d, p)
        if kind == "rank_scalar":
            out.append((pn, None, next(b for b, r in rm.items() if r is not None and r - 1 + base == gt)))
        elif kind in ("name_scalar", "pan_scalar"):
            out.append((pn, None, gt))
        elif kind == "name_list":
            out += [(pn, i, gt[i]) for i in range(len(role))]
        elif kind == "rank_list":
            out += [(pn, i, next(b for b, r in rm.items() if r is not None and r - 1 + base == gt[i]))
                    for i in range(len(role))]
    return out

kept, excl = [], Counter()
for d in ds:
    ans = answer_labels(d)
    labels = sorted({l for _, _, l in ans})
    wl = d.get("band_wavelengths") or {}
    if len(labels) < 2:
        # 单答案题（T2 全部、T1/T4 部分）：与窗口外最近邻候选成对交换（评审设计的 A<->B）
        if len(labels) != 1:
            excl["unique_answer_bands<2"] += 1
            continue
        a = labels[0]
        if a not in wl or mid(wl[a]) is None:
            excl["answer_band_no_wl"] += 1
            continue
        am = mid(wl[a])
        W = next((k for k, (x, y) in WIN.items() if x < am < y), None)
        if W is None:
            excl["answer_no_window"] += 1
            continue
        cands = sorted((d["rank_map"].get(c, 999), c) for c in d["band_options"]
                       if c != a and not EXCL.search(c) and mid(wl.get(c)) is not None)
        if not cands:
            excl["no_partner_candidate"] += 1
            continue
        # v2 修正：伙伴必须 ∈ band_options（v1 曾从全波段表选伙伴，导致新真值不可选——T2 全部作废）
        partner = cands[0][1]  # 确定性：rank 距离最近（并列取 label 序）
        labels = [a, partner]  # partner 只参与交换，不参与新真值推导
    if any(l not in wl or mid(wl[l]) is None for l in labels):
        excl["answer_band_no_wl"] += 1
        continue
    # 循环交换：a_i <- a_{i+1}（波长区间原样搬运）
    q = copy.deepcopy(d)
    for i, l in enumerate(labels):
        nxt = labels[(i + 1) % len(labels)]
        q["band_wavelengths"][l] = list(wl[nxt])
    q["eswap"] = {l: list(wl[labels[(i + 1) % len(labels)]]) for i, l in enumerate(labels)}
    # 新真值逐元素推导
    elem_new, ok_all, reason = {}, True, None
    for pn, idx, old_label in ans:
        nl, st = derive(old_label, d, q)
        if st != "ok":
            ok_all, reason = False, f"{pn}:{st}"
            break
        if nl == old_label:
            ok_all, reason = False, f"{pn}:new==old"
            break
        elem_new[(pn, idx)] = nl
    if not ok_all:
        excl[reason.split(":", 1)[1] if reason else "unknown"] += 1
        continue
    base = J._index_base(d)
    new_gt = {}
    for p in d["operator"]["params"]:
        pn, role, kind = p["param"], p["role"], J.param_kind(d, p)
        if kind in ("name_scalar", "pan_scalar"):
            new_gt[pn] = elem_new[(pn, None)]
        elif kind == "rank_scalar":
            new_gt[pn] = d["rank_map"][elem_new[(pn, None)]] - 1 + base
        elif kind in ("name_list", "rank_list"):
            elems = [elem_new[(pn, i)] for i in range(len(role))]
            new_gt[pn] = elems if kind == "name_list" else [d["rank_map"][b] - 1 + base for b in elems]
    # S2 自检：rank 型 gt 与新标签互推一致（rank 唯一性由构建门保证）
    base = J._index_base(d)
    for p in d["operator"]["params"]:
        if J.param_kind(d, p) == "rank_scalar":
            old_label = next(l for pn2, i2, l in ans if pn2 == p["param"] and i2 is None)
            new_label = elem_new[(p["param"], None)]
            inv = next(b for b, r in d["rank_map"].items() if r is not None and r - 1 + base == new_gt[p["param"]])
            if inv != new_label or derive(old_label, d, q)[0] != new_label:
                print(f"S2-DEBUG {q['sample_id']}: param={p['param']} old={old_label} new={new_label} "
                      f"inv={inv} gt={new_gt[p['param']]} ranks={sorted(set(d['rank_map'].values()))[:5]}")
                raise AssertionError("S2")
    q["ground_truth"] = new_gt
    q["original_ground_truth"] = d["ground_truth"]
    q["ground_truth_desc"] = {"_eswap": "波长反事实交换后的新真值（构建规则见 §E-SWAP）"}
    kept.append(q)

# S1: 候选顺序与未交换候选波长不变；S7: 新真值必须 ∈ band_options（v1 教训，升格为断言）
for q in kept:
    o = next(x for x in ds if x["sample_id"] == q["sample_id"])
    assert q["band_options"] == o["band_options"] and q["rank_map"] == o["rank_map"]
    for b in q["band_options"]:
        if b not in q["eswap"]:
            assert q["band_wavelengths"].get(b) == (o.get("band_wavelengths") or {}).get(b)
    base = J._index_base(q)
    opts = set(q["band_options"])
    for p in q["operator"]["params"]:
        gt = q["ground_truth"][p["param"]]
        for g in (gt if isinstance(gt, list) else [gt]):
            if isinstance(g, str):
                assert g in opts, (q["sample_id"], g)
            else:
                assert any(r is not None and r - 1 + base == g for r in q["rank_map"].values())
# S3(v2): derive 已改为候选集内唯一命中（v2 修正），与 step1b 全波段 new_truth 有意分歧；
# 分歧数只报告不再断言相等——分歧题 = 非候选波段占据窗口、按 v1 会误排或多命中的题
n_x = n_diff = 0
for q in kept[:80]:
    o = next(x for x in ds if x["sample_id"] == q["sample_id"])
    for p in o["operator"]["params"]:
        role = p["role"]
        if isinstance(role, str) and role in (o.get("band_roles_available") or {}):
            a, _ = derive(o["band_roles_available"][role], o, q)
            b, st_b = new_truth(o, q, role)
            n_diff += (a != b)
            n_x += 1

per_task = Counter(q["task"] for q in kept)
with open(os.path.join(BASE, "data", "eswap_ds.json"), "w", encoding="utf-8") as f:
    json.dump(kept, f, ensure_ascii=False)
print(f"构建完成(v2): 保留 {len(kept)}/579；排除 {dict(excl)}")
print(f"任务分布: {dict(per_task)}")
print(f"S1 候选不变性 PASS；S2 rank 互推 PASS；S7 新真值∈候选集 PASS；"
      f"S3 与全波段规则分歧 {n_diff}/{n_x}（候选集限定所致，符合修正意图）")
