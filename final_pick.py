import json, math

with open("backtest_data/prices.json") as f:
    data = json.load(f)
names = ["510300", "159915", "513100", "518880"]
label = {"510300":"沪深300","159915":"创业板","513100":"纳指","518880":"黄金"}

def stats(nav):
    values=[v for _,v in nav]; n=len(values)
    years=(n-1)/250.0
    ann=(values[-1])**(1/years)-1 if values[-1]>0 else 0
    peak=values[0]; max_dd=0
    for v in values:
        if v>peak: peak=v
        dd=(v-peak)/peak
        if dd<max_dd: max_dd=dd
    daily=[values[i]/values[i-1]-1 for i in range(1,n)]
    mean_d=sum(daily)/len(daily)
    std_d=(sum((r-mean_d)**2 for r in daily)/len(daily))**0.5
    sharpe=mean_d/std_d*math.sqrt(250) if std_d>0 else 0
    return {"ann":ann,"dd":max_dd,"sharpe":sharpe,"calmar":ann/abs(max_dd) if max_dd else 0,"total":values[-1]-1}

def run(md=20, rb=5, topk=3, cost=0.0008, ma_stop=0, vol_filter=None):
    date_sets=[set(d for d,_ in data[n]) for n in names]
    dates=sorted(set.intersection(*date_sets))
    px={n:{d:v for d,v in data[n]} for n in names}
    def ma(i,nd,name):
        if i<nd-1: return None
        return sum(px[name][dates[j]] for j in range(i-nd+1,i+1))/nd
    def vol(i,nd,name):
        if i<nd: return None
        rets=[px[name][dates[j]]/px[name][dates[j-1]]-1 for j in range(i-nd+1,i+1)]
        m=sum(rets)/len(rets)
        return (sum((r-m)**2 for r in rets)/len(rets))**0.5
    nav=[]; holds=[]; last=-10**9; navv=1.0; sw=0; cash=0; total=0
    for i in range(max(md,ma_stop,30), len(dates)):
        d=dates[i]
        moms={n: px[n][d]/px[n][dates[i-md]]-1 for n in names}
        if ma_stop>0 and holds:
            nh=[h for h in holds if ma(i,ma_stop,h) is None or px[h][d]>ma(i,ma_stop,h)]
            if set(nh)!=set(holds): navv*=(1-cost*(len(nh)+len(holds))/2); sw+=1
            holds=nh
        if i-last>=rb:
            last=i
            ranked=sorted(moms,key=moms.get,reverse=True)
            nh=[]
            for n in ranked[:topk]:
                if moms[n]<=0: continue
                if vol_filter is not None:
                    v=vol(i,20,n)
                    if v is not None and v>vol_filter: continue
                nh.append(n)
            if set(nh)!=set(holds): navv*=(1-cost*(len(nh)+len(holds))/2); sw+=1
            holds=nh
        if i>0:
            pd=dates[i-1]
            ret=0.0 if not holds else sum(px[h][d]/px[h][pd]-1 for h in holds)/len(holds)
            navv*=(1+ret)
        total+=1
        if not holds: cash+=1
        nav.append((d,navv))
    return nav, dates, sw, cash/total

# 三个候选版本，含不同交易成本模拟
print("="*78)
print("三个版本在不同交易成本下的实盘预测（这才是你要的'结果'）")
print("="*78)

versions = [
    ("A. 前3名+MA20止损+波动过滤(高频)", dict(topk=3, ma_stop=20, vol_filter=0.02)),
    ("B. 前3名+MA20止损(折中)", dict(topk=3, ma_stop=20, vol_filter=None)),
    ("C. 前3名(简单分散)", dict(topk=3, ma_stop=0, vol_filter=None)),
]

for tag, kw in versions:
    nav, dates, sw, cash = run(**kw)
    s0 = stats(nav)  # 0.08%成本
    # 更高成本重跑
    nav2,_,_,_ = run(cost=0.003, **kw)
    s3 = stats(nav2)
    print(f"\n{tag}")
    print(f"  换手{sw}次 空仓{cash*100:.0f}%")
    print(f"  成本0.08%: 年化{s0['ann']*100:5.1f}%  回撤{s0['dd']*100:5.1f}%  夏普{s0['sharpe']:4.2f}")
    print(f"  成本0.30%: 年化{s3['ann']*100:5.1f}%  回撤{s3['dd']*100:5.1f}%")

# 重点：版本B的完整数据
nav, dates, sw, cash = run(topk=3, ma_stop=20, vol_filter=None)
s = stats(nav)
values=[v for _,v in nav]
print("\n"+"="*78)
print("★ 推荐版 B 完整数据")
print("="*78)
print(f"年化 {s['ann']*100:.1f}%  最大回撤 {s['dd']*100:.1f}%  夏普 {s['sharpe']:.2f}  总收益 {s['total']*100:.0f}%")
print(f"换手 {sw}次  空仓 {cash*100:.0f}%")
print("\n分年度：")
yrs={}
for d,v in zip(dates,values): yrs.setdefault(d[:4],[]).append(v)
prev=1.0
for y in sorted(yrs):
    yv=yrs[y]; end=yv[-1]; ret=end/prev-1
    p=yv[0]; mdd=0
    for v in yv:
        if v>p:p=v
        dd=(v-p)/p
        if dd<mdd:mdd=dd
    print(f"  {y}: 收益{ret*100:+6.1f}%  当年回撤{mdd*100:6.1f}%")
    prev=end
# 100万演示
print(f"\n100万按版本B回测滚动 → 最终 ¥{1000000*(1+s['total']):,.0f} ({(1+s['total'])*100:.0f}倍)")
