# 统一 Brier/NLL 复算对账 + 并列感知 AURC（§3.6 裁定执行 · 2026-10-24）

脚本 sha=b6915246144d；口径：参数槽位宏平均；p 下限 1e-9；缺失分布不伪造、计数披露。

## 一、Brier/NLL 对账（已发布值 vs 统一口径复算）

| 项 | 复算 Brier | 复算 NLL | 对账 | 有效槽位披露 |
|---|---|---|---|---|
| T4b|teacher|wl | Brier 0.1122 | NLL 0.1931 | **口径更正**（原 0.0613/0.1931） | 槽位 1014（缺分布 0/键失配 0/裁剪 0） 题 579 |
| T4b|teacher|lo | Brier 0.4743 | NLL 0.8506 | **口径更正**（原 0.2066/0.8506） | 槽位 1014（缺分布 0/键失配 0/裁剪 0） 题 579 |
| T4b|kev9b|wl | Brier 0.2285 | NLL 0.4983 | **口径更正**（原 0.1354/0.4983） | 槽位 1014（缺分布 0/键失配 0/裁剪 0） 题 579 |
| T4b|kev9b|lo | Brier 0.6656 | NLL 1.3195 | **口径更正**（原 0.2262/1.3195） | 槽位 1014（缺分布 0/键失配 0/裁剪 0） 题 579 |
| T4b|kev4b|wl | Brier 0.2389 | NLL 0.4956 | **口径更正**（原 0.142/0.4956） | 槽位 1014（缺分布 0/键失配 0/裁剪 0） 题 579 |
| T4b|kev4b|lo | Brier 0.6594 | NLL 1.3227 | **口径更正**（原 0.2578/1.3227） | 槽位 1014（缺分布 0/键失配 0/裁剪 0） 题 579 |
| T4b|nimble|wl | Brier 0.6286 | NLL 1.2655 | **口径更正**（原 0.2047/1.2655） | 槽位 1014（缺分布 0/键失配 0/裁剪 0） 题 579 |
| T4b|nimble|lo | Brier 0.6406 | NLL 1.2852 | **口径更正**（原 0.2052/1.2852） | 槽位 1014（缺分布 0/键失配 0/裁剪 0） 题 579 |
| T4b|semif|wl | Brier 0.5642 | NLL 1.1218 | **口径更正**（原 0.2159/1.1218） | 槽位 1014（缺分布 0/键失配 0/裁剪 0） 题 579 |
| T4b|semif|lo | Brier 0.5547 | NLL 1.0864 | **口径更正**（原 0.2161/1.0864） | 槽位 1014（缺分布 0/键失配 0/裁剪 0） 题 579 |
| T4b|von|wl | Brier 0.8047 | NLL 1.7356 | **口径更正**（原 0.3005/1.7356） | 槽位 1014（缺分布 0/键失配 0/裁剪 0） 题 579 |
| T4b|von|lo | Brier 0.8341 | NLL 1.8300 | **口径更正**（原 0.1345/1.83） | 槽位 1014（缺分布 0/键失配 0/裁剪 0） 题 579 |
| T5|A|wl | Brier 0.0042 | NLL 0.0086 | **口径更正**（原 0.0022/0.0086） | 槽位 1014（缺分布 0/键失配 0/裁剪 0） 题 579 |
| T6|A|wl | Brier 0.0116 | NLL 0.0236 | **口径更正**（原 0.006/0.0236） | 槽位 362（缺分布 0/键失配 0/裁剪 0） 题 203 |
| T5|A|lo | Brier 0.1495 | NLL 1.2646 | **口径更正**（原 0.0739/1.2646） | 槽位 1014（缺分布 0/键失配 0/裁剪 58） 题 579 |
| T6|A|lo | Brier 0.0881 | NLL 0.7532 | **口径更正**（原 0.0437/0.7532） | 槽位 362（缺分布 0/键失配 0/裁剪 12） 题 203 |
| T5|B|wl | Brier 0.0989 | NLL 0.1801 | **口径更正**（原 0.0633/0.1801） | 槽位 1014（缺分布 0/键失配 0/裁剪 0） 题 579 |
| T6|B|wl | Brier 0.0623 | NLL 0.1213 | **口径更正**（原 0.0387/0.1213） | 槽位 362（缺分布 0/键失配 0/裁剪 0） 题 203 |
| T5|B|lo | Brier 0.4456 | NLL 0.8216 | **口径更正**（原 0.1786/0.8216） | 槽位 1014（缺分布 0/键失配 0/裁剪 0） 题 579 |
| T6|B|lo | Brier 0.5391 | NLL 0.8637 | **口径更正**（原 0.2177/0.8697） | 槽位 362（缺分布 0/键失配 0/裁剪 0） 题 203 |
| T5|C|wl | Brier 0.0153 | NLL 0.0332 | **口径更正**（原 0.0074/0.0332） | 槽位 1014（缺分布 0/键失配 0/裁剪 0） 题 579 |
| T6|C|wl | Brier 0.0052 | NLL 0.0085 | **口径更正**（原 0.0025/0.0085） | 槽位 362（缺分布 0/键失配 0/裁剪 0） 题 203 |
| T5|C|lo | Brier 0.1326 | NLL 1.1045 | **口径更正**（原 0.0664/1.1045） | 槽位 1014（缺分布 0/键失配 0/裁剪 49） 题 579 |
| T6|C|lo | Brier 0.0607 | NLL 0.2712 | **口径更正**（原 0.0303/0.2712） | 槽位 362（缺分布 0/键失配 0/裁剪 3） 题 203 |
| T5|A4b|wl | Brier 0.0335 | NLL 0.0766 | **口径更正**（原 0.0159/0.0766） | 槽位 1014（缺分布 0/键失配 0/裁剪 0） 题 579 |
| T6|A4b|wl | Brier 0.0421 | NLL 0.1120 | **口径更正**（原 0.0193/0.112） | 槽位 362（缺分布 0/键失配 0/裁剪 0） 题 203 |
| T5|A4b|lo | Brier 0.2381 | NLL 1.3837 | **口径更正**（原 0.1121/1.3837） | 槽位 1014（缺分布 0/键失配 0/裁剪 54） 题 579 |
| T6|A4b|lo | Brier 0.3399 | NLL 1.3609 | **口径更正**（原 0.1547/1.3609） | 槽位 362（缺分布 0/键失配 0/裁剪 15） 题 203 |
| Sval|A|wl | Brier 0.0000 | NLL 0.0004 | 复现 ✓ | 槽位 340（缺分布 0/键失配 0/裁剪 0） 题 288 |
| Sval|A|lo | Brier 0.8262 | NLL 7.0609 | **口径更正**（原 0.4099/7.06） | 槽位 340（缺分布 0/键失配 0/裁剪 110） 题 288 |
| Sval|B|wl | Brier 0.0901 | NLL 0.1422 | **口径更正**（原 0.043/None） | 槽位 340（缺分布 0/键失配 0/裁剪 0） 题 288 |
| Sval|B|lo | Brier 0.5183 | NLL 0.9132 | **口径更正**（原 0.1567/0.91） | 槽位 340（缺分布 0/键失配 0/裁剪 0） 题 288 |
| Sval|C|wl | Brier 0.0702 | NLL 0.1413 | **口径更正**（原 0.0341/None） | 槽位 340（缺分布 0/键失配 0/裁剪 0） 题 288 |
| Sval|C|lo | Brier 0.7895 | NLL 7.8309 | **口径更正**（原 0.3945/7.83） | 槽位 340（缺分布 0/键失配 0/裁剪 126） 题 288 |

