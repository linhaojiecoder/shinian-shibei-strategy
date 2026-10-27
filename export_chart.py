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
            current_holding = None if moms[best] < 0 else best
        if i > 0:
            prev_d = common_dates[i - 1]
            if current_holding is None:
                ret = 0.0
            else:
                ret = prices[current_holding][d] / prices[current_holding][prev_d] - 1
            nav_value *= (1 + ret)
        nav.append((d, nav_value))
    return nav

# 等权基准
def buy_hold():
    vals = [1.0]
    for i in range(1, len(common_dates)):
        d = common_dates[i]; prev = common_dates[i-1]
        r = sum(prices[n][d]/prices[n][prev]-1 for n in names)/len(names)
        vals.append(vals[-1]*(1+r))
    return list(zip(common_dates, vals))

strat_nav = run_backtest(20, 5)
bh_nav = buy_hold()
# 纳指单独
nq_vals = [1.0]
for i in range(1, len(common_dates)):
    d=common_dates[i]; prev=common_dates[i-1]
    nq_vals.append(nq_vals[-1]*(prices["513100"][d]/prices["513100"][prev]))
nq_nav = list(zip(common_dates, nq_vals))

out = {
    "dates": [d for d,_ in strat_nav],
    "strat": [v for _,v in strat_nav],
    "bh": [v for _,v in bh_nav],
    "nq": [v for _,v in nq_nav],
    "labels": label,
}
with open("backtest_data/chart_data.json","w") as f:
    json.dump(out, f, ensure_ascii=False)
print("chart data saved", len(out["dates"]), "points")
print("最终净值 - 策略:", round(strat_nav[-1][1],3), " 基准:", round(bh_nav[-1][1],3), " 纳指:", round(nq_nav[-1][1],3))
