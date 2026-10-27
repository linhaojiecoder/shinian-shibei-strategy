import json, math

with open("backtest_data/prices.json") as f:
    data = json.load(f)
names = ["510300", "159915", "513100", "518880"]
date_sets = [set(d for d, _ in data[n]) for n in names]
common_dates = sorted(set.intersection(*date_sets))
prices = {n: {d: v for d, v in data[n]} for n in names}

def stats(nav):
    values = [v for _, v in nav]
    n = len(values)
    years = (n - 1) / 250.0
    ann_ret = (values[-1]) ** (1 / years) - 1 if years > 0 and values[-1] > 0 else 0
    peak = values[0]; max_dd = 0
    for v in values:
        if v > peak: peak = v
        dd = (v - peak) / peak
        if dd < max_dd: max_dd = dd
    daily = [values[i]/values[i-1]-1 for i in range(1,n)]
    mean_d = sum(daily)/len(daily)
    std_d = (sum((r-mean_d)**2 for r in daily)/len(daily))**0.5
    sharpe = mean_d/std_d*math.sqrt(250) if std_d>0 else 0
    return {"ann":ann_ret, "dd":max_dd, "sharpe":sharpe, "calmar":ann_ret/abs(max_dd) if max_dd else 0}

def ma(dates, i, n, name):
    if i < n-1: return None
    return sum(prices[name][dates[j]] for j in range(i-n+1, i+1)) / n

# 带交易成本的通用回测引擎
def run(md=20, rb=5, topk=1, ma_filter=0, cost=0.0008):
    """
    md: 动量窗口
    rb: 调仓周期
    topk: 持有前几名
    ma_filter: >0 时要求价格在N日均线上方才持有
    cost: 单边交易成本（佣金+滑点+冲击）
    """
    nav=[]; holds=[]; last=-10**9; navv=1.0
    for i in range(max(md, ma_filter), len(common_dates)):
        d=common_dates[i]
        moms={n: prices[n][d]/prices[n][common_dates[i-md]]-1 for n in names}
        if i-last>=rb:
            last=i
            ranked = sorted(moms, key=moms.get, reverse=True)
            new_holds = []
            for n in ranked[:topk]:
                if moms[n] <= 0: continue
                if ma_filter > 0:
                    mav = ma(common_dates, i, ma_filter, n)
                    if mav is not None and prices[n][d] <= mav:
                        continue
                new_holds.append(n)
            # 计算换手，扣成本
            if set(new_holds) != set(holds):
                turnover = len(new_holds) + len(holds)
                navv *= (1 - cost * turnover / 2)
            holds = new_holds
        if i>0:
            pd=common_dates[i-1]
            if not holds:
                ret=0.0
            else:
                ret = sum(prices[h][d]/prices[h][pd]-1 for h in holds)/len(holds)
            navv*=(1+ret)
        nav.append((d,navv))
    return nav

print("="*80)
print("深入优化（含交易成本，单边0.08%≈佣金万1+滑点）")
print("="*80)
print(f"{'方案':<32}{'年化':>8}{'回撤':>9}{'夏普':>8}{'Calmar':>9}")

# 基准（含成本）
base = stats(run(20,5,1,0,0.0008))
print(f"{'0. 原始20日/周(含成本)':<32}{base['ann']*100:>7.1f}%{base['dd']*100:>8.1f}%{base['sharpe']:>8.2f}{base['calmar']:>9.2f}")

print("\n【A组】持有前K名分散（降低集中度回撤）")
for k in [1,2,3]:
    for ma_f in [0,20]:
        s = stats(run(20,5,k,ma_f,0.0008))
        tag = f"前{k}名" + (f"+MA{ma_f}过滤" if ma_f else "")
        print(f"  {tag:<30}{s['ann']*100:>7.1f}%{s['dd']*100:>8.1f}%{s['sharpe']:>8.2f}{s['calmar']:>9.2f}")

print("\n【B组】不同动量窗口 + 均线过滤组合")
for md in [10,20,40]:
    for ma_f in [10,20,40]:
        s = stats(run(md,5,1,ma_f,0.0008))
        print(f"  {md}日动量+MA{ma_f}过滤{'':<10}{s['ann']*100:>7.1f}%{s['dd']*100:>8.1f}%{s['sharpe']:>8.2f}{s['calmar']:>9.2f}")

print("\n【C组】调仓周期影响（前2名+MA20）")
for rb in [5,10,15,20]:
    s = stats(run(20,rb,2,20,0.0008))
    print(f"  前2名+MA20 / {rb}日调仓{'':<8}{s['ann']*100:>7.1f}%{s['dd']*100:>8.1f}%{s['sharpe']:>8.2f}{s['calmar']:>9.2f}")
