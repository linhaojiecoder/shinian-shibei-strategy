#!/usr/bin/env python3
"""v3 全局网格扫描：动量窗口 × 波动目标 × 波动窗口 × TOP_K × 过滤阈值
目标：在 v3(20日/15%/20日/TOP2/2%) 附近做系统扫描，找是否存在更优组合。
"""
import json, os, statistics, itertools
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "backtest_data", "prices_10y_open.json")

ETFS = [("510300","沪深300"),("159915","创业板"),("513100","纳指"),("513500","标普500"),("518880","黄金")]
NAMES = [c for c,_ in ETFS]
CAPITAL = 3_000_000
COST = 0.0008
START = "2016-01-01"
ANNF = 244 ** 0.5

data = json.load(open(DATA))
date_sets = [set(d for d,_ in data[n]) for n in NAMES]
DATES = sorted(set.intersection(*date_sets))
DATES = [d for d in DATES if d >= START]
close = {n:{d:v[1] for d,v in data[n]} for n in NAMES}
openp = {n:{d:v[0] for d,v in data[n]} for n in NAMES}

def is_friday(d):
    return datetime.strptime(d, "%Y-%m-%d").weekday() == 4

def is_biweekly(i):
    d = DATES[i]
    return is_friday(d) and (i // 5) % 2 == 0

def run(md, vol_target, vol_win, top_k, vol_limit):
    holdings = {}; cash = float(CAPITAL); nav_arr = []; pending = None; trades = 0
    for i, d in enumerate(DATES):
        if pending is not None:
            target, scale = pending
            total = cash + sum(h["shares"]*openp[c][d] for c,h in holdings.items())
            n = len(target)
            each = total*scale/n if n > 0 else 0.0
            for c in list(holdings):
                if c not in target:
                    h = holdings.pop(c)
                    cash += h["shares"]*openp[c][d]*(1-COST); trades += 1
            for c in target:
                p = openp[c][d]
                cur_sh = holdings.get(c,{}).get("shares",0); cur_v = cur_sh*p
                diff = each - cur_v
                if diff > p:
                    sh = int(diff/(p*(1+COST)))//100*100
                    if sh > 0:
                        old = holdings.get(c,{}).get("shares",0); oc = holdings.get(c,{}).get("cost",0)
                        ts = old+sh
                        holdings[c] = {"shares":ts,"cost":(old*oc+sh*p)/ts if ts>0 else p}
                        cash -= sh*p*(1+COST); trades += 1
                elif diff < -p:
                    sh = min(cur_sh, int((-diff)/(p*(1-COST)))//100*100)
                    if sh > 0:
                        ns = cur_sh-sh; cash += sh*p*(1-COST); trades += 1
                        if ns > 0: holdings[c]["shares"] = ns
                        else: holdings.pop(c,None)
            pending = None
        if i >= md and is_biweekly(i):
            metrics = {}
            for n in NAMES:
                mom = close[n][d]/close[n][DATES[i-md]]-1
                rets = [close[n][DATES[j]]/close[n][DATES[j-1]]-1 for j in range(i-vol_win+1,i+1)]
                m = sum(rets)/len(rets)
                v = (sum((r-m)**2 for r in rets)/len(rets))**0.5
                metrics[n] = (mom, v)
            ranked = sorted(NAMES, key=lambda n: metrics[n][0], reverse=True)
            target = [n for n in ranked[:top_k] if metrics[n][0] > 0 and metrics[n][1] <= vol_limit]
            nav_now = (cash + sum(h["shares"]*close[c][d] for c,h in holdings.items()))/CAPITAL
            combined = nav_arr + [nav_now]
            if len(combined) >= vol_win+1:
                rets = [combined[j]/combined[j-1]-1 for j in range(len(combined)-vol_win, len(combined))]
                m = sum(rets)/len(rets); v = (sum((r-m)**2 for r in rets)/len(rets))**0.5
                av = v*ANNF
                scale = max(0.0, min(1.0, vol_target/av)) if av > 0 else 1.0
            else:
                scale = 1.0
            pending = (target, scale)
        mv = sum(h["shares"]*close[c][d] for c,h in holdings.items())
        nav_arr.append((cash+mv)/CAPITAL)
    navs = nav_arr
    years = len(navs)/244
    ann = (navs[-1]/navs[0])**(1/years)-1
    peak = navs[0]; mdd = 0.0
    for v in navs:
        peak = max(peak,v); mdd = max(mdd,(peak-v)/peak)
    rets = [navs[i]/navs[i-1]-1 for i in range(1,len(navs))]
    sharpe = statistics.mean(rets)/statistics.pstdev(rets)*ANNF if statistics.pstdev(rets)>0 else 0
    calmar = (ann*100)/(mdd*100) if mdd>0 else 0
    # 2026年收益
    y26 = [navs[i] for i in range(len(navs)) if DATES[i][:4]=="2026"]
    ret26 = (y26[-1]/y26[0]-1)*100 if len(y26)>1 else 0.0
    return dict(ann=ann*100, mdd=mdd*100, sharpe=sharpe, calmar=calmar,
                trades=trades, final=navs[-1]*CAPITAL, ret26=ret26)

# 扫描网格
grid = itertools.product(
    [20, 30, 40, 60],        # 动量窗口
    [0.10, 0.12, 0.15, 0.18],# 波动目标
    [10, 20, 40, 60],        # 波动窗口
    [2],                     # TOP_K（先固定2，重点看其他维）
    [0.02],                  # 过滤阈值
)
results = []
for md, vt, vw, tk, vl in grid:
    r = run(md, vt, vw, tk, vl)
    r.update(md=md, vt=vt, vw=vw, tk=tk, vl=vl)
    results.append(r)

results.sort(key=lambda x: -x["calmar"])
print(f"共 {len(results)} 组，按卡玛排序 TOP20：")
print(f"{'动量':>4}{'波动目标':>8}{'波动窗':>6}{'年化':>8}{'回撤':>8}{'夏普':>7}{'卡玛':>7}{'2026':>8}{'期末':>10}")
for r in results[:20]:
    print(f"{r['md']:>4}{r['vt']*100:>7.0f}%{r['vw']:>6}{r['ann']:>7.2f}%{-r['mdd']:>7.2f}%"
          f"{r['sharpe']:>7.2f}{r['calmar']:>7.3f}{r['ret26']:>7.2f}%{r['final']:>10,.0f}")

# 标记基线
base = [r for r in results if r['md']==20 and r['vt']==0.15 and r['vw']==20]
print("\n=== 基线 v3 (20/15%/20) ===")
for b in base:
    print(f"年化{b['ann']:.2f}% 回撤-{b['mdd']:.2f}% 夏普{b['sharpe']:.2f} 卡玛{b['calmar']:.3f} 2026{b['ret26']:+.2f}%")

# 按年化排序 TOP10
print("\n=== 按年化排序 TOP10 ===")
for r in sorted(results, key=lambda x:-x['ann'])[:10]:
    print(f"md{r['md']} vt{r['vt']*100:.0f}% vw{r['vw']}: 年化{r['ann']:.2f}% 回撤-{r['mdd']:.2f}% 卡玛{r['calmar']:.3f} 2026{r['ret26']:+.2f}%")

json.dump(results, open(os.path.join(BASE,"backtest_data","grid_scan_v3.json"),"w"), ensure_ascii=False, indent=1)
