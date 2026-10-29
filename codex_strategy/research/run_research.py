#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prespecified V1 comparisons with chronological holdout and truncation checks."""
import copy
import hashlib
import html
import json
import math
from pathlib import Path
import engine

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'v1/data_20261029.json'
OUT = ROOT / 'research/results.json'
REPORT = ROOT / 'research/report.html'
CUT = '2020-12-31'


def score(ledger):
    first, last = ledger[0], ledger[-1]
    days = (engine.dt.date.fromisoformat(last['date'])-engine.dt.date.fromisoformat(first['date'])).days
    ratio = last['total']/first['total']
    ann = (ratio**(365.2425/days)-1)*100
    peak, drawdown = first['total'], 0
    for row in ledger:
        peak = max(peak, row['total'])
        drawdown = max(drawdown, (peak-row['total'])/peak)
    return {'return_pct':(ratio-1)*100,'cagr_pct':ann,'max_drawdown_pct':drawdown*100,
            'calmar':ann/(drawdown*100) if drawdown else None}


def combine(left, right):
    ledger=[]
    for a,b in zip(left['ledger'],right['ledger']):
        assert a['date']==b['date']
        ledger.append({'date':a['date'],'total':a['total']+b['total'],
                       'cash':a['cash']+b['cash'],'receivable':a['receivable']+b['receivable']})
    return {'ledger':ledger,'trades':len(left['orders'])+len(right['orders']),
            'signals':left['signals']+right['signals'], 'orders':left['orders']+right['orders']}


def run_all(prices,days,actions,indices,fee,slip):
    opts={'fee':fee,'slip':slip}
    v1=engine.simulate(prices,days,actions,indices,**opts)
    base={'ledger':v1['ledger'],'trades':len(v1['orders']),'signals':v1['signals'],'orders':v1['orders']}
    cap=engine.simulate(prices,days,actions,indices,us_cap=.5,**opts)
    constrained={'ledger':cap['ledger'],'trades':len(cap['orders']),'signals':cap['signals'],'orders':cap['orders']}
    parts=[engine.simulate(prices,days,actions,indices,schedule='calendar',phase=phase,capital=engine.INITIAL/2,**opts) for phase in (0,1)]
    stagger=combine(*parts)
    parts_cap=[engine.simulate(prices,days,actions,indices,schedule='calendar',phase=phase,capital=engine.INITIAL/2,us_cap=.5,**opts) for phase in (0,1)]
    stagger_cap=combine(*parts_cap)
    return {'V1':base,'US_cap_50':constrained,'staggered':stagger,'staggered_US_cap_50':stagger_cap}


def assert_no_future(data,prices,days,actions,indices,full):
    # Compare each day's signal-index prefix against a prefix reconstructed from raw
    # prices and events available on or before that day. Reuse cumulative calculations
    # only after verifying the recurrence; no future corporate event can affect a prefix.
    for code in engine.CODES:
        own=sorted(prices[code]); loc={day:i for i,day in enumerate(own)}
        acc=1.0
        for i in range(1,len(days)):
            for day in own[loc[days[i-1]]+1:loc[days[i]]+1]:
                previous=own[loc[day]-1]
                ratio,dividend=1.0,0.0
                for kind,event in actions.get((code,day),[]):
                    if kind=='split': ratio*=event['ratio']
                    else: dividend+=event['amount_per_share']
                acc*= (prices[code][day][1]*ratio+dividend)/prices[code][previous][1]
            assert math.isclose(acc,indices[code][i],rel_tol=1e-12)
    # Full simulation rerun at every historical signal date, deleting all future
    # price rows and future action records before constructing signals and orders.
    signal_days=sorted({x['date'] for result in full.values() for x in result['signals']})
    for day in signal_days:
        prefix=copy.deepcopy(data)
        for code in engine.CODES:
            prefix['prices'][code]=[x for x in prefix['prices'][code] if x[0]<=day]
            prefix['actions'][code]['dividends']=[x for x in prefix['actions'][code]['dividends'] if x['ex_date']<=day]
            prefix['actions'][code]['splits']=[x for x in prefix['actions'][code]['splits'] if x['date']<=day]
        p,d,a,idx=engine.prepare(prefix)
        for code in engine.CODES:
            assert math.isclose(idx[code][-1],indices[code][len(d)-1],rel_tol=1e-12)
        # One full strategy rerun per signal date proves earlier V1 signals and orders
        # are identical when future prices and corporate actions are absent.
        truncated=run_all(p,d,a,idx,.0008,0)
        for name,expected in full.items():
            for field in ('signals','orders'):
                assert truncated[name][field]==[x for x in expected[field] if x['date']<=day], (day,name,field)
            assert math.isclose(truncated[name]['ledger'][-1]['total'],expected['ledger'][len(d)-1]['total'],rel_tol=1e-12)
    return len(days),len(signal_days)


