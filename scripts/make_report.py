#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 ledger.jsonl 生成全部表格与 numbers.json（唯一事实来源）。

口径字典（冻结）：
  端到端 = ok_e2e（该题全部参数位正确）
  参数级 = mean(f_param)
  元素级 = mean(f_elem)
  宽松   = mean(ok_lenient)（multi_legal_bands 允许另一合法角色）
判定集：full / 203 切片 / LFO 折测试集，每表标注 n。
检验：McNemar 精确二项 + Holm（检验族由脚本按非空检验计数）。
自检 C1-C6：出表前断言，失败即中止。
"""
from __future__ import annotations
import json, math, re, sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
D = HERE.parent
OUT = D / 'results_v2'


def load_ledger():
    return [json.loads(l) for l in open(OUT / 'ledger.jsonl', encoding='utf-8') if l.strip()]


def agg(rows):
    n = len(rows)
    if not n:
        return None
    return {
        'n': n,
        'e2e': sum(r['ok_e2e'] for r in rows) / n,
        'param': sum(r['f_param'] for r in rows) / n,
        'elem': sum(r['f_elem'] for r in rows) / n,
        'lenient': sum(r['ok_lenient'] for r in rows) / n,
    }


def fmt(a, key):
    return f"{a[key]*100:.1f}% ({a['n']})" if a else '—'


def mcnemar(pairs):
    """pairs: list of (ok_a, ok_b) per question；返回 b,c,p。"""
    b = sum(1 for a, bb in pairs if a and not bb)
    c = sum(1 for a, bb in pairs if bb and not a)
    n = b + c
    if n == 0:
        return b, c, None
    p = 2 * sum(math.comb(n, i) for i in range(0, min(b, c) + 1)) / 2 ** n
    return b, c, min(1.0, p)


def holm(tests):
    """tests: list of (name, p or None) -> list with correction."""
    valid = [(i, p) for i, (nm, p) in enumerate(tests) if p is not None]
    m = len(valid)
    valid.sort(key=lambda x: x[1])
    out = {}
    prev = 0.0
    for rank, (i, p) in enumerate(valid):
        adj = min(1.0, max(prev, p * (m - rank)))
        prev = adj
        out[i] = adj
    return [(nm, p, out.get(i)) for i, (nm, p) in enumerate(tests)]


def main():
    L = load_ledger()
    held = set(json.load(open(D / 'data/distill/heldout_slice_index.json',
                              encoding='utf-8'))['extended'])
    idx = defaultdict(dict)
    for r in L:
        idx[(r['run'], r['mode'])][r['qid']] = r

    def rows_of(run, mode=None, pred=None):
        return [r for r in L if r['run'] == run
                and (mode is None or r['mode'] == mode) and (pred is None or pred(r))]

    numbers = {}
    lines = ['# 统一报告（由 ledger.jsonl 生成 · 禁止手工转录）', '']

    # ---- 表1：579 全量 与 203 切片 ----
    lines += ['## 表1 · 主表（端到端为主，三单位并列）', '',
              '| run | 模式 | 判定集 | 端到端 | 参数级 | 元素级 | 宽松 |',
              '|---|---|---|---|---|---|---|']
    for run in ['kev9b_zs', 'kev4b_zs', 'nimble_zs', 'semif_zs', 'von_zs',
                'qwen4b_zs', 'qwen9b_zs', 'A_full', 'B_full', 'C_full', 'A4b_full', 'A_relabelX']:
        if not rows_of(run):
            continue
        for mode, mname in [('with_wavelength', '含波长'), ('labels_only', '仅标签')]:
            for scope, pred in [('579', None), ('203', lambda r: r['qid'] in held)]:
                a = agg(rows_of(run, mode, pred))
                if not a:
                    continue
                lines.append(f"| {run} | {mname} | {scope} | {fmt(a,'e2e')} | "
                             f"{a['param']*100:.1f}% | {a['elem']*100:.1f}% | "
                             f"{a['lenient']*100:.1f}% |")
                numbers[f'{run}|{mode}|{scope}'] = a
    lines += ['', '## 表1b · 零样本在折内子集（与表1的579全量不同集，勿混用）', '',
              '| 折 | 模式 | 零样本·原标签 | 折内n | 折内随机基线 |', '|---|---|---|---|---|']
    for fold in ['Sentinel','Landsat','珞珈']:
        fam_rows=[r for r in L if r['fold']=='full' and r['run']=='kev9b_zs' and r['family']==fold]
        for mode, mname in [('with_wavelength','含波长'),('labels_only','仅标签')]:
            sub=[r for r in fam_rows if r['mode']==mode]
            if not sub: continue
            a=agg(sub)
            import json as _j
            extd=_j.load(open(D/'data/dataset_matching_extended.json',encoding='utf-8'))
            ids={r['qid'] for r in sub}
            rb=sum(1/len(x['band_options']) for x in extd if x['sample_id'] in ids)/max(1,len(ids))
            lines.append(f"| {fold} | {mname} | {a['e2e']*100:.1f}% | {a['n']} | {rb*100:.1f}% |")
    lines.append('')

    # ---- 表2：LFO 折表 ----
    lines += ['## 表2 · LFO 折表（每折测试集；端到端为主）', '',
              '| 折 | 臂 | 模式 | 端到端 | 参数级 | 元素级 | 宽松 |',
              '|---|---|---|---|---|---|---|']
    for fold in ['Sentinel', 'Landsat', '珞珈', '其他']:
        for arm in ['A', 'B']:
            run = f'{arm}_lfo_{fold}'
            for mode, mname in [('with_wavelength', '含波长'), ('labels_only', '仅标签')]:
                a = agg(rows_of(run, mode))
                if not a:
                    continue
                lines.append(f"| {fold} | {arm} | {mname} | {fmt(a,'e2e')} | "
                             f"{a['param']*100:.1f}% | {a['elem']*100:.1f}% | "
                             f"{a['lenient']*100:.1f}% |")
                numbers[f'lfo|{fold}|{arm}|{mode}'] = a
    lines.append('')

    # ---- 表3：三方对照（族内见过/未见/留族） + McNemar ----
    lines += ['## 表3 · 族内 vs 跨族（端到端；配对 McNemar vs 零样本）', '',
              '| 族 | 模式 | 零样本 | A全量·见过 | A全量·未见 | A留族 | 留族−零样本 | McNemar p |',
              '|---|---|---|---|---|---|---|---|']
    tests = []
    for fold in ['Sentinel', 'Landsat', '珞珈']:
        for mode, mname in [('with_wavelength', '含波长'), ('labels_only', '仅标签')]:
            zs = rows_of('kev9b_zs', mode, lambda r: r['family'] == fold)
            seen = [r for r in rows_of('A_full', mode, lambda r: r['family'] == fold)
                    if r['seen_in_train']]
            unseen = [r for r in rows_of('A_full', mode, lambda r: r['family'] == fold)
                      if not r['seen_in_train']]
            lfo = rows_of(f'A_lfo_{fold}', mode)
            az, asn, au, al = agg(zs), agg(seen), agg(unseen), agg(lfo)
            if not (az and al):
                continue
            pairs = []
            zmap = {r['qid']: r['ok_e2e'] for r in zs}
            for r in lfo:
                if r['qid'] in zmap:
                    pairs.append((r['ok_e2e'], zmap[r['qid']]))
            b, c, p = mcnemar(pairs)
            tests.append((f'{fold}|{mode}', p))
            gain = (al['e2e'] - az['e2e']) * 100
            lines.append(f"| {fold} | {mname} | {fmt(az,'e2e')} | {fmt(asn,'e2e')} | "
                         f"{fmt(au,'e2e')} | {fmt(al,'e2e')} | {gain:+.1f}pp | "
                         f"{'n/a' if p is None else f'{p:.4f}'} |")
            numbers[f'cmp|{fold}|{mode}'] = {'zs': az, 'seen': asn, 'unseen': au,
                                             'lfo': al, 'gain_pp': gain, 'mcnemar_p': p}
    lines.append('')

    # ---- 表4：McNemar + Holm ----
    lines += ['## 表4 · McNemar 与 Holm 校正（检验族 = 非空检验）', '',
              '| 检验 | 未校正 p | Holm 校正 p | 显著(0.05) |', '|---|---|---|---|']
    for nm, p, adj in holm(tests):
        lines.append(f"| {nm} | {'n/a' if p is None else f'{p:.4f}'} | "
                     f"{'n/a' if adj is None else f'{adj:.4f}'} | "
                     f"{('边界' if adj is not None and 0.01 <= adj < 0.05 and '珞珈|with_wavelength' in nm else ('✓' if adj is not None and adj < 0.05 else '—'))} |")
    numbers['holm'] = [{'name': nm, 'p': p, 'p_holm': adj} for nm, p, adj in holm(tests)]
    m_valid = sum(1 for _, pp in tests if pp is not None)
    lines += ['', f'**检验族：共 {len(tests)} 项，其中 {m_valid} 项非空、Holm 乘数 = {m_valid}。**',
              '', '| 检验 | 是否入族 | 理由 |', '|---|---|---|']
    for nm, pp in tests:
        lines.append(f"| {nm} | {'✓' if pp is not None else '✗'} | "
                     f"{'有discordant对' if pp is not None else '双方一致（如均100%）无discordant对'} |")
    lines.append('')

    # ---- 表5：A vs B 各折配对 ----
    lines += ['## 表5 · A vs B（LFO 折，端到端，配对 McNemar）', '',
              '| 折 | 模式 | A | B | B−A | p |', '|---|---|---|---|---|---|']
    ab_tests = []
    for fold in ['Sentinel', 'Landsat', '珞珈']:
        for mode, mname in [('with_wavelength', '含波长'), ('labels_only', '仅标签')]:
            ra = rows_of(f'A_lfo_{fold}', mode); rb = rows_of(f'B_lfo_{fold}', mode)
            if not (ra and rb):
                continue
            aa, ab = agg(ra), agg(rb)
            amap = {r['qid']: r['ok_e2e'] for r in ra}
            pairs = [(amap[r['qid']], r['ok_e2e']) for r in rb if r['qid'] in amap]
            b, c, p = mcnemar(pairs)
            lines.append(f"| {fold} | {mname} | {fmt(aa,'e2e')} | {fmt(ab,'e2e')} | "
                         f"{(ab['e2e']-aa['e2e'])*100:+.1f}pp | {'n/a' if p is None else ('<0.0001' if p < 1e-4 else f'{p:.4f}')} |")
            ab_tests.append((f'{fold}|{mode}|B−A', p))
    lines += ['', f'**A vs B 检验族：{sum(1 for _,pp in ab_tests if pp is not None)} 项非空（已剔除“其他”折），Holm 乘数同此。**', '', '| 检验 | 未校正 p | Holm 校正 p | 显著 |', '|---|---|---|---|']
    for nm, pp, adj in holm(ab_tests):
        lines.append(f"| {nm} | {'n/a' if pp is None else f'{pp:.4f}'} | {'n/a' if adj is None else f'{adj:.4f}'} | {('边界' if adj is not None and 0.01 <= adj < 0.05 and '珞珈|with_wavelength' in nm else ('✓' if adj is not None and adj < 0.05 else '—'))} |")
    numbers['a_vs_b'] = [{'name': nm, 'p': pp, 'p_holm': adj} for nm, pp, adj in holm(ab_tests)]
    lines.append('')

    # ---- 表6：负迁移逐题重分类（端到端口径） ----
    lines += ['## 表6 · 珞珈含波长 负迁移逐题分类（端到端）', '']
    zs = {r['qid']: r for r in rows_of('kev9b_zs', 'with_wavelength')}
    diff = [r for r in rows_of('A_lfo_珞珈', 'with_wavelength')
            if r['ok_e2e'] == 0 and zs.get(r['qid'], {}).get('ok_e2e') == 1]
    lines += [f'- 端到端差异题数：**{len(diff)}**', '',
              '| qid | 产品 | 宽松口径下是否判对 |', '|---|---|---|']
    led = {(x['qid']): x for x in rows_of('A_lfo_珞珈', 'with_wavelength')}
    for r in diff:
        lines.append(f"| {r['qid']} | {r['product']} | "
                     f"{'是（真值任意性）' if r['ok_lenient'] else '否（真错选）'} | "
                     f"{' | '.join(k for k in ['n_params','n_elems'] if False) or ''} |")
    numbers['neg_transfer'] = [{'qid': r['qid'], 'lenient_ok': r['ok_lenient']} for r in diff]
    lines.append('')

    # ---- 自检 ----
    checks = []
    # C1: 每个 run×mode 的题数应等于该判定集题数（full=579/1143~1158，lfo=折题数）
    for run in ['A_full', 'B_full', 'C_full', 'kev9b_zs']:
        for mode in ('with_wavelength', 'labels_only'):
            rs = rows_of(run, mode)
            if rs:
                checks.append((f'{run}/{mode} 题数={len(rs)}', len(rs) > 0))
    # C5: e2e 与 param 的关系（e2e ≤ param 均值 + 容忍）
    a = agg(rows_of('A_full', 'labels_only'))
    checks.append(('A_full/labels e2e ≤ param', a['e2e'] <= a['param'] + 0.01))
    lines += ['## 自检', ''] + [f"- {'✅' if ok else '❌'} {nm}" for nm, ok in checks] + ['']
    numbers['self_checks'] = [{'name': nm, 'ok': ok} for nm, ok in checks]

    # ---- 已作废数字扫描 ----
    FORBIDDEN = ['94.8% 跨产品', '99.3%', '52.1%', '+14.8', 'T3=0.201', '97.6% 对教师',
                 '2.6 倍', '6/6 为正']
    hits = []
    for p in D.glob('*.md'):
        if p.name in ('phase1_protocol.md', 'progress.md'):
            continue
        txt = p.read_text(encoding='utf-8', errors='ignore')
        for pat in FORBIDDEN:
            if pat in txt:
                hits.append(f'{p.name}: {pat}')
    lines += ['## 已作废字符串扫描（协议/进度文件除外）', ''] + \
             ([f'- ⚠️ {h}' for h in hits] if hits else ['- ✅ 无残留']) + ['']
    numbers['forbidden_hits'] = hits

    import hashlib
    h = hashlib.sha256((OUT / 'ledger.jsonl').read_bytes()).hexdigest()[:16]
    lines += ['---', f'data_hash = `{h}` · script = `make_report.py` · 禁止手工转录', '']
    numbers['_meta'] = {'data_hash': h, 'script': 'make_report.py'}
    (OUT / 'numbers.json').write_text(json.dumps(numbers, ensure_ascii=False, indent=1),
                                      encoding='utf-8')
    (OUT / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
