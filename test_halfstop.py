#!/usr/bin/env python3
"""测试软止损：跌破MA减半仓，涨回买回"""
import json, os
from datetime import datetime
import statistics

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "backtest_data", "prices_10y_open.json")

NAMES = ["510300","159915","513100","513500","518880"]
LABEL = {"510300":"沪深300","159915":"创业板","513100":"纳指","513500":"标普500","518880":"黄金"}
CAPITAL = 3_000_000
COST = 0.0008
START = "2016-01-01"

data = json.load(open(DATA))
date_sets = [set(d for d,_ in data[n]) for n in NAMES]
DATES = sorted(set.intersection(*date_sets))
DATES = [d for d in DATES if d >= START]
CLOSE = {n:{d:v[1] for d,v in data[n]} for n in NAMES}
OPENP = {n:{d:v[0] for d,v in data[n]} for n in NAMES}

def is_friday(d):
    return datetime.strptime(d, "%Y-%m-%d").weekday() == 4

def rebalance_day(i, freq):
    d = DATES[i]
    if freq == 'weekly':
        return is_friday(d)
    elif freq == 'biweekly':
        return is_friday(d) and (i // 5) % 2 == 0
    elif freq == 'monthly':
        return d[5:7] != DATES[i-1][5:7] if i > 0 else False
    return False

def stats(navs):
    years = len(navs)/244
    ann = ((navs[-1]/navs[0])**(1/years)-1)*100
    peak = navs[0]; mdd = 0
    for v in navs:
        peak = max(peak, v); mdd = max(mdd, (peak-v)/peak)
    rets = [navs[i]/navs[i-1]-1 for i in range(1,len(navs))]
    sharpe = statistics.mean(rets)/statistics.pstdev(rets)*(244**0.5) if statistics.pstdev(rets)>0 else 0
    calmar = ann/(mdd*100) if mdd>0 else 0
    return ann, mdd*100, sharpe, calmar


def backtest(ma_n, freq, md, top_k, vol_on, half_stop=False):
    """half_stop: 跌破MA减半仓，涨回MA上方买回"""
    holdings = {}
    cash = CAPITAL
    nav_series = []
    pending_target = None
    pending_stop = set()
    trade_count = 0
    target_shares = {}

    for i, d in enumerate(DATES):
        # ==== 执行昨日决定的调仓（次日开盘成交）====
        if i > 0 and (pending_target is not None or pending_stop):
            for code in list(pending_stop):
                if code in holdings:
                    h = holdings.pop(code)
                    p = OPENP[code][d]
                    cash += h["shares"] * p * (1 - COST)
                    trade_count += 1
                    target_shares.pop(code, None)
            if pending_target is not None:
                for code in list(holdings.keys()):
                    if code not in pending_target and code not in pending_stop:
                        h = holdings.pop(code)
                        p = OPENP[code][d]
                        cash += h["shares"]*p*(1-COST)
                        trade_count += 1
                        target_shares.pop(code, None)
                if pending_target:
                    mv = sum(holdings[c]["shares"]*OPENP[c][d] for c in holdings)
                    total = cash + mv
                    each = total / len(pending_target)
                    for code in pending_target:
                        p = OPENP[code][d]
                        cur = holdings.get(code, {}).get("shares", 0)
                        diff = each - cur*p
                        if diff > p:
                            sh = int(diff/(p*(1+COST)))//100*100
                            if sh > 0:
                                holdings[code] = {"shares": holdings.get(code,{}).get("shares",0) + sh}
                                cash -= sh*p*(1+COST)
                                trade_count += 1
                    target_shares = {c: holdings.get(c,{}).get("shares",0) for c in pending_target}
            pending_target = None
            pending_stop = set()

        # ==== 软止损：跌破MA减半，涨回买回 ====
        if half_stop and ma_n > 0 and i >= ma_n:
            for code in list(holdings.keys()):
                ma = sum(CLOSE[code][DATES[j]] for j in range(i-ma_n+1, i+1)) / ma_n
                cur_sh = holdings[code]["shares"]
                if CLOSE[code][d] < ma:
                    # 跌破：减半仓（次日开盘执行）
                    if cur_sh > 100 and (i+1) < len(DATES):
                        sell_sh = (cur_sh//100//2)*100
                        if sell_sh > 0:
                            p = OPENP[code][DATES[i+1]]
                            holdings[code] = {"shares": cur_sh - sell_sh}
                            cash += sell_sh*p*(1-COST)
                            trade_count += 1
                            target_shares[code] = cur_sh - sell_sh
                elif CLOSE[code][d] > ma and code in target_shares:
                    # 涨回：买回目标仓
                    tgt = target_shares[code]
                    if cur_sh < tgt*0.9 and (i+1) < len(DATES):
                        p = OPENP[code][DATES[i+1]]
                        buy_sh = (tgt - cur_sh)//100*100
                        if buy_sh > 0:
                            holdings[code] = {"shares": cur_sh + buy_sh}
                            cash -= buy_sh*p*(1+COST)
                            trade_count += 1

        # ==== 周期调仓：计算动量目标 ====
        if rebalance_day(i, freq) and i >= md:
            metrics = {}
            for n in NAMES:
                mom = CLOSE[n][d] / CLOSE[n][DATES[i-md]] - 1
                ma = sum(CLOSE[n][DATES[j]] for j in range(i-ma_n+1, i+1))/ma_n if ma_n > 0 else 0
                rets = [CLOSE[n][DATES[j]]/CLOSE[n][DATES[j-1]]-1 for j in range(i-20+1, i+1)]
                m = sum(rets)/len(rets)
                vol = (sum((r-m)**2 for r in rets)/len(rets))**0.5
                above = CLOSE[n][d] > ma if ma_n > 0 else True
                metrics[n] = {"mom": mom, "above": above, "vol": vol}
            ranked = sorted(NAMES, key=lambda n: metrics[n]["mom"], reverse=True)
            target = []
            for n in ranked[:top_k]:
                if metrics[n]["mom"] > 0 and metrics[n]["above"]:
                    if vol_on and metrics[n]["vol"] > 0.02:
                        continue
                    target.append(n)
            pending_target = target

        mv = sum(holdings[c]["shares"]*CLOSE[c][d] for c in holdings)
        nav_series.append((cash + mv) / CAPITAL)

    return stats(nav_series) + (trade_count,)


if __name__ == "__main__":
    print("="*95)
    print("软止损（破MA减半仓 / 涨回买回）对比测试")
    print("="*95)
    configs = [
        ("基准: 无止损·双周·TOP2·20日",     0,   'biweekly', 20, 2, True,  False),
        ("软止损 MA20减半·双周·TOP2",       20,  'biweekly', 20, 2, True,  True),
        ("软止损 MA20减半·周频·TOP3",       20,  'weekly',   20, 3, True,  True),
        ("软止损 MA60减半·双周·TOP2",       60,  'biweekly', 20, 2, True,  True),
        ("软止损 MA120减半·双周·TOP2",      120, 'biweekly', 20, 2, True,  True),
        ("硬止损 MA20清仓·周频·TOP3(参考)",  20,  'weekly',   20, 3, True,  False),
    ]
    print(f"{'配置':<32}{'年化':>8}{'回撤':>8}{'夏普':>7}{'卡玛':>7}{'交易':>6}")
    for name, ma_n, freq, md, topk, vol, hs in configs:
        ann, mdd, sharpe, calmar, trades = backtest(ma_n, freq, md, topk, vol, hs)
        print(f"{name:<32}{ann:7.2f}%{mdd:7.2f}%{sharpe:7.2f}{calmar:7.3f}{trades:6d}")
