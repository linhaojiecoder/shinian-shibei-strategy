import json

with open("backtest_data/prices.json") as f:
    data = json.load(f)
names = ["510300","159915","513100","513500","518880"]
label = {"510300":"沪深300","159915":"创业板","513100":"纳指","513500":"标普500","518880":"黄金"}

date_sets=[set(d for d,_ in data[n]) for n in names]
dates=sorted(set.intersection(*date_sets))
px={n:{d:v for d,v in data[n]} for n in names}

# 找到2026-10-16这个交易日
idx = None
for i,d in enumerate(dates):
    if d == "2026-10-16":
        idx = i
        break
print(f"目标交易日: {dates[idx]} (周{'一二三四五六日'[__import__('datetime').date(2026,10,16).weekday()]})\n")

def ma(i,nd,name):
    if i<nd-1: return None
    return sum(px[name][dates[j]] for j in range(i-nd+1,i+1))/nd

i=idx; d=dates[i]
print(f"{'标的':<8}{'今收':>8}{'20日前':>10}{'20日涨幅':>10}{'MA20':>8}{'状态':>8}")
moms={}
for n in names:
    r=px[n][d]/px[n][dates[i-20]]-1
    moms[n]=r
    m=ma(i,20,n)
    st="站上" if px[n][d]>m else "跌破"
    print(f"{label[n]:<8}{px[n][d]:>8.3f}{px[n][dates[i-20]]:>10.3f}{r*100:>9.2f}%{m:>8.3f}{st:>8}")

ranked=sorted(moms,key=moms.get,reverse=True)
print("\n涨幅排名:", " > ".join(f"{label[n]}({moms[n]*100:.1f}%)" for n in ranked))
print("\n前3名过两关：")
holds=[]
for n in ranked[:3]:
    ok_mom=moms[n]>0
    m=ma(i,20,n); ok_ma=px[n][d]>m
    print(f"  {label[n]}: 涨幅{'+' if ok_mom else '-'} 均线{'站上' if ok_ma else '跌破'} -> {'✓买入' if ok_mom and ok_ma else '✗剔除'}")
    if ok_mom and ok_ma: holds.append(n)

print(f"\n★ 上周五应持有 {len(holds)} 个:")
for n in holds:
    print(f"  {label[n]} ({n}) 收 {px[n][d]:.3f} 元")
if not holds:
    print("  （空仓）")
