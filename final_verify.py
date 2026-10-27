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

def run(md=20, rb=5, topk=1, ma_filter=0, cost=0.0008):
    nav=[]; holds=[]; last=-10**9; navv=1.0
    hold_log=[]
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
            if set(new_holds) != set(holds):
                turnover = len(new_holds) + len(holds)
                navv *= (1 - cost * turnover / 2)
            holds = new_holds
            hold_log.append((d, list(holds)))
        if i>0:
            pd=common_dates[i-1]
            if not holds:
                ret=0.0
            else:
                ret = sum(prices[h][d]/prices[h][pd]-1 for h in holds)/len(holds)
            navv*=(1+ret)
        nav.append((d,navv))
    return nav, hold_log

# 前3名方案分年度
for k, name in [(1,"前1名"), (2,"前2名"), (3,"前3名")]:
    nav, _ = run(20,5,k,0,0.0008)
    values=[v for _,v in nav]; dates=[d for d,_ in nav]
    s = stats(nav)
    print(f"\n【{name}】年化{s['ann']*100:.1f}% 回撤{s['dd']*100:.1f}% 夏普{s['sharpe']:.2f}")
    prev=1.0
    yrs = {}
    for d,v in zip(dates,values):
        yrs.setdefault(d[:4],[]).append(v)
    for y in sorted(yrs):
        end=yrs[y][-1]
        ret=end/prev-1
        print(f"    {y}年: {ret*100:6.1f}%")
        prev=end
    # 分年度回撤
    print(f"    分年度回撤:", end=" ")
    for y in sorted(yrs):
        vv=yrs[y]; p=vv[0]; mdd=0
        for v in vv:
            if v>p:p=v
            dd=(v-p)/p
            if dd<mdd:mdd=dd
        print(f"{y}:{mdd*100:.0f}%", end=" ")
    print()

# 前3名的最终持仓分布统计
nav, log = run(20,5,3,0,0.0008)
from collections import Counter
hold_count = Counter()
for d, holds in log:
    for h in holds:
        hold_count[label[h]] += 1
total = sum(hold_count.values())
print(f"\n【前3名方案】持仓时间分布：")
for l, c in hold_count.most_common():
    print(f"    {l}: {c/total*100:.0f}%")
