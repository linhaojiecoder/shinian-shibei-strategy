#!/usr/bin/env python3
"""动态仓位 / 波动率目标机制测试
基线：无止损 · 双周调仓 · 20日动量 · TOP2 · 波动过滤(>2%剔除)
     年化 20.72% | 回撤 -17.01% | 夏普 1.13 | 卡玛 1.219

机制：不改变选股（20日动量 TOP2），只根据市场状态动态调整「总仓位比例 scale∈[0,1]」，
     TOP2 内部仍等权。T日收盘算信号(含scale)，T+1日开盘成交，消除前视偏差。
"""
import json, os, statistics
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "backtest_data", "prices_10y_open.json")
OUT = os.path.join(BASE, "backtest_data", "dynalloc_agent.json")

ETFS = [("510300","沪深300"),("159915","创业板"),("513100","纳指"),("513500","标普500"),("518880","黄金")]
NAMES = [c for c,_ in ETFS]
LABEL = {c:n for c,n in ETFS}
CAPITAL = 3_000_000
MD = 20        # 动量窗口
VOL_N = 20     # 波动率窗口
VOL_LIMIT = 0.02
TOP_K = 2
COST = 0.0008
START = "2016-01-01"
TRADING_DAYS = 244

data = json.load(open(DATA))
date_sets = [set(d for d,_ in data[n]) for n in NAMES]
DATES = sorted(set.intersection(*date_sets))
DATES = [d for d in DATES if d >= START]
CLOSE = {n:{d:v[1] for d,v in data[n]} for n in NAMES}
OPENP = {n:{d:v[0] for d,v in data[n]} for n in NAMES}

def is_friday(d):
    return datetime.strptime(d, "%Y-%m-%d").weekday() == 4

