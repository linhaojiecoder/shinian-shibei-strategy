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

def vol(dates, i, n, name):
    if i < n: return None
    rets = [prices[name][dates[j]]/prices[name][dates[j-1]]-1 for j in range(i-n+1, i+1)]
    m = sum(rets)/len(rets)
    return (sum((r-m)**2 for r in rets)/len(rets))**0.5

def run(md=20, rb=5, topk=3, cost=0.0008, ma_stop=20, vol_filter=None, vol_lb=20):
    nav=[]; holds=[]; last=-10**9; navv=1.0; switches=0
    cash_days=0; total=0
    for i in range(max(md, ma_stop, 30), len(common_dates)):
        d=common_dates[i]
        moms={n: prices[n][d]/prices[n][common_dates[i-md]]-1 for n in names}
        if ma_stop > 0 and holds:
            new_holds=[h for h in holds if ma(common_dates,i,ma_stop,h) is None or prices[h][d]>ma(common_dates,i,ma_stop,h)]
            if set(new_holds)!=set(holds):
                navv*=(1-cost*(len(new_holds)+len(holds))/2); switches+=1
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
                navv*=(1-cost*(len(new_holds)+len(holds))/2); switches+=1
            holds=new_holds
        if i>0:
            pd=common_dates[i-1]
            ret=0.0 if not holds else sum(prices[h][d]/prices[h][pd]-1 for h in holds)/len(holds)
            navv*=(1+ret)
        total+=1
        if not holds: cash_days+=1
        nav.append((d,navv))
    return nav, switches, cash_days/total

# 最优方案分年度验证
print("【最优：跌破MA20清仓 + 波动率>2%剔除】")
for vf in [0.015, 0.02, 0.025]:
    nav, sw, cash = run(20,5,3,0.0008,20,vf,20)
    s = stats(nav)
    print(f"\n  波动率>{vf*100:.1f}%剔除: 年化{s['ann']*100:.1f}% 回撤{s['dd']*100:.1f}% 夏普{s['sharpe']:.2f} 切换{sw} 空仓{cash*100:.0f}%")

# 分年度看最优（vf=0.02）
nav, sw, cash = run(20,5,3,0.0008,20,0.02,20)
values=[v for _,v in nav]; dates=[d for d,_ in nav]
s=stats(nav)
print(f"\n【波动率>2%剔除 分年度】年化{s['ann']*100:.1f}% 回撤{s['dd']*100:.1f}% 空仓{cash*100:.0f}%")
prev=1.0; yrs={}
for d,v in zip(dates,values): yrs.setdefault(d[:4],[]).append(v)
for y in sorted(yrs):
    end=yrs[y][-1]; ret=end/prev-1
    vv=yrs[y]; p=vv[0]; mdd=0
    for v in vv:
        if v>p:p=v
        dd=(v-p)/p
        if dd<mdd:mdd=dd
    print(f"  {y}年: 收益{ret*100:6.1f}%  当年回撤{mdd*100:6.1f}%")
    prev=end
