import json, math

with open("backtest_data/prices.json") as f:
    data = json.load(f)
names = ["510300", "159915", "513100", "518880"]
date_sets = [set(d for d, _ in data[n]) for n in names]
common_dates = sorted(set.intersection(*date_sets))
prices = {n: {d: v for d, v in data[n]} for n in names}
label = {"510300":"沪深300","159915":"创业板","513100":"纳指","518880":"黄金"}

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

def run(md=20, rb=5, topk=3, cost=0.0008, ma_stop=0, ma_rebuy=False):
    """
    ma_stop: 持仓期间跌破 N 日均线即清仓（0=不启用）
    ma_rebuy: 空仓期间，若某标的重新站上均线且动量>0，是否买回
    """
    nav=[]; holds=[]; last=-10**9; navv=1.0
    switches = 0
    for i in range(max(md, ma_stop), len(common_dates)):
        d=common_dates[i]
        moms={n: prices[n][d]/prices[n][common_dates[i-md]]-1 for n in names}

        # 持仓止损：跌破MA清仓
        if ma_stop > 0 and holds:
            new_holds = []
            for h in holds:
                mav = ma(common_dates, i, ma_stop, h)
                if mav is not None and prices[h][d] > mav:
                    new_holds.append(h)  # 站上均线，保留
                # 否则跌破均线，剔除（清仓）
            if set(new_holds) != set(holds):
                turnover = len(new_holds) + len(holds)
                navv *= (1 - cost * turnover / 2)
                switches += 1
            holds = new_holds

        # 调仓
        if i-last>=rb:
            last=i
            ranked = sorted(moms, key=moms.get, reverse=True)
            new_holds = [n for n in ranked[:topk] if moms[n] > 0]
            if set(new_holds) != set(holds):
                turnover = len(new_holds) + len(holds)
                navv *= (1 - cost * turnover / 2)
                switches += 1
            holds = new_holds

        # 收益
        if i>0:
            pd=common_dates[i-1]
            ret = 0.0 if not holds else sum(prices[h][d]/prices[h][pd]-1 for h in holds)/len(holds)
            navv*=(1+ret)
        nav.append((d,navv))
    return nav, switches

print("="*80)
print("测试：跌破 20 日线清仓、涨回买回（叠加在前3名方案上）")
print("="*80)
print(f"{'方案':<36}{'年化':>8}{'回撤':>9}{'夏普':>8}{'Calmar':>9}{'切换':>6}")

# 基准：前3名，无MA止损
nav, sw = run(20,5,3,0.0008,0)
s = stats(nav)
print(f"{'前3名（无MA止损，基准）':<36}{s['ann']*100:>7.1f}%{s['dd']*100:>8.1f}%{s['sharpe']:>8.2f}{s['calmar']:>9.2f}{sw:>6}")

print("\n【跌破MA清仓】不同均线周期：")
for m in [5,10,20,30,60]:
    nav, sw = run(20,5,3,0.0008,m)
    s = stats(nav)
    print(f"{'  跌破MA'+str(m)+'清仓':<34}{s['ann']*100:>7.1f}%{s['dd']*100:>8.1f}%{s['sharpe']:>8.2f}{s['calmar']:>9.2f}{sw:>6}")

print("\n【跌破MA20清仓】叠加不同动量窗口：")
for md in [10,20,40]:
    nav, sw = run(md,5,3,0.0008,20)
    s = stats(nav)
    print(f"{'  '+str(md)+'日动量+跌破MA20清仓':<32}{s['ann']*100:>7.1f}%{s['dd']*100:>8.1f}%{s['sharpe']:>8.2f}{s['calmar']:>9.2f}{sw:>6}")

print("\n【跌破MA20清仓】叠加不同持有数量：")
for k in [2,3,4]:
    nav, sw = run(20,5,k,0.0008,20)
    s = stats(nav)
    print(f"{'  前'+str(k)+'名+跌破MA20清仓':<32}{s['ann']*100:>7.1f}%{s['dd']*100:>8.1f}%{s['sharpe']:>8.2f}{s['calmar']:>9.2f}{sw:>6}")
