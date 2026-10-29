#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fresh-data, event-driven cash ETF backtest; independent from other engines."""
import collections
import datetime as dt
import hashlib
import html
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INPUT = ROOT / 'fresh_market_data_20261029.json'
RESULT = ROOT / 'rebuilt_backtest_results.json'
REPORT = ROOT / 'rebuilt_backtest_report.html'
INITIAL = 3000000.0
CODES = ['510300', '159915', '513100', '513500', '518880']
LABELS = {'510300': '沪深300ETF', '159915': '创业板ETF', '513100': '纳指ETF',
          '513500': '标普500ETF', '518880': '黄金ETF'}


def prepare(data):
    prices = {code: dict(data['prices'][code]) for code in CODES}
    dates = sorted(set.intersection(*(set(prices[code]) for code in CODES)))
    actions = collections.defaultdict(list)
    for code in CODES:
        for dividend in data['actions'][code]['dividends']:
            if dividend['ex_date'] >= dates[0]:
                actions[(code, dividend['ex_date'])].append(('dividend', dividend))
        for split in data['actions'][code]['splits']:
            if split['date'] < dates[0]:
                continue
            anchor = next(day for day in sorted(prices[code]) if day >= split['date'])
            actions[(code, anchor)].append(('split', split))
    indices = {code: [1.0] for code in CODES}
    for code in CODES:
        own = sorted(prices[code])
        loc = {day: i for i, day in enumerate(own)}
        for pos in range(1, len(dates)):
            factor = 1.0
            for day in own[loc[dates[pos-1]]+1:loc[dates[pos]]+1]:
                prev = own[loc[day]-1]
                split, dividend = 1.0, 0.0
                for kind, event in actions.get((code, day), []):
                    if kind == 'split':
                        split *= event['ratio']
                    else:
                        dividend += event['amount_per_share']
                factor *= (prices[code][day][1] * split + dividend) / prices[code][prev][1]
            indices[code].append(indices[code][-1] * factor)
    return prices, dates, actions, indices


def calculate_metrics(nav, days):
    total = nav[-1] / INITIAL
    years = (dt.date.fromisoformat(days[-1]) - dt.date.fromisoformat(days[0])).days / 365.2425
    peak, worst = INITIAL, 0.0
    for amount in nav:
        peak = max(peak, amount)
        worst = max(worst, 1-amount/peak)
    changes = [nav[i]/nav[i-1]-1 for i in range(1, len(nav))]
    mean = sum(changes)/len(changes)
    sigma = math.sqrt(sum((r-mean)**2 for r in changes)/len(changes))
    return {'return_pct': (total-1)*100, 'cagr_pct': (total**(1/years)-1)*100,
            'max_drawdown_pct': worst*100, 'sharpe_zero_rf': mean/sigma*math.sqrt(244) if sigma else None,
            'final_total': nav[-1]}


