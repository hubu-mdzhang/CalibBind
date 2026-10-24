#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""共享指标库（2026-10-23 · 修正 AUROC 秩计算 bug）。

此前实现 `start = sum(1 for x in allv if x < v)` 统计的是**不同取值的个数**，
而非**样本个数**；在大量并列（如分歧度 0.0）时会低估秩，甚至产出负 AUROC。
本库用标准 Mann-Whitney（并列取平均秩、按样本计数）实现，全项目统一调用。
"""
import math


def auroc(pairs, min_class=20):
    """pairs: [(score, positive_bool)]。返回 AUROC 或 None（小类 < min_class 时）。"""
    pos = [c for c, ok in pairs if ok]
    neg = [c for c, ok in pairs if not ok]
    if not pos or not neg:
        return None
    if min(len(pos), len(neg)) < min_class:
        return None
    items = sorted([(c, 1) for c in pos] + [(c, 0) for c in neg])
    n = len(items)
    rank_sum = 0.0
    i = 0
    while i < n:
        j = i
        while j + 1 < n and items[j + 1][0] == items[i][0]:
            j += 1
        avg = ((i + 1) + (j + 1)) / 2          # 并列平均秩（1 起）
        for k in range(i, j + 1):
            if items[k][1] == 1:
                rank_sum += avg
        i = j + 1
    u = rank_sum - len(pos) * (len(pos) + 1) / 2
    return u / (len(pos) * len(neg))


def auroc_forced(pairs):
    """不做小类门槛的 AUROC（仅供内部核对，正文不引用）。"""
    return auroc(pairs, min_class=1)


def ece(pairs):
    n = len(pairs)
    if not n:
        return None
    bins = [[] for _ in range(10)]
    for c, ok in pairs:
        bins[min(9, max(0, int(c * 10)))].append(ok)
    return sum(len(b) / n * abs(sum(b) / len(b) - (i + 0.5) / 10)
               for i, b in enumerate(bins) if b)


def ladder(pairs, taus=(0.5, 0.6, 0.7, 0.8, 0.9, 0.95)):
    n = len(pairs)
    out = {}
    for t in taus:
        keep = [ok for c, ok in pairs if c >= t]
        out[t] = (len(keep) / n if n else 0,
                  sum(keep) / len(keep) if keep else None)
    return out


def mcnemar_exact(pairs):
    b = sum(1 for a, bb in pairs if a and not bb)
    c = sum(1 for a, bb in pairs if bb and not a)
    n = b + c
    if n == 0:
        return b, c, None
    p = 2 * sum(math.comb(n, i) for i in range(min(b, c) + 1)) / 2 ** n
    return b, c, min(1.0, p)


def boot_ci(pairs, fn, iters=10000, seed=7):
    import random
    rng = random.Random(seed)
    vals = []
    for _ in range(iters):
        samp = [pairs[rng.randrange(len(pairs))] for _ in range(len(pairs))]
        v = fn(samp)
        if v is not None:
            vals.append(v)
    if len(vals) < 100:
        return None
    vals.sort()
    return vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals)) - 1]
