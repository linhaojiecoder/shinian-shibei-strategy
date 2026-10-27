import json

with open("backtest_data/prices.json") as f:
    data = json.load(f)

# 对齐日期：取 4 只都有数据的交易日
names = ["510300", "159915", "513100", "518880"]
date_sets = [set(d for d, _ in data[n]) for n in names]
common_dates = sorted(set.intersection(*date_sets))

# 构建价格矩阵（对齐到共同交易日）
prices = {n: {d: v for d, v in data[n]} for n in names}

def run_backtest(momentum_days=20, rebalance_days=5, cash_name=None):
    """动量轮动回测，返回净值序列和统计"""
    nav = []  # (date, nav)
    current_holding = None  # 当前持有的 ETF 名，None 表示空仓
    last_rebalance_idx = -10**9
    nav_value = 1.0

    # 需要 momentum_days 历史才能开始
    for i in range(momentum_days, len(common_dates)):
        d = common_dates[i]
        # 计算各 ETF 的动量（过去 momentum_days 的涨幅）
        moms = {}
        for n in names:
            p_now = prices[n][d]
            p_past = prices[n][common_dates[i - momentum_days]]
            moms[n] = p_now / p_past - 1

        # 调仓判断
        if i - last_rebalance_idx >= rebalance_days:
            last_rebalance_idx = i
            # 找动量最强的
            best = max(moms, key=moms.get)
            if moms[best] < 0:
                current_holding = None  # 全部负动量，空仓
            else:
                current_holding = best

        # 计算当日收益
        if i > 0:
            prev_d = common_dates[i - 1]
            if current_holding is None:
                # 空仓，收益为 0（假设现金无收益，或可另算货基）
                ret = 0.0
            else:
                p_now = prices[current_holding][d]
                p_prev = prices[current_holding][prev_d]
                ret = p_now / p_prev - 1
            nav_value *= (1 + ret)
        nav.append((d, nav_value))

    return nav

def stats(nav, start_nav=1.0):
    """计算年化收益、最大回撤、夏普、Calmar"""
    dates = [d for d, _ in nav]
    values = [v for _, v in nav]
    n = len(values)
    total_ret = values[-1] / start_nav - 1
    # 年化（按自然年，约 250 交易日/年）
    years = (n - 1) / 250.0
    ann_ret = (values[-1] / start_nav) ** (1 / years) - 1 if years > 0 else 0

    # 最大回撤
    peak = values[0]
    max_dd = 0
    for v in values:
        if v > peak:
            peak = v
        dd = (v - peak) / peak
        if dd < max_dd:
            max_dd = dd

    # 夏普（日收益年化）
    import math
    daily_rets = []
    for i in range(1, n):
        daily_rets.append(values[i] / values[i-1] - 1)
    mean_d = sum(daily_rets) / len(daily_rets) if daily_rets else 0
    var_d = sum((r - mean_d)**2 for r in daily_rets) / len(daily_rets) if daily_rets else 0
    std_d = math.sqrt(var_d)
    sharpe = (mean_d / std_d) * math.sqrt(250) if std_d > 0 else 0

    calmar = ann_ret / abs(max_dd) if max_dd != 0 else 0

    return {
        "total_ret": total_ret,
        "ann_ret": ann_ret,
        "max_dd": max_dd,
        "sharpe": sharpe,
        "calmar": calmar,
        "years": years,
    }

# 基准：买入持有 4 只等权
def buy_hold_stats():
    n = len(common_dates)
    port_values = []
    for i in range(n):
        d = common_dates[i]
        # 等权组合的日收益
        if i == 0:
            port_values.append(1.0)
            continue
        prev_d = common_dates[i-1]
        ret = 0
        for nm in names:
            ret += (prices[nm][d] / prices[nm][prev_d] - 1) / len(names)
        port_values.append(port_values[-1] * (1 + ret))
    nav = list(zip(common_dates, port_values))
    return nav

print("=" * 60)
print("回测区间：", common_dates[0], "~", common_dates[-1], f"（{len(common_dates)} 个交易日）")
print("=" * 60)

# 买入持有等权基准
bh_nav = buy_hold_stats()
bh = stats(bh_nav)
print(f"\n【基准】4 ETF 等权买入持有：")
print(f"  总收益 {bh['total_ret']*100:.1f}%  年化 {bh['ann_ret']*100:.1f}%  最大回撤 {bh['max_dd']*100:.1f}%  夏普 {bh['sharpe']:.2f}")

# 各 ETF 单独买入持有
print(f"\n【基准】各 ETF 单独买入持有（近5年）：")
for nm in names:
    vals = []
    for i, d in enumerate(common_dates):
        if i == 0:
            vals.append(1.0)
        else:
            prev_d = common_dates[i-1]
            vals.append(vals[-1] * (prices[nm][d]/prices[nm][prev_d]))
    nav = list(zip(common_dates, vals))
    s = stats(nav)
    label = {"510300":"沪深300","159915":"创业板","513100":"纳指","518880":"黄金"}[nm]
    print(f"  {label:6s} 总收益 {s['total_ret']*100:7.1f}%  年化 {s['ann_ret']*100:6.1f}%  回撤 {s['max_dd']*100:6.1f}%")

# 动量轮动多组参数
print(f"\n【策略】动量轮动（全仓持动量最强 1 个，负动量空仓）：")
configs = [
    (20, 5, "20日动量/周调仓"),
    (20, 10, "20日动量/双周调仓"),
    (60, 5, "60日动量/周调仓"),
    (60, 10, "60日动量/双周调仓"),
    (20, 20, "20日动量/月调仓"),
    (40, 5, "40日动量/周调仓"),
]
for md, rb, label in configs:
    nav = run_backtest(md, rb)
    s = stats(nav)
    print(f"  {label:18s} 年化 {s['ann_ret']*100:6.1f}%  回撤 {s['max_dd']*100:6.1f}%  夏普 {s['sharpe']:.2f}  Calmar {s['calmar']:.2f}")

# 保存关键结果供后续画图
result = {
    "common_dates": common_dates,
    "prices": prices,
    "names": names,
}
with open("backtest_data/backtest_result.json", "w") as f:
    json.dump(result, f, ensure_ascii=False)
print("\n回测数据已保存")
