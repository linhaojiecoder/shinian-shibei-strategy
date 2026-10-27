import json, math
with open("backtest_data/prices.json") as f:
    data = json.load(f)
names = ["510300","159915","513100","513500","518880"]
label = {"510300":"沪深300","159915":"创业板","513100":"纳指","513500":"标普500","518880":"黄金"}
date_sets=[set(d for d,_ in data[n]) for n in names]
dates=sorted(set.intersection(*date_sets))
px={n:{d:v for d,v in data[n]} for n in names}
i=len(dates)-1; d=dates[i]
def ma(i,nd,name):
    if i<nd-1: return None
    return sum(px[name][dates[j]] for j in range(i-nd+1,i+1))/nd
def vol(i,nd,name):
    if i<nd: return None
    rets=[px[name][dates[j]]/px[name][dates[j-1]]-1 for j in range(i-nd+1,i+1)]
    m=sum(rets)/len(rets)
    return (sum((r-m)**2 for r in rets)/len(rets))**0.5
print("今日", d)
moms={}
for n in names:
    moms[n]=px[n][d]/px[n][dates[i-20]]-1
ranked=sorted(moms,key=moms.get,reverse=True)
holds=[]
for n in ranked[:3]:
    m=ma(i,20,n); v=vol(i,20,n)
    ok_mom=moms[n]>0
    ok_ma=m is not None and px[n][d]>m
    ok_vol=v is not None and v<=0.02
    print(f"{label[n]}: 动量{moms[n]*100:+.2f}% 波动率{v*100 if v else 0:.2f}% MA20站上{'是' if ok_ma else '否'}")
    if ok_mom and ok_ma and ok_vol:
        holds.append(n)
print("持仓:", [label[n] for n in holds] if holds else "空仓")
