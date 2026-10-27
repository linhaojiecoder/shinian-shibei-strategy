#!/usr/bin/env python3
"""市场状态开关测试：解决"明知市场差还硬买"的问题
基线 v3：双周 · 20日动量 · TOP2 · 波动率目标15%
        年化21.20% ｜ 回撤-14.11% ｜ 卡玛1.503 ｜ 2026:-1.78%

测试空仓开关（等权篮子跌破长期均线→全空仓，站上再恢复）：
  S1: 篮子破MA200全空仓
  S2: 篮子破MA120全空仓
  S3: 篮子破MA200→空仓但保留黄金(避险)
  S4: 篮子破MA200全空仓 + 绝对动量阈值升级(20日动量>货基0.16%才买)

成交：T日收盘算信号，T+1日开盘成交。
"""
import json, os, statistics
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "backtest_data", "prices_10y_open.json")
OUT = os.path.join(BASE, "backtest_data", "market_switch_results.json")

ETFS = [("510300","沪深300"),("159915","创业板"),("513100","纳指"),("513500","标普500"),("518880","黄金")]
NAMES = [c for c,_ in ETFS]
CAPITAL = 3_000_000
MD=20; VOL_N=20; VOL_LIMIT=0.02; TOP_K=2; COST=0.0008; START='2016-01-01'
VOL_TARGET=0.15; VOL_WIN=20; ANNF=244**0.5

data = json.load(open(DATA))
ds=[set(d for d,_ in data[n]) for n in NAMES]
DATES=sorted(set.intersection(*ds)); DATES=[d for d in DATES if d>=START]
CLOSE={n:{d:v[1] for d,v in data[n]} for n in NAMES}
OPENP={n:{d:v[0] for d,v in data[n]} for n in NAMES}

# 等权篮子（归一化起点=1）
BASKET=[]
for d in DATES:
    BASKET.append(sum(CLOSE[n][d]/CLOSE[n][DATES[0]] for n in NAMES)/len(NAMES))

def ma(arr,w):
    out=[None]*len(arr); s=0.0
    for i in range(len(arr)):
        s+=arr[i]
        if i>=w: s-=arr[i-w]
        if i>=w-1: out[i]=s/w
    return out
BMA={w:ma(BASKET,w) for w in (120,200)}

