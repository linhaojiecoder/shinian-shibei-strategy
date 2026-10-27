import json

with open("backtest_data/prices.json") as f:
    data = json.load(f)
names = ["510300", "159915", "513100", "518880"]
date_sets = [set(d for d, _ in data[n]) for n in names]
common_dates = sorted(set.intersection(*date_sets))
prices = {n: {d: v for d, v in data[n]} for n in names}
label = {"510300":"沪深300","159915":"创业板","513100":"纳指","518880":"黄金"}

def run_backtest(momentum_days=20, rebalance_days=5, max_hold=1, min_mom=0.0,
                 stop_loss=None, vol_filter=None, allow_cash=True):
    """通用回测引擎，支持多种风控参数"""
    nav = []
    current_holding = None
    last_rebalance_idx = -10**9
    nav_value = 1.0
    peak = 1.0
    for i in range(momentum_days, len(common_dates)):
        d = common_dates[i]
        moms = {}
        for n in names:
            p_now = prices[n][d]
            p_past = prices[n][common_dates[i - momentum_days]]
            moms[n] = p_now / p_past - 1
        # 调仓
        if i - last_rebalance_idx >= rebalance_days:
            last_rebalance_idx = i
            best = max(moms, key=moms.get)
            if moms[best] < min_mom:
                current_holding = None
            else:
                current_holding = best
        # 止损：单日跌破止损线则空仓
        if stop_loss is not None and current_holding is not None and i > 0:
            prev_d = common_dates[i-1]
            p_prev = prices[current_holding][prev_d]
            p_now = prices[current_holding][d]
            # 从持仓以来的最高点算回撤
            if p_now / p_prev - 1 < stop_loss:
                # 单日大跌触发止损，次日空仓
                current_holding = None
                last_rebalance_idx = i  # 避免立刻买回
        # 计算收益
        if i > 0:
            prev_d = common_dates[i - 1]
            if current_holding is None:
                ret = 0.0
            else:
                ret = prices[current_holding][d] / prices[current_holding][prev_d] - 1
            nav_value *= (1 + ret)
        nav.append((d, nav_value))
    return nav

def stats(nav):
    values = [v for _, v in nav]
    n = len(values)
    years = (n - 1) / 250.0
    ann_ret = (values[-1]) ** (1 / years) - 1 if years > 0 else 0
    peak = values[0]; max_dd = 0
    dd_start = dd_end = None
    for i, v in enumerate(values):
        if v > peak:
            peak = v
        dd = (v - peak) / peak
        if dd < max_dd:
            max_dd = dd
    import math
    daily = [values[i]/values[i-1]-1 for i in range(1,n)]
    mean_d = sum(daily)/len(daily)
    std_d = (sum((r-mean_d)**2 for r in daily)/len(daily))**0.5
    sharpe = mean_d/std_d*math.sqrt(250) if std_d>0 else 0
    return {"ann":ann_ret, "dd":max_dd, "sharpe":sharpe, "calmar":ann_ret/abs(max_dd) if max_dd else 0}

print("="*70)
print("回撤优化测试（原策略：20日动量/周调仓，年化32.6% 回撤-27.3%）")
print("="*70)

# 先定位回撤时段
nav0, _ = run_backtest(20,5), None
nav0 = run_backtest(20,5)
values = [v for _,v in nav0]
dates = [d for d,_ in nav0]
peak = values[0]; max_dd = 0; cur_peak_idx = 0
dd_ranges = []
for i,v in enumerate(values):
    if v > peak:
        peak = v; cur_peak_idx = i
    dd = (v-peak)/peak
    if dd < max_dd:
        max_dd = dd

# 找出最大回撤区间
peak = values[0]; max_dd=0; peak_idx=0; trough_idx=0
for i,v in enumerate(values):
    if v>peak: peak=v; peak_idx=i
    dd=(v-peak)/peak
    if dd<max_dd: max_dd=dd; trough_idx=i
print(f"\n最大回撤 {max_dd*100:.1f}%")
print(f"  峰值日 {dates[peak_idx]}，谷底日 {dates[trough_idx]}")

# 分年度回撤
print("\n分年度最大回撤：")
for y in ["2021","2022","2023","2024","2025","2026"]:
    yr_vals = [(d,v) for d,v in zip(dates,values) if d[:4]==y]
    if not yr_vals: continue
    p = yr_vals[0][1]; mdd=0
    for d,v in yr_vals:
        if v>p: p=v
        dd=(v-p)/p
        if dd<mdd: mdd=dd
    print(f"  {y}: {mdd*100:.1f}%")