def is_biweekly(i):
    d = DATES[i]
    return is_friday(d) and (i // 5) % 2 == 0

# ---------------- scale 策略 ----------------
def scale_full(ctx):
    return 1.0

def scale_voltarget(tgt_ann, window):
    def fn(ctx):
        nav = ctx["nav_arr"]
        if len(nav) < window + 1:
            return 1.0
        rets = [nav[j]/nav[j-1]-1 for j in range(len(nav)-window, len(nav))]
        m = sum(rets)/len(rets)
        vol = (sum((r-m)**2 for r in rets)/len(rets))**0.5
        ann_vol = vol*(TRADING_DAYS**0.5)
        if ann_vol <= 0:
            return 1.0
        return max(0.0, min(1.0, tgt_ann/ann_vol))
    return fn

def scale_ma_switch(ma_short, ma_long):
    def fn(ctx):
        nav = ctx["nav_arr"]
        if len(nav) < ma_long:
            return 1.0
        cur = nav[-1]
        ma_s = sum(nav[-ma_short:])/ma_short
        ma_l = sum(nav[-ma_long:])/ma_long
        if cur >= ma_s: return 1.0
        elif cur >= ma_l: return 0.5
        else: return 0.0
    return fn

def scale_dd_gradient():
    def fn(ctx):
        nav = ctx["nav_arr"]
        cur = nav[-1]
        peak = max(nav)
        dd = (peak-cur)/peak if peak > 0 else 0.0   # 正数
        if dd <= 0.05: return 1.0
        elif dd <= 0.10: return 0.75
        elif dd <= 0.15: return 0.50
        else: return 0.25
    return fn

def scale_trend(thresh, use_min=True):
    def fn(ctx):
        moms = ctx["selected_mom"]
        if not moms: return 0.0
        m = min(moms) if use_min else (sum(moms)/len(moms))
        return max(0.0, min(1.0, m/thresh))
    return fn

def compose(*fns):
    def fn(ctx):
        return min(f(ctx) for f in fns)
    return fn

# ---------------- 回测引擎 ----------------
def backtest(scale_fn):
    holdings = {}          # code -> shares
    cash = float(CAPITAL)
    navs = []
    pending = None
    trades = 0

    for i, d in enumerate(DATES):
        # 1) 执行 T-1 日信号（T 日开盘成交）
        if pending is not None:
            target, scale = pending
            openp = {n: OPENP[n][d] for n in NAMES}
            total = cash + sum(hs*openp[c] for c, hs in holdings.items())
            n = len(target)
            each = total*scale/n if n > 0 else 0.0
            # 卖出不在目标内的
            for c in list(holdings):
                if c not in target:
                    hs = holdings.pop(c)
                    cash += hs*openp[c]*(1-COST)
                    trades += 1
            # 对目标内标的调至目标权重
            for c in target:
                p = openp[c]
                cur = holdings.get(c, 0)
                diff = each - cur*p
                if diff > 0:
                    sh = int(diff/(p*(1+COST)))//100*100
                    if sh > 0:
                        holdings[c] = cur + sh
                        cash -= sh*p*(1+COST)
                        trades += 1
                elif diff < 0:
                    sh = min(cur, int((-diff)/(p*(1-COST)))//100*100)
                    if sh > 0:
                        new = cur - sh
                        cash += sh*p*(1-COST)
                        trades += 1
                        if new > 0: holdings[c] = new
                        else: holdings.pop(c, None)
            pending = None

        # 2) 双周调仓信号（T 日收盘算，含 scale）
        if i >= MD and is_biweekly(i):
            metrics = {}
            for n in NAMES:
                mom = CLOSE[n][d]/CLOSE[n][DATES[i-MD]] - 1
                rets = [CLOSE[n][DATES[j]]/CLOSE[n][DATES[j-1]]-1 for j in range(i-VOL_N+1, i+1)]
                m = sum(rets)/len(rets)
                vol = (sum((r-m)**2 for r in rets)/len(rets))**0.5
                metrics[n] = (mom, vol)
            ranked = sorted(NAMES, key=lambda n: metrics[n][0], reverse=True)
            target = [n for n in ranked[:TOP_K] if metrics[n][0] > 0 and metrics[n][1] <= VOL_LIMIT]
            nav_now = (cash + sum(hs*CLOSE[c][d] for c, hs in holdings.items()))/CAPITAL
            ctx = {"nav_arr": navs + [nav_now],
                   "selected_mom": [metrics[n][0] for n in target],
                   "i": i}
            scale = scale_fn(ctx)
            pending = (target, scale)

        # 3) 记录收盘净值
        mv = sum(hs*CLOSE[c][d] for c, hs in holdings.items())
        navs.append((cash+mv)/CAPITAL)

    years = len(navs)/TRADING_DAYS
    ann = ((navs[-1]/navs[0])**(1/years)-1)*100
    peak = navs[0]; mdd = 0.0
    for v in navs:
        peak = max(peak, v); mdd = max(mdd, (peak-v)/peak)
    rets = [navs[j]/navs[j-1]-1 for j in range(1, len(navs))]
    sharpe = statistics.mean(rets)/statistics.pstdev(rets)*(TRADING_DAYS**0.5) if statistics.pstdev(rets) > 0 else 0.0
    calmar = ann/(mdd*100) if mdd > 0 else 0.0
    return dict(ann=ann, mdd=mdd*100, sharpe=sharpe, calmar=calmar, trades=trades,
                final=navs[-1]*CAPITAL, navs=navs)

# ---------------- 测试配置 ----------------
def build_configs():
    cfgs = []
    cfgs.append(("基准·满仓", scale_full))
    # 1) 波动率目标
    for t in (0.10, 0.12, 0.15):
        for w in (20, 60):
            cfgs.append((f"波动率目标 {int(t*100)}%·{w}日", scale_voltarget(t, w)))
    # 2) 市场状态开关
    for s, l in ((60,120),(60,250),(120,250),(120,200)):
        cfgs.append((f"MA开关 {s}/{l}日", scale_ma_switch(s, l)))
    # 3) 回撤梯度降仓
    cfgs.append(("回撤梯度降仓(-5/-10/-15%)", scale_dd_gradient()))
    # 4) 趋势强度加权
    for th in (0.02, 0.05, 0.10):
        cfgs.append((f"趋势加权·min·阈值{int(th*100)}%", scale_trend(th, True)))
    cfgs.append(("趋势加权·均值·阈值5%", scale_trend(0.05, False)))
    # 组合
    cfgs.append(("MA60/250 + 波动率目标12%", compose(scale_ma_switch(60,250), scale_voltarget(0.12,20))))
    cfgs.append(("回撤梯度 + 波动率目标12%", compose(scale_dd_gradient(), scale_voltarget(0.12,20))))
    return cfgs

def main():
    cfgs = build_configs()
    results = []
    for name, fn in cfgs:
        r = backtest(fn)
        r["name"] = name
        results.append(r)

    results.sort(key=lambda r: r["calmar"], reverse=True)

    print("="*104)
    print(f"{'方案':<34}{'年化':>8}{'回撤':>8}{'夏普':>7}{'卡玛':>7}{'交易':>6}")
    print("-"*104)
    for r in results:
        print(f"{r['name']:<34}{r['ann']:7.2f}%{r['mdd']:7.2f}%{r['sharpe']:7.2f}{r['calmar']:7.3f}{r['trades']:6d}")

    json.dump([{k: (round(v,4) if isinstance(v,float) else v) for k,v in r.items() if k!='navs'}
               for r in results], open(OUT,"w"), ensure_ascii=False, indent=1)
    print(f"\n已保存 {OUT}")

if __name__ == "__main__":
    main()