def is_fri(d): return datetime.strptime(d,'%Y-%m-%d').weekday()==4
def is_bi(i): d=DATES[i]; return is_fri(d) and (i//5)%2==0

def vol_scale(nav_arr,nav_now):
    c=nav_arr+[nav_now]
    if len(c)>=VOL_WIN+1:
        r=[c[j]/c[j-1]-1 for j in range(len(c)-VOL_WIN,len(c))]
        m=sum(r)/len(r); v=(sum((x-m)**2 for x in r)/len(r))**0.5
        av=v*ANNF; return max(0.0,min(1.0,VOL_TARGET/av)) if av>0 else 1.0
    return 1.0

def run(switch_ma=None, keep_gold=False, abs_thresh=0.0):
    holdings={}; cash=float(CAPITAL); nav_arr=[]; trades=0; pending=None
    for i,d in enumerate(DATES):
        if i>0 and pending is not None:
            target,scale=pending; total=cash+sum(h['shares']*OPENP[c][d] for c,h in holdings.items())
            n=len(target); each=total*scale/n if n>0 else 0.0
            for c in list(holdings):
                if c not in target:
                    h=holdings.pop(c); p=OPENP[c][d]; cash+=h['shares']*p*(1-COST); trades+=1
            for c in target:
                p=OPENP[c][d]; cur=holdings.get(c,{}).get('shares',0); cv=cur*p; diff=each-cv
                if diff>p:
                    sh=int(diff/(p*(1+COST)))//100*100
                    if sh>0:
                        old=holdings.get(c,{}).get('shares',0); oc=holdings.get(c,{}).get('cost',0)
                        ts=old+sh; holdings[c]={'shares':ts,'cost':(old*oc+sh*p)/ts if ts>0 else p}; cash-=sh*p*(1+COST); trades+=1
                elif diff<-p:
                    sh=min(cur,int((-diff)/(p*(1-COST)))//100*100)
                    if sh>0:
                        ns=cur-sh; cash+=sh*p*(1-COST); trades+=1
                        if ns>0: holdings[c]['shares']=ns
                        else: holdings.pop(c,None)
            pending=None

        if i>=MD and is_bi(i):
            # 市场状态判断
            market_bad = False
            if switch_ma is not None:
                bm = BMA[switch_ma][i]
                if bm is not None and BASKET[i] < bm:
                    market_bad = True
            if market_bad:
                target = ['518880'] if keep_gold else []  # 保留黄金或全空仓
                pending=(target, 1.0 if keep_gold else 1.0)
            else:
                met={}
                for n in NAMES:
                    mom=CLOSE[n][d]/CLOSE[n][DATES[i-MD]]-1
                    r=[CLOSE[n][DATES[j]]/CLOSE[n][DATES[j-1]]-1 for j in range(i-VOL_N+1,i+1)]
                    m=sum(r)/len(r); v=(sum((x-m)**2 for x in r)/len(r))**0.5
                    met[n]=(mom,v)
                ranked=sorted(NAMES,key=lambda n:met[n][0],reverse=True)
                target=[n for n in ranked[:TOP_K] if met[n][0]>abs_thresh and met[n][1]<=VOL_LIMIT]
                nav_now=(cash+sum(h['shares']*CLOSE[c][d] for c,h in holdings.items()))/CAPITAL
                scale=vol_scale(nav_arr,nav_now)
                pending=(target,scale)
        mv=sum(h['shares']*CLOSE[c][d] for c,h in holdings.items()); nav_arr.append((cash+mv)/CAPITAL)

    years=len(nav_arr)/244; ann=((nav_arr[-1]/nav_arr[0])**(1/years)-1)*100
    peak=nav_arr[0]; mdd=0.0
    for v in nav_arr: peak=max(peak,v); mdd=max(mdd,(peak-v)/peak)
    r=[nav_arr[j]/nav_arr[j-1]-1 for j in range(1,len(nav_arr))]
    sp=statistics.mean(r)/statistics.pstdev(r)*ANNF if statistics.pstdev(r)>0 else 0
    cal=ann/(mdd*100) if mdd>0 else 0
    # 2026 YTD
    y26=[nav_arr[j] for j in range(len(nav_arr)) if DATES[j][:4]=='2026']
    ytd26=(y26[-1]/y26[0]-1)*100 if y26 else 0
    return ann,mdd*100,sp,cal,trades,nav_arr[-1]*CAPITAL,ytd26

def main():
    print("市场状态开关测试（解决'明知差还硬买'）\n")
    configs=[
        ("基线 v3（无开关）", dict()),
        ("S1: 篮子破MA200全空仓", dict(switch_ma=200)),
        ("S2: 篮子破MA120全空仓", dict(switch_ma=120)),
        ("S3: 破MA200空仓但留黄金", dict(switch_ma=200, keep_gold=True)),
        ("S4: 破MA200空仓+动量阈值0.16%", dict(switch_ma=200, abs_thresh=0.0016)),
        ("S5: 仅绝对动量阈值0.16%(不空仓)", dict(abs_thresh=0.0016)),
    ]
    print(f"{'方案':<32}{'年化':>8}{'回撤':>8}{'夏普':>7}{'卡玛':>7}{'交易':>6}{'期末':>12}{'26YTD':>8}")
    print("-"*100)
    results=[]
    for name,cfg in configs:
        a,m,s,c,t,f,y=run(**cfg)
        results.append({'name':name,'ann':a,'mdd':m,'sharpe':s,'calmar':c,'trades':t,'final':f,'ytd26':round(y,2)})
        print(f"{name:<32}{a:>7.2f}%{-m:>7.2f}%{s:>7.2f}{c:>7.3f}{t:>6d}{f:>12,.0f}{y:>+7.2f}%")

    ss=sorted(results,key=lambda r:r['calmar'],reverse=True)
    print("\n按卡玛排序：")
    for r in ss:
        print(f"  {r['name']:<32} 卡玛 {r['calmar']:.3f} ｜ 2026 {r['ytd26']:+.2f}%")

    json.dump(results,open(OUT,'w'),ensure_ascii=False,indent=2)
    print(f"\n已保存 {OUT}")

if __name__=="__main__":
    main()