## 二、S2 珞珈折复现（luojia_metrics_restore 系题宏单位；同时给槽宏与题宏）

| 模型 | 槽宏 Brier/NLL | 题宏 Brier/NLL | 原值(题宏) | 判定(题宏对题宏) |
|---|---|---|---|---|
| 零样本 kev-9b | 0.0897 / 0.2470 | 0.0885 / 0.2407 | 0.089 / 0.241 | 复现 ✓ |
| A_lfo s0 | 0.2542 / 1.1241 | 0.2861 / 1.3986 | 0.286 / 1.399 | 复现 ✓ |
| A_lfo s1 | 0.0946 / 0.1632 | 0.1059 / 0.1889 | 0.106 / 0.189 | 复现 ✓ |
| A_lfo s2 | 0.0622 / 0.1466 | 0.0452 / 0.1095 | 0.045 / 0.110 | 复现 ✓ |

## 三、并列感知 AURC 重算（旧值 vs 新值；新算法与输入顺序无关）

| 项 | 旧 AURC | 新（并列感知） | 判定 |
|---|---|---|---|
| T7a|lo|A | 0.027 | 0.0437 | 顺序不变 ✓；旧值差 +0.0167 |
| T7a|lo|B | 0.332 | 0.3320 | 顺序不变 ✓；旧值差 -0.0000 |
| T7a|lo|C | 0.005 | 0.0100 | 顺序不变 ✓；旧值差 +0.0050 |
| T7a|lo|zs | 0.378 | 0.3785 | 顺序不变 ✓；旧值差 +0.0005 |
| T7a|wl|A | 0.0 | 0.0002 | 顺序不变 ✓；旧值差 +0.0002 |
| T7a|wl|B | 0.004 | 0.0038 | 顺序不变 ✓；旧值差 -0.0002 |
| T7a|wl|C | 0.0 | 0.0001 | 顺序不变 ✓；旧值差 +0.0001 |
| T7a|wl|zs | 0.004 | 0.0039 | 顺序不变 ✓；旧值差 -0.0001 |
| T7b|A_lfo | 0.545 | 0.4827 | 顺序不变 ✓；旧值差 -0.0623 |
| T7b|B_lfo | 0.654 | 0.6545 | 顺序不变 ✓；旧值差 +0.0005 |
| T7b|zs | 0.32 | 0.3204 | 顺序不变 ✓；旧值差 +0.0004 |