def simulate(prices, days, actions, indices, *, schedule='legacy', phase=0, fee=.0008, slip=0.0, buy_hold=None, us_cap=1.0, capital=INITIAL):
    cash, outstanding = capital, []
    shares = dict.fromkeys(CODES, 0)
    costs = dict.fromkeys(CODES, 0.0)
    nav, ledger, orders, signals = [], [], [], []
    pending = ([buy_hold], 1.0) if buy_hold else None
    for i, day in enumerate(days):
        # Pay dates can be non-common dates, so settle everything payable by today.
        for payment in list(outstanding):
            if payment['pay_date'] <= day:
                cash += payment['amount']
                outstanding.remove(payment)
        for code in CODES:
            for kind, event in actions.get((code, day), []):
                if kind == 'split':
                    shares[code] *= event['ratio']
                    costs[code] /= event['ratio']
                else:
                    assert event['record_date'] < day and event['pay_date'] >= day
                    outstanding.append({'pay_date': event['pay_date'], 'amount': shares[code]*event['amount_per_share']})
        receivables = sum(item['amount'] for item in outstanding)
        if pending is not None:
            selected, scale = pending
            equity = cash + receivables + sum(shares[c]*prices[c][day][0] for c in CODES)
            weight = equity*scale/len(selected) if selected else 0
            us_selected = sum(c in ('513100', '513500') for c in selected)
            us_weight = min(weight, equity*us_cap/us_selected) if us_selected else 0
            target = {c: math.floor((us_weight if c in ('513100', '513500') else weight)/prices[c][day][0]/100)*100 if c in selected else 0 for c in CODES}
            for code in CODES:
                amount = max(0, shares[code]-target[code])
                if amount:
                    execution = prices[code][day][0]*(1-slip)
                    net = amount*execution*(1-fee)
                    cash += net
                    shares[code] -= amount
                    if not shares[code]:
                        costs[code] = 0.0
                    orders.append({'date':day,'code':code,'side':'sell','shares':amount,'price':execution,'cash_change':net})
            for code in selected:
                execution = prices[code][day][0]*(1+slip)
                unit_cost = execution*(1+fee)
                amount = min(max(0, target[code]-shares[code]), math.floor((cash+1e-8)/unit_cost/100)*100)
                if amount:
                    total_cost = amount*unit_cost
                    costs[code] = (shares[code]*costs[code]+total_cost)/(shares[code]+amount)
                    shares[code] += amount
                    cash -= total_cost
                    orders.append({'date':day,'code':code,'side':'buy','shares':amount,'price':execution,'cash_change':-total_cost})
            pending = None
        market = sum(shares[c]*prices[c][day][1] for c in CODES)
        value = cash+receivables+market
        assert cash >= -1e-5 and all(value >= 0 for value in shares.values())
        nav.append(value)
        ledger.append({'date':day,'cash':cash,'receivable':receivables,'market':market,'total':value,
                       'holdings':{c:{'shares':shares[c], 'cost':costs[c]} for c in CODES if shares[c]}})
        if buy_hold or i < 20 or dt.date.fromisoformat(day).weekday() != 4:
            continue
        parity = (i//5)%2 if schedule == 'legacy' else (dt.date.fromisoformat(day).toordinal()//7)%2
        if parity != phase:
            continue
        scores = {}
        for code in CODES:
            seq = indices[code]
            daily = [seq[j]/seq[j-1]-1 for j in range(i-19, i+1)]
            avg = sum(daily)/20
            volatility = math.sqrt(sum((v-avg)**2 for v in daily)/20)
            scores[code] = (seq[i]/seq[i-20]-1, volatility)
        ranked = sorted(CODES, key=lambda c:scores[c][0], reverse=True)
        selected = [c for c in ranked[:2] if scores[c][0] > 0 and scores[c][1] <= .02]
        changes = [nav[j]/nav[j-1]-1 for j in range(i-19, i+1)]
        avg = sum(changes)/20
        volatility = math.sqrt(sum((v-avg)**2 for v in changes)/20)*math.sqrt(244)
        scale = min(1.0, .15/volatility) if volatility else 1.0
        pending = selected, scale
        signals.append({'date':day,'selection':selected,'scale':scale})
    normalized = [value*INITIAL/capital for value in nav]
    return {'metrics':calculate_metrics(normalized, days),'ledger':ledger,'orders':orders,'signals':signals}


def main():
    raw = INPUT.read_bytes()
    source = json.loads(raw)
    prices, days, actions, indices = prepare(source)
    for code, date, ratio in [('513100','2022-01-14',5),('513500','2022-03-30',2)]:
        i = days.index(date)
        actual = indices[code][i]/indices[code][i-1]
        expected = prices[code][date][1]*ratio/prices[code][days[i-1]][1]
        assert abs(actual-expected)<1e-12
    runs = {'original_calendar':simulate(prices,days,actions,indices),
            'higher_cost':simulate(prices,days,actions,indices,fee=.0016,slip=.001),
            'calendar_A':simulate(prices,days,actions,indices,schedule='calendar'),
            'calendar_B':simulate(prices,days,actions,indices,schedule='calendar',phase=1),
            'nasdaq_hold':simulate(prices,days,actions,indices,buy_hold='513100'),
            'hs300_hold':simulate(prices,days,actions,indices,buy_hold='510300')}
    for run in runs.values():
        assert all(abs(row['cash']+row['receivable']+row['market']-row['total'])<1e-6 for row in run['ledger'])
        assert all(order['shares']%100==0 for order in run['orders'] if order['side']=='buy')
    output = {'start':days[0], 'end':days[-1], 'data_sha256':hashlib.sha256(raw).hexdigest(),
              'method':'Sina daily unadjusted OHLC; Eastmoney corporate actions; cash dividends credited on pay date; original common-session index parity Friday, next common session open',
              'runs':runs}
    RESULT.write_text(json.dumps(output,ensure_ascii=False,separators=(',',':')))
    names={'original_calendar':'原调仓日历','higher_cost':'原日历 · 较高摩擦',
           'calendar_A':'固定双周 A','calendar_B':'固定双周 B','nasdaq_hold':'买入持有纳指ETF','hs300_hold':'买入持有沪深300ETF'}
    rows=[]
    for key,name in names.items():
        m=runs[key]['metrics']
        rows.append(f"<tr><td>{html.escape(name)}</td><td>{m['return_pct']:.2f}%</td><td>{m['cagr_pct']:.2f}%</td><td>-{m['max_drawdown_pct']:.2f}%</td><td>{m['final_total']:,.0f}</td></tr>")
        print(key, json.dumps(m,ensure_ascii=False), 'orders',len(runs[key]['orders']))
    page='''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>慢富十倍重新回测</title><style>body{background:#101722;color:#e6eefa;font:16px system-ui;margin:0}main{max-width:1050px;margin:auto;padding:32px}h1{color:#eac65f}p,li{line-height:1.8;color:#c4cede}table{border-collapse:collapse;width:100%}td,th{text-align:right;padding:12px;border-bottom:1px solid #354052}td:first-child,th:first-child{text-align:left}.note{padding:16px;border-left:4px solid #e9bb5d;background:#272722}.scroll{overflow:auto}</style></head><body><main><h1>慢富十倍 · 重新获取数据回测</h1><p>2014-01-15 至 2026-10-29 ｜本金 300 万 ｜研究模拟，不是实际收益</p><div class="note">以重新下载的新浪不复权日线、基金资料页分红及折算记录构建独立回测；数据仍需交易所/基金公告逐笔复核。高收益对调仓时点和成本敏感，不能保证未来表现。</div><h2>不同场景</h2><div class="scroll"><table><thead><tr><th>方案</th><th>累计收益</th><th>年化</th><th>最大回撤</th><th>期末总资产（元）</th></tr></thead><tbody>ROWS</tbody></table></div><h2>方法和局限</h2><ul><li>行情重新从新浪下载，不使用项目旧行情；分红、拆分及发放日重新从天天基金提取。原价与项目数据在11个开收盘记录上不一致，腾讯复核这些差异与项目记录相同，新浪值的准确性仍待交易所核实。</li><li>信号使用事件调整后的逐日收益序列；成交和估值始终用不复权价格。拆分后份额同步调整、成本按比例变化，现金分红在登记日确认权益、发放日到账，期间记为应收。</li><li>周五收盘信号，下一共同交易日开盘成交；费用每侧0.08%，买入按100份，不允许负现金。高摩擦情景每侧费用0.16%另加0.10%滑点。</li><li>五只 ETF 共同交易日历忽略少数个别停牌日；未模拟涨跌停、停牌成交失败、订单冲击、分红税、融资及 QDII 溢价突变；当日开盘全额成交属于理想化假设。</li><li>原日历为项目原有的交易日序号规则，不是严格每两周；固定双周 A/B 为敏感性对照。所有结果均是同一历史样本内回测，不是严格样本外结果，且不预测未来收益。</li><li>基金资料页中的分红发放日期与交易所 ETF 投资者的实际可用日期可能不同，应与基金公告、托管方及券商账单核对；企业事件及历史行情尚未完整独立复核。</li></ul><p>逐日持仓、现金、应收分红和交易明细见审计结果文件。</p></main></body></html>'''
    REPORT.write_text(page.replace('ROWS',''.join(rows)))
    print('saved',RESULT,REPORT)


if __name__ == '__main__':
    main()
