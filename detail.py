import json

with open("backtest_data/prices.json") as f:
    data = json.load(f)
names = ["510300", "159915", "513100", "518880"]
date_sets = [set(d for d, _ in data[n]) for n in names]
common_dates = sorted(set.intersection(*date_sets))
prices = {n: {d: v for d, v in data[n]} for n in names}
label = {"510300":"沪深300","159915":"创业板","513100":"纳指","518880":"黄金"}

def run_backtest(momentum_days=20, rebalance_days=5):
    nav = []
    current_holding = None
    last_rebalance_idx = -10**9
    nav_value = 1.0
    holdings_log = []  # 记录每次调仓
    for i in range(momentum_days, len(common_dates)):
        d = common_dates[i]
        moms = {}
        for n in names:
            p_now = prices[n][d]
            p_past = prices[n][common_dates[i - momentum_days]]
            moms[n] = p_now / p_past - 1
        if i - last_rebalance_idx >= rebalance_days:
            last_rebalance_idx = i
            best = max(moms, key=moms.get)
            if moms[best] < 0:
                new_hold = None
            else:
                new_hold = best
            if new_hold != current_holding:
                holdings_log.append((d, current_holding, new_hold, moms))
                current_holding = new_hold
        if i > 0:
            prev_d = common_dates[i - 1]
            if current_holding is None:
                ret = 0.0
            else:
                ret = prices[current_holding][d] / prices[current_holding][prev_d] - 1
            nav_value *= (1 + ret)
        nav.append((d, nav_value))
    return nav, holdings_log

nav, log = run_backtest(20, 5)

# 年度收益
print("【20日动量/周调仓】年度收益拆解：")
years = {}
for d, v in nav:
    y = d[:4]
    years.setdefault(y, []).append(v)
prev_end = 1.0
for y in sorted(years):
    vals = years[y]
    end = vals[-1]
    ret = end / prev_end - 1
    print(f"  {y}年: {ret*100:6.1f}%")
    prev_end = end

print(f"\n【20日动量/周调仓】持仓切换记录（共 {len(log)} 次）：")
for d, old, new, moms in log[:60]:
    old_l = "空仓" if old is None else label[old]
    new_l = "空仓" if new is None else label[new]
    mom_str = " ".join(f"{label[n]}={moms[n]*100:.1f}%" for n in names)
    print(f"  {d}  {old_l:6s} -> {new_l:6s}   [{mom_str}]")