## 四、输入文件哈希

- teacher|wl: `E:\01_documents\Tencent\Wechat\xwechat_files\wxid_3pi5yps28df622_49fb\msg\file\2026-10\remote-sensing-operator-band-matching\data\jev_results_ext_with_wavelength.json` sha=ff595d0bfeaa
- teacher|lo: `E:\01_documents\Tencent\Wechat\xwechat_files\wxid_3pi5yps28df622_49fb\msg\file\2026-10\remote-sensing-operator-band-matching\data\jev_results_ext_labels_only.json` sha=adc07c1141a2
- kev9b: `E:\01_documents\Tencent\Wechat\xwechat_files\wxid_3pi5yps28df622_49fb\msg\file\2026-10\remote-sensing-operator-band-matching\results_v2\eval_kev9b.jsonl` sha=0e6d8ee4b71a
- kev4b: `E:\01_documents\Tencent\Wechat\xwechat_files\wxid_3pi5yps28df622_49fb\msg\file\2026-10\remote-sensing-operator-band-matching\results_v2\eval_kev4b.jsonl` sha=b8e0df540f4f
- nimble: `E:\01_documents\Tencent\Wechat\xwechat_files\wxid_3pi5yps28df622_49fb\msg\file\2026-10\remote-sensing-operator-band-matching\results_v2\eval_nimble.jsonl` sha=23b99b1bdaad
- semif: `E:\01_documents\Tencent\Wechat\xwechat_files\wxid_3pi5yps28df622_49fb\msg\file\2026-10\remote-sensing-operator-band-matching\results_v2\eval_semif.jsonl` sha=65246056c6d0
- von: `E:\01_documents\Tencent\Wechat\xwechat_files\wxid_3pi5yps28df622_49fb\msg\file\2026-10\remote-sensing-operator-band-matching\results_v2\eval_von.jsonl` sha=59e2f1f91c69
- armA: `E:\01_documents\Tencent\Wechat\xwechat_files\wxid_3pi5yps28df622_49fb\msg\file\2026-10\remote-sensing-operator-band-matching\results_v2\eval_v2_armA_hard.jsonl` sha=b6e731a8e242
- armB: `E:\01_documents\Tencent\Wechat\xwechat_files\wxid_3pi5yps28df622_49fb\msg\file\2026-10\remote-sensing-operator-band-matching\results_v2\eval_v2_armB_soft.jsonl` sha=f8b387d7ebb3
- armC: `E:\01_documents\Tencent\Wechat\xwechat_files\wxid_3pi5yps28df622_49fb\msg\file\2026-10\remote-sensing-operator-band-matching\results_v2\eval_v2_armC_brier.jsonl` sha=8fe7352b1fa8
- armA4b: `E:\01_documents\Tencent\Wechat\xwechat_files\wxid_3pi5yps28df622_49fb\msg\file\2026-10\remote-sensing-operator-band-matching\results_v2\eval_v2_armA_4b.jsonl` sha=1e46db3a44b4
- valA: `E:\01_documents\Tencent\Wechat\xwechat_files\wxid_3pi5yps28df622_49fb\msg\file\2026-10\remote-sensing-operator-band-matching\results_v2\eval_val_v2_armA_hard.jsonl` sha=6c6efaed2371
- valB: `E:\01_documents\Tencent\Wechat\xwechat_files\wxid_3pi5yps28df622_49fb\msg\file\2026-10\remote-sensing-operator-band-matching\results_v2\eval_val_v2_armB_soft.jsonl` sha=73511f9a4f80
- valC: `E:\01_documents\Tencent\Wechat\xwechat_files\wxid_3pi5yps28df622_49fb\msg\file\2026-10\remote-sensing-operator-band-matching\results_v2\eval_val_v2_armC_brier.jsonl` sha=77a8f46d5421
