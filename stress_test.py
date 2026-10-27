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

def vol(dates, i, n, name):
    if i < n: return None
    rets = [prices[name][dates[j]]/prices[name][dates[j-1]]-1 for j in range(i-n+1, i+1)]
    m = sum(rets)/len(rets)
    return (sum((r-m)**2 for r in rets)/len(rets))**0.5

def run(md=20, rb=5, topk=3, cost=0.0008, ma_stop=20, vol_filter=None, vol_lb=20):
    nav=[]; holds=[]; last=-10**9; navv=1.0
    for i in range(max(md, ma_stop, 30), len(common_dates)):
        d=common_dates[i]
        moms={n: prices[n][d]/prices[n][common_dates[i-md]]-1 for n in names}
        if ma_stop > 0 and holds:
            new_holds=[h for h in holds if ma(common_dates,i,ma_stop,h) is None or prices[h][d]>ma(common_dates,i,ma_stop,h)]
            if set(new_holds)!=set(holds):
                navv*=(1-cost*(len(new_holds)+len(holds))/2)
            holds=new_holds
        if i-last>=rb:
            last=i
            ranked=sorted(moms,key=moms.get,reverse=True)
            new_holds=[]
            for n in ranked[:topk]:
                if moms[n]<=0: continue
                if vol_filter is not None:
                    v=vol(common_dates,i,vol_lb,n)
                    if v is not None and v>vol_filter: continue
                new_holds.append(n)
            if set(new_holds)!=set(holds):
                navv*=(1-cost*(len(new_holds)+len(holds))/2)
            holds=new_holds
        if i>0:
            pd=common_dates[i-1]
            ret=0.0 if not holds else sum(prices[h][d]/prices[h][pd]-1 for h in holds)/len(holds)
            navv*=(1+ret)
        nav.append((d,navv))
    return nav

print("="*80)
print("参数稳健性检验（最优方案：MA20止损+波动率>2%剔除）")
print("="*80)
print(f"{'参数扰动':<36}{'年化':>8}{'回撤':>9}{'夏普':>8}")
print("-"*80)

base_params = dict(md=20, rb=5, topk=3, ma_stop=20, vol_filter=0.02, vol_lb=20)
s = stats(run(**base_params))
print(f"{'基准组合':<36}{s['ann']*100:>7.1f}%{s['dd']*100:>8.1f}%{s['sharpe']:>8.2f}")

# 单参数扰动
print("\n【单参数扰动】")
for name, param, vals in [
    ("动量窗口md", "md", [10,15,20,30,40]),
    ("调仓周期rb", "rb", [3,5,7,10]),
    ("持有数topk", "topk", [2,3,4]),
    ("止损均线ma_stop", "ma_stop", [15,20,30,40]),
    ("波动率阈值vol_filter", "vol_filter", [0.015,0.018,0.02,0.022,0.025]),
    ("波动窗口vol_lb", "vol_lb", [10,15,20,30,40]),
]:
    for v in vals:
        p = base_params.copy(); p[param] = v
        s = stats(run(**p))
        print(f"  {name}={v:<8} 年化{s['ann']*100:6.1f}% 回撤{s['dd']*100:6.1f}% 夏普{s['sharpe']:5.2f}")
    print()

# 交易成本敏感性
print("\n【交易成本敏感性】(基准参数下改成本)")
for cost in [0.0003, 0.0008, 0.0015, 0.003, 0.005]:
    p = base_params.copy(); p["cost"] = cost
    s = stats(run(**p))
    print(f"  单边成本{cost*100:.2f}%: 年化{s['ann']*100:6.1f}% 回撤{s['dd']*100:6.1f}%")
