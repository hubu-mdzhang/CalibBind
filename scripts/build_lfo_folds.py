#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建 LFO 折数据（phase1_protocol.md 折定义存档版）：
每折输出 {data}/lfo/{fold}/{{train,soft}.jsonl, test_ext.json}
train/soft = train_uniq(_labeled) 剔除该族产品行；test = 该族产品 579 行。
"""
import json, sys
from pathlib import Path
HERE=Path(__file__).resolve().parent; sys.path.insert(0,str(HERE))
D=HERE.parent/'data'; OUT=D/'lfo'
FAM={'S2_MSIL1C':'Sentinel','S2A_MSIL1C':'Sentinel','S2B_MSIL1C':'Sentinel','S2_MSIL2A':'Sentinel',
 'LT05_L1TP_C02_T1':'Landsat','LC08_C02_L1':'Landsat','LC08_C02_L2':'Landsat','LC08_L1T':'Landsat',
 'LC09_C02_L1':'Landsat','LC09_C02_L2':'Landsat','LC_Ref':'Landsat',
 'LJ4I_HSI_17B':'珞珈','LJ4I_HSI_5B':'珞珈','LJ3II_L1B_Fusion':'珞珈','LJ4I_HSI_32B':'珞珈'}
def fam(n):
    return FAM.get(n, '其他')
ext=json.load(open(D/'dataset_matching_extended.json',encoding='utf-8'))
tr=[json.loads(l) for l in open(D/'distill'/'train_uniq.jsonl',encoding='utf-8') if l.strip()]
trl=[json.loads(l) for l in open(D/'distill'/'train_uniq_labeled.jsonl',encoding='utf-8') if l.strip()]
for fold in ['Sentinel','珞珈','其他']:
    (OUT/fold).mkdir(parents=True,exist_ok=True)
    tr_f=[r for r in tr if fam(r['product_name'])!=fold]
    trl_f=[r for r in trl if fam(r['product_name'])!=fold]
    te=[r for r in ext if fam(r['product_name'])==fold]
    (OUT/fold/'train.jsonl').write_text('\n'.join(json.dumps(r,ensure_ascii=False) for r in tr_f)+'\n',encoding='utf-8')
    (OUT/fold/'soft.jsonl').write_text('\n'.join(json.dumps(r,ensure_ascii=False) for r in trl_f)+'\n',encoding='utf-8')
    (OUT/fold/'test_ext.json').write_text(json.dumps(te,ensure_ascii=False),encoding='utf-8')
    print(fold,'train',len(tr_f),'soft_lines',len(trl_f),'test_rows',len(te))
print('Landsat 折 = 现有切片数字，无需重训')
