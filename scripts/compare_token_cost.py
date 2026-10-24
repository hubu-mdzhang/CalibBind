# -*- coding: utf-8 -*-
"""Jev vs DeepSeek token 与成本对比（实测数据）"""

J_IN, J_OUT = 879, 135      # Jev 实测 97 样本均值
D_IN, D_OUT = 678, 54       # DeepSeek 实测 3 样本均值

# Jev: $0.042 / 1M 输入 token，输出免费
J_PIN, J_POUT = 0.042 / 1e6, 0.0
# DeepSeek: 输入 ¥1 / 1M，输出 ¥2 / 1M（缓存未命中，按官方标价估算）
D_PIN, D_POUT = 1.0 / 1e6, 2.0 / 1e6
FX = 7.2  # 美元兑人民币

print("=== 单样本 token 对比 ===")
print(f"{'':<12}{'输入':>9}{'输出':>9}{'总计':>10}")
print(f"{'Jev':<12}{J_IN:>9}{J_OUT:>9}{J_IN + J_OUT:>10}")
print(f"{'DeepSeek':<12}{D_IN:>9}{D_OUT:>9}{D_IN + D_OUT:>10}")
print(f"{'Jev/DS倍数':<12}{J_IN / D_IN:>8.2f}x{J_OUT / D_OUT:>8.2f}x"
      f"{(J_IN + J_OUT) / (D_IN + D_OUT):>9.2f}x")

print()
print("=== 输出 token 拆解（为什么 Jev 输出更多）===")
print("  DeepSeek 54 token : {\"mappings\":[{\"param\":\"redBandName\",\"band\":\"SR_B4\","
      "\"confidence\":1.0}, ...]}")
print("  Jev     135 token : 每个参数返回 choice + probabilities(6个键值) + confidence")
print("                      概率分布占了大头：6 个候选 x 2 参数 = 12 个键值对")

print()
print("=== 成本对比（单样本）===")
jc = J_IN * J_PIN + J_OUT * J_POUT
dc_cny = D_IN * D_PIN + D_OUT * D_POUT
dc = dc_cny / FX
print(f"  Jev      : ${jc:.8f}   输入 ${J_IN * J_PIN:.8f} + 输出 $0.00000000")
print(f"  DeepSeek : ${dc:.8f}   输入 ${D_IN * D_PIN / FX:.8f} + 输出 ${D_OUT * D_POUT / FX:.8f}")
print(f"  -> Jev 输出 token 多 2.5 倍，但因输出免费，总成本仅 DeepSeek 的 {jc / dc * 100:.0f}%")

print()
print("=== 194 次完整实验总成本 ===")
print(f"  Jev      : ${jc * 194:.4f}    (实测 ${0.003582:.4f})")
print(f"  DeepSeek : {dc_cny * 194 / FX:.4f} USD  ({dc_cny * 194:.2f} 元)")
print(f"  -> Jev 约为 DeepSeek 的 {0.003582 / (dc_cny * 194 / FX) * 100:.0f}%")

print()
print("=== 关键洞察 ===")
print("  1. 输入 token：Jev 反而更多(879 vs 678)，因为 criteria 里")
print("     每个候选都带波长描述，重复了 state 中的信息")
print("  2. 输出 token：Jev 多 2.5 倍，因为要返回完整概率分布")
print("  3. 但 Jev 输出免费 —— 这是它成本优势的核心")
print("  4. Jev 多出的输出 token 买到了 LLM 根本给不了的东西：")
print("     每个候选的概率分布，这是 NLL/Brier 得以计算的前提")