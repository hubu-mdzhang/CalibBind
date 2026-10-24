#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建单一事实来源账本（long format）。

一行 = 一个 (question, run, mode)，字段固定：
  qid, product, family, task, run, fold, mode,
  n_params, n_elems, ok_e2e, f_param, f_elem, ok_lenient,
  seen_in_train, conf_mean, pred_json

所有下游表格只能从 ledger.jsonl 生成（make_report.py），禁止手工转录。
"""
from __future__ import annotations
import json, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
D = HERE.parent
sys.path.insert(0, str(HERE))

WIN = {'大气校正': (400, 460), '蓝': (450, 520), '绿': (520, 600), '红': (620, 700),
       '近红外': (790, 920), '短波红外1': (1550, 1750), '短波红外2': (2080, 2350),
       '热红外': (10600, 12500)}
EXCL = re.compile(r'qa|quality|state|raz|szen|vzen|azimuth|angle|day_of_year|cloud|shadow|'
                  r'snow|ice|water_mask|uncertaint|brdf|view|solar|pixel', re.I)


def load_jsonl(p):
    return [json.loads(l) for l in open(p, encoding='utf-8') if l.strip()]


def load_any(p):
    try:
        d = json.load(open(p, encoding='utf-8'))
        return d.get('rows') if isinstance(d, dict) and 'rows' in d else d
    except Exception:
        return load_jsonl(p)


def label_of(s, val, param):
    if val is None:
        return None
    if isinstance(val, int) or (isinstance(val, str) and val.lstrip('-').isdigit()):
        n = int(val)
        want = n + 1 if param == 'bandIndex' else n
        for lab, rk in (s.get('rank_map') or {}).items():
            if rk == want:
                return lab
        return None
    return str(val)


def legal_set(s, role):
    if role == '全色':
        return list(s.get('pan_bands') or [])
    wl = s.get('band_wavelengths') or {}
    pan = set(s.get('pan_bands') or [])
    a, b = WIN.get(role, (0, 0))
    out = []
    for c in s.get('band_options') or []:
        if c in pan or EXCL.search(c):
            continue
        w = wl.get(c)
        if w and w[0] is not None and a <= (w[0] + w[1]) / 2 <= b:
            out.append(c)
    return out


def family(name):
    F = {'LT05_L1TP_C02_T1': 'Landsat', 'LC08_C02_L1': 'Landsat', 'LC08_C02_L2': 'Landsat',
         'LC08_L1T': 'Landsat', 'LC09_C02_L1': 'Landsat', 'LC09_C02_L2': 'Landsat',
         'LC_Ref': 'Landsat', 'LC08_L1TP_Hubei1420_sr': 'Landsat',
         'HiGLASS_SR_Landsat_30m': 'Landsat',
         'S2_MSIL1C': 'Sentinel', 'S2_MSIL2A': 'Sentinel', 'S2A_MSIL1C': 'Sentinel',
         'S2B_MSIL1C': 'Sentinel', 'LJ4I_HSI_17B': '珞珈', 'LJ4I_HSI_5B': '珞珈',
         'LJ3II_L1B_Fusion': '珞珈', 'LJ4I_HSI_32B': '珞珈'}
    return F.get(name, '其他')


def main():
    ext = {r['sample_id']: r for r in
           json.load(open(D / 'data/dataset_matching_extended.json', encoding='utf-8'))}
    train_prods = {json.loads(l)['product_name'] for l in
                   open(D / 'data/distill/train_uniq.jsonl', encoding='utf-8') if l.strip()}

    SOURCES = [
        ('kev9b_zs', 'results_v2/eval_kev9b.jsonl', 'full'),
        ('kev4b_zs', 'results_v2/eval_kev4b.jsonl', 'full'),
        ('nimble_zs', 'results_v2/eval_nimble.jsonl', 'full'),
        ('semif_zs', 'results_v2/eval_semif.jsonl', 'full'),
        ('von_zs', 'results_v2/eval_von.jsonl', 'full'),
        ('qwen4b_zs', 'results_v2/eval_qwen4b.jsonl', 'full'),
        ('qwen9b_zs', 'results_v2/eval_qwen9b.jsonl', 'full'),
        ('A_full', 'results_v2/eval_v2_armA_hard.jsonl', 'full'),
        ('B_full', 'results_v2/eval_v2_armB_soft.jsonl', 'full'),
        ('C_full', 'results_v2/eval_v2_armC_brier.jsonl', 'full'),
        ('A4b_full', 'results_v2/eval_v2_armA_4b.jsonl', 'full'),
        ('A_relabelX', 'results_v2/eval_relabelA7_smoke.jsonl', 'full'),
    ]
    for f, ap in [('Sentinel', 'A'), ('Sentinel', 'B'), ('Landsat', 'A'), ('Landsat', 'B'),
                  ('珞珈', 'A'), ('珞珈', 'B'), ('其他', 'A'), ('其他', 'B')]:
        p = D / f'results_v2/lfo/eval_lfo_{f}_{ap}_smoke.jsonl'
        if p.exists():
            SOURCES.append((f'{ap}_lfo_{f}', f'results_v2/lfo/eval_lfo_{f}_{ap}_smoke.jsonl', f))

    out = []
    for run, rel, fold in SOURCES:
        p = D / rel
        if not p.exists():
            print(f'[skip] {rel}')
            continue
        for r in load_any(p):
            s = ext.get(r.get('sample_id'))
            if not s or r.get('error'):
                continue
            details = r.get('details') or []
            n_elem = len(details)
            n_param = r.get('total') or 0
            if not n_param:
                continue
            ok_e2e = 1 if (r.get('correct') == n_param and n_param > 0) else 0
            f_param = r['correct'] / n_param
            f_elem = (sum(1 for d in details if d.get('ok')) / n_elem) if n_elem else 0.0
            # 宽松：逐元素，若该角色合法集>1 则接受任一
            roles = {v: k for k, v in (s.get('band_roles_available') or {}).items()}
            for lab in (s.get('pan_bands') or []):
                roles[lab] = '全色'
            ok_len = 1
            for d in details:
                tl = label_of(s, d.get('truth'), d.get('param'))
                pl = label_of(s, d.get('pred'), d.get('param'))
                L = legal_set(s, roles.get(tl)) if roles.get(tl) else []
                good = bool(d.get('ok')) if len(L) <= 1 else (pl in L)
                if not good:
                    ok_len = 0
                    break
            conf = [max((d.get('probabilities') or {}).values())
                    for d in details if d.get('probabilities')]
            out.append({
                'qid': r['sample_id'], 'product': s['product_name'],
                'family': family(s['product_name']), 'task': r.get('task'),
                'run': run, 'fold': fold, 'mode': r.get('mode'),
                'n_params': n_param, 'n_elems': n_elem,
                'ok_e2e': ok_e2e, 'f_param': round(f_param, 4), 'f_elem': round(f_elem, 4),
                'ok_lenient': ok_len,
                'seen_in_train': 1 if s['product_name'] in train_prods else 0,
                'conf_mean': round(sum(conf) / len(conf), 4) if conf else None,
            })
    outp = D / 'results_v2/ledger.jsonl'
    outp.write_text('\n'.join(json.dumps(x, ensure_ascii=False) for x in out) + '\n',
                    encoding='utf-8')
    print(f'ledger rows={len(out)} -> {outp}')
    import collections
    print('by run:', dict(collections.Counter(x['run'] for x in out)))


if __name__ == '__main__':
    main()
