import json, math

with open("backtest_data/prices.json") as f:
    data = json.load(f)

label = {"510300":"沪深300","159915":"创业板","513100":"纳指","518880":"黄金","513520":"日经225","513500":"标普500"}

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

def run(names, md=20, rb=5, topk=3, cost=0.0008, ma_stop=20):
    date_sets=[set(d for d,_ in data[n]) for n in names]
    dates=sorted(set.intersection(*date_sets))
    px={n:{d:v for d,v in data[n]} for n in names}
    def ma(i,nd,name):
        if i<nd-1: return None
        return sum(px[name][dates[j]] for j in range(i-nd+1,i+1))/nd
    nav=[]; holds=[]; last=-10**9; navv=1.0; sw=0; cash=0; total=0
    hold_cnt={n:0 for n in names}
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
            nh=[n for n in ranked[:topk] if moms[n]>0]
            if set(nh)!=set(holds): navv*=(1-cost*(len(nh)+len(holds))/2); sw+=1
            holds=nh
        if i>0:
            pd=dates[i-1]
            ret=0.0 if not holds else sum(px[h][d]/px[h][pd]-1 for h in holds)/len(holds)
            navv*=(1+ret)
        total+=1
        if not holds: cash+=1
        for h in holds: hold_cnt[h]+=1
        nav.append((d,navv))
    return nav, dates, sw, cash/total, hold_cnt

names4 = ["510300","159915","513100","518880"]
names5 = ["510300","159915","513100","518880","513500"]
names6 = ["510300","159915","513100","518880","513500","513520"]

print("="*78)
print("回测对比：4标的 / 加标普500 / 加标普+日本")
print("="*78)

print("\n【各标的 5年买入持有】")
for n in ["510300","159915","513100","518880","513500","513520"]:
    if n not in data: continue
    rows = sorted(data[n])
    vals=[1.0]
    for i in range(1,len(rows)):
        vals.append(vals[-1]*(rows[i][1]/rows[i-1][1]))
    s=stats(list(zip([d for d,_ in rows], vals)))
    print(f"  {label[n]:<6}: 年化{s['ann']*100:6.1f}%  回撤{s['dd']*100:6.1f}%")

print("\n【策略回测：20日动量+前3名+跌破MA20清仓】")
print(f"{'方案':<26}{'年化':>8}{'回撤':>9}{'夏普':>8}{'Calmar':>9}{'总收益':>9}{'换手':>6}{'空仓':>7}")
for names, tag in [(names4,"4标的(基准)"),(names5,"5标的(加标普)"),(names6,"6标的(标普+日本)")]:
    nav, dates, sw, cash, cnt = run(names)
    s=stats(nav)
    print(f"{tag:<26}{s['ann']*100:>7.1f}%{s['dd']*100:>8.1f}%{s['sharpe']:>8.2f}{s['calmar']:>9.2f}{s['total']*100:>8.0f}%{sw:>6}{cash*100:>6.0f}%")

print("\n"+"="*78)
for names, tag in [(names5,"5标的(加标普)")]:
    nav, dates, sw, cash, cnt = run(names)
    tot=sum(cnt.values())
    print(f"\n【{tag}】持仓时间分布：")
    for n,c in sorted(cnt.items(), key=lambda x:-x[1]):
        print(f"  {label[n]}: {c/tot*100:.1f}%")
    values=[v for _,v in nav]; s=stats(nav)
    print(f"\n【{tag} 分年度】年化{s['ann']*100:.1f}% 回撤{s['dd']*100:.1f}%")
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
