import json, math

with open("backtest_data/prices.json") as f:
    data = json.load(f)
names = ["510300", "159915", "513100", "518880"]
date_sets = [set(d for d, _ in data[n]) for n in names]
common_dates = sorted(set.intersection(*date_sets))
prices = {n: {d: v for d, v in data[n]} for n in names}

def ma(dates, i, n, name):
    if i < n-1: return None
    return sum(prices[name][dates[j]] for j in range(i-n+1, i+1)) / n
def vol(dates, i, n, name):
    if i < n: return None
    rets=[prices[name][dates[j]]/prices[name][dates[j-1]]-1 for j in range(i-n+1,i+1)]
    m=sum(rets)/len(rets)
    return (sum((r-m)**2 for r in rets)/len(rets))**0.5

def run(md, rb, topk, cost, ma_stop, vol_filter, vol_lb=20):
    nav=[]; holds=[]; last=-10**9; navv=1.0
    for i in range(max(md,ma_stop,30), len(common_dates)):
        d=common_dates[i]
        moms={n: prices[n][d]/prices[n][common_dates[i-md]]-1 for n in names}
        if ma_stop>0 and holds:
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

# 三个方案对比：原始前1 / 前3 / 最优(MA20止损+波动过滤)
def run_simple(md, rb, topk, cost):
    return run(md, rb, topk, cost, 0, None)

s1 = run_simple(20,5,1,0.0008)
s3 = run_simple(20,5,3,0.0008)
s_best = run(20,5,3,0.0008,20,0.02)

dates = [d for d,_ in s1]
step = max(1, len(dates)//600)
out = {
    "dates": dates[::step],
    "k1": [v for _,v in s1][::step],
    "k3": [v for _,v in s3][::step],
    "best": [v for _,v in s_best][::step],
}
json.dump(out, open("backtest_data/final_chart.json","w"), ensure_ascii=False)
open("backtest_data/final_chart.js","w").write("window.FINAL_DATA = "+json.dumps(out, ensure_ascii=False)+";")
print("saved", len(out["dates"]))
