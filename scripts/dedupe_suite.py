#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""去重重建 suite：内容哈希去重（变体重叠+教师逐模式写行+转换器展开 三层重复一次清）。
- 按 (mode, state+questions 内容哈希) 去重，教师标签取组内首个非错误结果
- 输出: data/distill/suite_{hard,soft}_{train,val}_dedup.jsonl + dedup_stats.json
"""
import json, sys, os, hashlib
sys.stdout.reconfigure(encoding='utf-8')
PROJ = r'E:\01_documents\Tencent\Wechat\xwechat_files\wxid_3pi5yps28df622_49fb\msg\file\2026-10\remote-sensing-operator-band-matching'
os.chdir(PROJ)
sys.path.insert(0, os.path.join(PROJ, 'scripts'))
import jev_band_matcher as J

def content_key(state, questions):
    return hashlib.sha256(json.dumps(
        {'s': state, 'q': questions}, sort_keys=True, ensure_ascii=False)
        .encode('utf-8')).hexdigest()

def process(side):
    # 1) 按 sample_id 分组收集（合并重复行的教师结果）
    groups: dict[str, dict] = {}
    for l in open(f'data/distill/{side}_uniq_labeled.jsonl', encoding='utf-8'):
        if not l.strip():
            continue
        r = json.loads(l)
        sid = r['sample_id']
        g = groups.setdefault(sid, {'rec': r, 'teachers': {}})
        for t in r.get('teacher', []):
            if t.get('error'):
                continue
            g['teachers'].setdefault(t['mode'], t)
    # 2) 每唯一样本 × 每模式渲染 + 内容去重
    seen: dict[str, str] = {}
    out = {'hard': [], 'soft': []}
    n_param_hard = n_param_soft = 0
    for sid, g in groups.items():
        r = g['rec']
        for mode in ['with_wavelength', 'labels_only']:
            use_wl = (mode == 'with_wavelength')
            state = J.build_state_ext(r, use_wl=use_wl)
            questions = J.build_questions_ext(r, use_wl=use_wl)
            key = content_key(state, questions)
            if key in seen:
                continue
            seen[key] = sid
            teacher_t = (g['teachers'].get(mode) or {}).get('answers') or {}
            hard_q, soft_q, soft_complete = {}, {}, True
            for qk, qv in questions.items():
                base, _, idx = qk.partition('::')
                gtv = r['ground_truth'].get(base)
                if isinstance(gtv, list):
                    gold = str(gtv[int(idx)]) if int(idx) < len(gtv) else None
                elif isinstance(gtv, int):
                    gold = str(gtv)
                else:
                    gold = gtv
                if gold is None:
                    soft_complete = False; break
                hard_q[qk] = {'type': 'choice', 'instructions': qv['instructions'],
                              'criteria': qv['criteria'], 'label': gold, 'src': 'oge_distill'}
                a = teacher_t.get(qk) or {}
                probs = a.get('probabilities') or {}
                if probs and a.get('choice') is not None:
                    soft_q[qk] = dict(hard_q[qk])
                    soft_q[qk]['target'] = {k: float(v) for k, v in probs.items()}
                else:
                    soft_complete = False
            if not hard_q:
                continue
            n_param_hard += len(hard_q)
            out['hard'].append(json.dumps({'state': state, 'questions': hard_q}, ensure_ascii=False))
            if soft_complete and soft_q:
                n_param_soft += len(soft_q)
                out['soft'].append(json.dumps({'state': state, 'questions': soft_q}, ensure_ascii=False))
    return out, n_param_hard, n_param_soft, len(seen)

stats = {}
for side in ['train', 'val']:
    res, nph, nps, nuniq = process(side)
    for kind in ['hard', 'soft']:
        with open(f'data/distill/suite_{kind}_{side}_dedup.jsonl', 'w', encoding='utf-8') as f:
            f.write('\n'.join(res[kind]) + ('\n' if res[kind] else ''))
    stats[side] = {'unique_samples': nuniq, 'hard_records': len(res['hard']),
                   'soft_records': len(res['soft']), 'param_hard': nph, 'param_soft': nps}
    print(f"{side}: 唯一样本 {nuniq} | hard 记录 {len(res['hard'])}（参数位 {nph}）| soft 记录 {len(res['soft'])}（参数位 {nps}）")

json.dump(stats, open('data/distill/dedup_stats.json', 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1)
print('已写 dedup_stats.json')
