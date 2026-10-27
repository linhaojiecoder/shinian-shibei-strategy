import json, math

with open("backtest_data/prices.json") as f:
    data = json.load(f)
names = ["510300", "159915", "513100", "518880"]
date_sets = [set(d for d, _ in data[n]) for n in names]
common_dates = sorted(set.intersection(*date_sets))
prices = {n: {d: v for d, v in data[n]} for n in names}
label = {"510300":"沪深300","159915":"创业板","513100":"纳指","518880":"黄金"}

def ma(dates, i, n, name):
    if i < n-1: return None
    return sum(prices[name][dates[j]] for j in range(i-n+1, i+1)) / n

def vol(dates, i, n, name):
    if i < n: return None
    rets=[prices[name][dates[j]]/prices[name][dates[j-1]]-1 for j in range(i-n+1,i+1)]
    m=sum(rets)/len(rets)
    return (sum((r-m)**2 for r in rets)/len(rets))**0.5

def run(md=20, rb=5, topk=3, cost=0.0008, ma_stop=20, vol_filter=0.02, vol_lb=20, log=True):
    nav=[]; holds=[]; last=-10**9; navv=1.0; switches=0
    hold_log=[]  # (date, holds)
    cash_days=0; total=0
    for i in range(max(md,ma_stop,30), len(common_dates)):
        d=common_dates[i]
        moms={n: prices[n][d]/prices[n][common_dates[i-md]]-1 for n in names}
        if ma_stop>0 and holds:
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
        if log:
            hold_log.append((d, list(holds)))
    return nav, switches, cash_days/total, hold_log

nav, sw, cash, hold_log = run()

# 统计
def stats(nav):
    values=[v for _,v in nav]; n=len(values)
    years=(n-1)/250.0
    ann=(values[-1])**(1/years)-1
    peak=values[0]; max_dd=0; peak_i=0; trough_i=0; dd_start=0
    cur_peak=values[0]; cur_peak_i=0
    for i,v in enumerate(values):
        if v>cur_peak: cur_peak=v; cur_peak_i=i
        dd=(v-cur_peak)/cur_peak
        if dd<max_dd: max_dd=dd; peak_i=cur_peak_i; trough_i=i
    daily=[values[i]/values[i-1]-1 for i in range(1,n)]
    mean_d=sum(daily)/len(daily)
    std_d=(sum((r-mean_d)**2 for r in daily)/len(daily))**0.5
    sharpe=mean_d/std_d*math.sqrt(250)
    return ann, max_dd, sharpe, peak_i, trough_i, values[-1]

ann, dd, sharpe, peak_i, trough_i, final = stats(nav)
dates=[d for d,_ in nav]; values=[v for _,v in nav]

print("="*70)
print("最优方案：跌破MA20止损 + 波动率>2%剔除（前3名）")
print("="*70)
print(f"回测区间: {dates[0]} ~ {dates[-1]}  ({len(dates)}个交易日)")
print(f"总收益: {(final-1)*100:.1f}%")
print(f"年化收益: {ann*100:.1f}%")
print(f"最大回撤: {dd*100:.1f}%")
print(f"  回撤峰值日: {dates[peak_i]}  谷底日: {dates[trough_i]}")
print(f"夏普: {sharpe:.2f}  Calmar: {ann/abs(dd):.2f}")
print(f"换手次数: {sw}  空仓占比: {cash*100:.1f}%")
print()

# 分年度收益和回撤
print("【分年度收益 + 当年最大回撤】")
print(f"{'年度':<8}{'年度收益':>10}{'当年最大回撤':>14}{'期末净值':>12}")
yrs={}
for d,v in zip(dates,values): yrs.setdefault(d[:4],[]).append((d,v))
prev_end=1.0
for y in sorted(yrs):
    yv=[v for _,v in yrs[y]]
    end=yv[-1]
    ret=end/prev_end-1
    # 当年回撤
    p=yv[0]; mdd=0
    for v in yv:
        if v>p:p=v
        dd=(v-p)/p
        if dd<mdd:mdd=dd
    print(f"{y:<8}{ret*100:>9.1f}%{mdd*100:>13.1f}%{end:>12.4f}")
    prev_end=end

# 持仓时间分布
from collections import Counter
cnt=Counter()
for d,hs in hold_log:
    for h in hs: cnt[label[h]]+=1
tot=sum(cnt.values())
print(f"\n【持仓时间分布】")
for l,c in cnt.most_common():
    print(f"  {l}: {c/tot*100:.1f}%  ({c}个交易日)")

# 前20次调仓明细
print(f"\n【前40次持仓切换明细】")
prev_holds=[]
n_shown=0
for d,hs in hold_log:
    if set(hs)!=set(prev_holds):
        prev_l = "空仓" if not prev_holds else "+".join(label[h] for h in prev_holds)
        new_l = "空仓" if not hs else "+".join(label[h] for h in hs)
        print(f"  {d}  {prev_l} -> {new_l}")
        n_shown+=1
        if n_shown>=40: break
    prev_holds=hs

print(f"\n(共{sw}次切换)")
