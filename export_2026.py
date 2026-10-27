import json, math

with open("backtest_data/prices.json") as f:
    data = json.load(f)
names = ["510300","159915","513100","513500","518880"]
label = {"510300":"沪深300","159915":"创业板","513100":"纳指","513500":"标普500","518880":"黄金"}

date_sets=[set(d for d,_ in data[n]) for n in names]
dates=sorted(set.intersection(*date_sets))
px={n:{d:v for d,v in data[n]} for n in names}

def ma(i,nd,name):
    if i<nd-1: return None
    return sum(px[name][dates[j]] for j in range(i-nd+1,i+1))/nd

def run_full(md=20, rb=5, topk=3, cost=0.0008, ma_stop=20):
    nav=[]; holds=[]; last=-10**9; navv=1.0
    daily_holds=[]  # 每日持仓
    for i in range(max(md,ma_stop,30), len(dates)):
        d=dates[i]
        moms={n: px[n][d]/px[n][dates[i-md]]-1 for n in names}
        # 跌破MA20清仓
        if ma_stop>0 and holds:
            nh=[h for h in holds if ma(i,ma_stop,h) is None or px[h][d]>ma(i,ma_stop,h)]
            if set(nh)!=set(holds):
                navv*=(1-cost*(len(nh)+len(holds))/2)
            holds=nh
        # 周调仓
        if i-last>=rb:
            last=i
            ranked=sorted(moms,key=moms.get,reverse=True)
            nh=[n for n in ranked[:topk] if moms[n]>0 and (ma(i,20,n) is None or px[n][d]>ma(i,20,n))]
            if set(nh)!=set(holds):
                navv*=(1-cost*(len(nh)+len(holds))/2)
            holds=nh
        if i>0:
            pd=dates[i-1]
            ret=0.0 if not holds else sum(px[h][d]/px[h][pd]-1 for h in holds)/len(holds)
            navv*=(1+ret)
        nav.append((d,navv))
        daily_holds.append((d,list(holds)))
    return nav, daily_holds

nav, daily_holds = run_full()

# 只取2026年
nav_2026 = [(d,v) for d,v in nav if d >= "2026-01-01"]
holds_2026 = [(d,h) for d,h in daily_holds if d >= "2026-01-01"]

# 输出持仓切换（只在持仓变化时打印）
print("="*70)
print("2026年至今 持仓变化记录（只在切换时显示）")
print("="*70)
prev=None
for d,h in holds_2026:
    hs = "空仓" if not h else "+".join(label[n] for n in h)
    if hs != prev:
        print(f"{d}  ->  {hs}")
        prev=hs

# 统计2026收益
start_v = nav_2026[0][1]
end_v = nav_2026[-1][1]
print(f"\n2026-01-01 净值 {start_v:.4f} -> {nav_2026[-1][0]} 净值 {end_v:.4f}")
print(f"2026年至今收益: {(end_v/start_v-1)*100:.1f}%")

# 导出完整数据给图表
out = {
    "dates": [d for d,_ in nav_2026],
    "nav": [v for _,v in nav_2026],
    "holds": [[d, [label[n] for n in h]] for d,h in holds_2026],
}
json.dump(out, open("backtest_data/nav_2026.json","w"), ensure_ascii=False)
print(f"\n已导出 {len(nav_2026)} 个交易日数据")
