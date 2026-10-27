import json

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

print("今日信号", d)
moms={}
for n in names:
    moms[n]=px[n][d]/px[n][dates[i-20]]-1
ranked=sorted(moms,key=moms.get,reverse=True)
holds=[]
for n in ranked[:3]:
    m=ma(i,20,n)
    if moms[n]>0 and px[n][d]>m:
        holds.append(n)
print("持仓:", [label[n] for n in holds] if holds else "空仓")
for n in names:
    print(f"{label[n]}: 收{px[n][d]:.3f} 动量{moms[n]*100:+.2f}% MA20 {ma(i,20,n):.3f}")
