import json, math

with open("backtest_data/prices.json") as f:
    data = json.load(f)
names = ["510300", "159915", "513100", "518880"]
date_sets = [set(d for d, _ in data[n]) for n in names]
common_dates = sorted(set.intersection(*date_sets))
prices = {n: {d: v for d, v in data[n]} for n in names}

def run(md=20, rb=5, topk=1, cost=0.0008):
    nav=[]; holds=[]; last=-10**9; navv=1.0
    for i in range(md, len(common_dates)):
        d=common_dates[i]
        moms={n: prices[n][d]/prices[n][common_dates[i-md]]-1 for n in names}
        if i-last>=rb:
            last=i
            ranked = sorted(moms, key=moms.get, reverse=True)
            new_holds = [n for n in ranked[:topk] if moms[n] > 0]
            if set(new_holds) != set(holds):
                turnover = len(new_holds) + len(holds)
                navv *= (1 - cost * turnover / 2)
            holds = new_holds
        if i>0:
            pd=common_dates[i-1]
            ret = 0.0 if not holds else sum(prices[h][d]/prices[h][pd]-1 for h in holds)/len(holds)
            navv*=(1+ret)
        nav.append((d,navv))
    return nav

series = {}
for k in [1,2,3]:
    nav = run(20,5,k)
    series[k] = [v for _,v in nav]
dates = [d for d,_ in run(20,5,1)]

# 采样
step = max(1, len(dates)//600)
out = {
    "dates": dates[::step],
    "k1": series[1][::step],
    "k2": series[2][::step],
    "k3": series[3][::step],
}
json.dump(out, open("backtest_data/opt_chart.json","w"), ensure_ascii=False)
js = json.dumps(out, ensure_ascii=False)
open("backtest_data/opt_chart.js","w").write("window.OPT_DATA = " + js + ";")
print("saved", len(out["dates"]), "points")