def main():
    raw=DATA.read_bytes(); data=json.loads(raw)
    prices,days,actions,indices=engine.prepare(data)
    normal=run_all(prices,days,actions,indices,.0008,0)
    print('checking causal prefixes...',flush=True)
    counts=assert_no_future(data,prices,days,actions,indices,normal)
    print('causal checks',counts,flush=True)
    high=run_all(prices,days,actions,indices,.0016,.001)
    summary={}
    for name,result in normal.items():
        insample=[x for x in result['ledger'] if x['date']<=CUT]
        holdout=[x for x in result['ledger'] if x['date']>CUT]
        summary[name]={'full':score(result['ledger']),'through_2020':score(insample),
                       '2021_onward':score(holdout),'high_cost':score(high[name]['ledger']),
                       'trades':result['trades']}
        print(name,json.dumps(summary[name],ensure_ascii=False),flush=True)
    output={'data_sha256':hashlib.sha256(raw).hexdigest(),'date_start':days[0],'date_end':days[-1],
            'chronology':{'research_cutoff':CUT,'holdout':'2021-01-01 onward; exploratory, not blind because history already known',
                          'causal_daily_recurrence_checks':counts[0],'all_strategies_signal_date_prefix_reruns':counts[1]},
            'definitions':{'V1':'original index-parity Friday','US_cap_50':'V1 with US ETF combined target <= 50% equity; remainder cash',
                           'staggered':'50/50 independent sleeves on alternate calendar Fridays; each sleeve estimates its own vol',
                           'staggered_US_cap_50':'staggered sleeves with each US target <= 50% of sleeve equity'},
            'summary':summary,'series':{k:v['ledger'] for k,v in normal.items()}}
    OUT.write_text(json.dumps(output,ensure_ascii=False,separators=(',',':')))
    rows=[]
    names={'V1':'V1 原日历','US_cap_50':'原日历 + 美股上限50%','staggered':'错峰双账户','staggered_US_cap_50':'错峰 + 美股上限50%'}
    for name,item in summary.items():
        f,h,c=item['full'],item['2021_onward'],item['high_cost']
        rows.append(f"<tr><td>{html.escape(names[name])}</td><td>{f['cagr_pct']:.2f}%</td><td>-{f['max_drawdown_pct']:.2f}%</td><td>{f['calmar']:.2f}</td><td>{h['cagr_pct']:.2f}% / -{h['max_drawdown_pct']:.2f}%</td><td>{c['cagr_pct']:.2f}% / -{c['max_drawdown_pct']:.2f}%</td><td>{item['trades']}</td></tr>")
    report='''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>慢富十倍 · V2研究</title><style>body{background:#101722;color:#edf2fa;font:16px system-ui}main{max-width:1200px;margin:auto;padding:28px}h1{color:#edc65d}p,li{line-height:1.75;color:#c4cede}.note{background:#30251e;border-left:4px solid #e3a058;padding:16px}.scroll{overflow:auto}table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:right;padding:10px;border-bottom:1px solid #344052}th:first-child,td:first-child{text-align:left}</style></head><body><main><h1>慢富十倍 · 独立优化研究</h1><p>2014-01-15 至 2026-10-29 ｜ 历史模拟，不是投资建议</p><div class="note">错峰方案是两份独立子账户，各自测算波动率；不是简单把两条净值曲线平均。2021年以后分段已被研究者看到，不能称为严格盲测。数据来自冻结快照，价格差异、停牌和真实成交约束尚待核实。</div><h2>对照与稳健性</h2><div class="scroll"><table><tr><th>策略</th><th>全区间年化</th><th>全区间最大回撤</th><th>收益回撤比</th><th>2021年后 年化/回撤</th><th>高成本 年化/回撤</th><th>交易笔数</th></tr>ROWS</table></div><h2>测试和前提</h2><ul><li>V1、50%美股ETF组合目标上限、双周错峰和两者结合，候选在本次比较前固定；未进行大规模参数网格搜索。该上限仅约束调仓目标，持仓随价格变动仍可能超过50%。</li><li>逐日信号价格递推因果检查；对所有历史信号日删除之后的价格和公司事件，独立重跑全部候选并核对当日账本、历史订单与信号。此检查不等于所有潜在前视偏差均已排除。</li><li>主成本每侧0.08%；高成本每侧0.16%另加0.10%滑点。不能真实模拟涨跌停、停牌、容量冲击、QDII溢价，基金分红实际到账需核对。</li><li>分段统计以区间首日收盘净值为起点，含历史延续持仓；非独立新建账户，不是未曾看过的样本外实验。</li></ul></main></body></html>'''
    REPORT.write_text(report.replace('ROWS',''.join(rows)))
    print('saved',OUT,REPORT)


if __name__=='__main__': main()
