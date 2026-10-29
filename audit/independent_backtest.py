#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Independent no-leverage ETF momentum backtest; no project engine imports."""
import collections
import datetime as dt
import hashlib
import html
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRICES = ROOT / 'backtest_data/prices_true_nofq.json'
EVENTS = ROOT / 'backtest_data/events_table.json'
OUTPUT = ROOT / 'audit/independent_backtest_results.json'
REPORT = ROOT / 'audit/independent_backtest_report.html'
CODES = ['510300', '159915', '513100', '513500', '518880']
NAMES = dict(zip(CODES, ['沪深300ETF', '创业板ETF', '纳指ETF', '标普500ETF', '黄金ETF']))
CAPITAL = 3000000.0


def load():
    prices = {code: dict(rows) for code, rows in json.loads(PRICES.read_text()).items() if code in CODES}
    events = json.loads(EVENTS.read_text())
    dates = sorted(set.intersection(*(set(prices[code]) for code in CODES)))
    dates = [day for day in dates if day >= '2014-01-01']
    corp = collections.defaultdict(list)
    for code in CODES:
        for event in events[code]['events']:
            if event['date'] < dates[0]:
                continue
            if event['type'] == 'split':
                # Use each ETF's own first available session, not the common calendar.
                anchor = next((day for day in sorted(prices[code]) if day >= event['date']), None)
                if anchor:
                    corp[(code, anchor)].append(event)
            elif event['type'] == 'cash_dividend':
                corp[(code, event['date'])].append(event)
    return prices, dates, corp


def signal_series(prices, dates, corp):
    # Forward total-return index: only information available as of each session.
    result = {code: [1.0] for code in CODES}
    for code in CODES:
        own_dates = sorted(prices[code])
        index = {day: i for i, day in enumerate(own_dates)}
        for day in dates[1:]:
            previous_common = dates[len(result[code]) - 1]
            multiplier = 1.0
            for own_day in own_dates[index[previous_common] + 1:index[day] + 1]:
                previous = own_dates[index[own_day] - 1]
                ratio = 1.0
                dividend = 0.0
                for event in corp.get((code, own_day), []):
                    if event['type'] == 'split':
                        ratio *= event['split_ratio']
                    elif event['type'] == 'cash_dividend':
                        dividend += event['amount_per_share']
                multiplier *= (prices[code][own_day][1] * ratio + dividend) / prices[code][previous][1]
            result[code].append(result[code][-1] * multiplier)
    return result


def metrics(nav, dates):
    years = (dt.date.fromisoformat(dates[-1]) - dt.date.fromisoformat(dates[0])).days / 365.2425
    peak, drawdown = nav[0], 0.0
    for value in nav:
        peak = max(peak, value)
        drawdown = max(drawdown, 1 - value / peak)
    returns = [nav[i] / nav[i - 1] - 1 for i in range(1, len(nav))]
    mean = sum(returns) / len(returns)
    std = math.sqrt(sum((value - mean) ** 2 for value in returns) / len(returns))
    return {'total_pct': (nav[-1] / nav[0] - 1) * 100,
            'cagr_pct': ((nav[-1] / nav[0]) ** (1 / years) - 1) * 100,
            'max_drawdown_pct': drawdown * 100,
            'sharpe_zero_rf': mean / std * math.sqrt(244) if std else 0,
            'final_yuan': nav[-1] * CAPITAL}


def run(prices, dates, corp, signals, fee=0.0008, slip=0.0, window=20, target_vol=0.15, phase=0, schedule='calendar', fixed=None, dividend_delay=0):
    cash = CAPITAL
    shares = {code: 0 for code in CODES}
    costs = {code: 0.0 for code in CODES}
    receivable = 0.0
    payments = collections.defaultdict(float)
    ledger = []
    nav, trades, holding_counts, targets = [], [], collections.Counter(), []
    pending = None
    last_signal_week = None
    for index, day in enumerate(dates):
        cash += payments.pop(index, 0.0)
        for code in CODES:
            for event in corp.get((code, day), []):
                if event['type'] == 'split':
                    shares[code] *= event['split_ratio']
                    costs[code] /= event['split_ratio']
                elif event['type'] == 'cash_dividend':
                    entitlement = shares[code] * event['amount_per_share']
                    if dividend_delay:
                        payments[index + dividend_delay] += entitlement
                        receivable += entitlement
                    else:
                        cash += entitlement
        receivable = sum(payments.values())
        if fixed and index == 0:
            pending = ([fixed], 1.0)
        if pending:
            selected, scale = pending
            opening = {code: prices[code][day][0] for code in CODES}
            equity = cash + receivable + sum(shares[code] * opening[code] for code in CODES)
            each = equity * scale / len(selected) if selected else 0
            goals = {code: math.floor(each / opening[code] / 100) * 100 if code in selected else 0 for code in CODES}
            for code in CODES:
                quantity = max(0, shares[code] - goals[code])
                if quantity:
                    cash += quantity * opening[code] * (1 - slip) * (1 - fee)
                    shares[code] -= quantity
                    if not shares[code]:
                        costs[code] = 0.0
                    trades.append((day, code, 'sell', quantity))
            for code in selected:
                wanted = max(0, goals[code] - shares[code])
                unit_cost = opening[code] * (1 + slip) * (1 + fee)
                quantity = min(wanted, math.floor((cash + 1e-8) / unit_cost / 100) * 100)
                if quantity > 0:
                    cash -= quantity * unit_cost
                    costs[code] = (shares[code] * costs[code] + quantity * unit_cost) / (shares[code] + quantity)
                    shares[code] += quantity
                    trades.append((day, code, 'buy', quantity))
            pending = None
        value = cash + receivable + sum(shares[code] * prices[code][day][1] for code in CODES)
        assert cash >= -1e-6 and all(quantity >= 0 for quantity in shares.values())
        nav.append(value / CAPITAL)
        ledger.append({'date': day, 'cash': cash, 'dividends_receivable': receivable,
                       'market_value': value - cash - receivable, 'total': value,
                       'holdings': {code: {'shares': shares[code], 'cost': costs[code]}
                                    for code in CODES if shares[code]}})
        for code in CODES:
            if shares[code] > 0:
                holding_counts[code] += 1
        if fixed or index < max(window, 20):
            continue
        weekday = dt.date.fromisoformat(day).weekday()
        week = dt.date.fromisoformat(day).toordinal() // 7
        if schedule == 'legacy':
            trigger = weekday == 4 and (index // 5) % 2 == phase
        else:
            # Alternate calendar Fridays; a missing Friday has no fallback.
            trigger = weekday == 4 and (week % 2 == phase) and week != last_signal_week
            if trigger:
                last_signal_week = week
        if not trigger:
            continue
        scores = {}
        for code in CODES:
            series = signals[code]
            momentum = series[index] / series[index - window] - 1
            changes = [series[j] / series[j - 1] - 1 for j in range(index - 19, index + 1)]
            avg = sum(changes) / len(changes)
            vol = math.sqrt(sum((v - avg) ** 2 for v in changes) / len(changes))
            scores[code] = momentum, vol
        ranked = sorted(CODES, key=lambda code: scores[code][0], reverse=True)
        selected = [code for code in ranked[:2] if scores[code][0] > 0 and scores[code][1] <= .02]
        changes = [nav[j] / nav[j - 1] - 1 for j in range(index - 19, index + 1)]
        avg = sum(changes) / len(changes)
        vol = math.sqrt(sum((v - avg) ** 2 for v in changes) / len(changes)) * math.sqrt(244)
        scale = min(1.0, target_vol / vol) if vol else 1.0
        pending = selected, scale
        targets.append((day, selected, scale))
    assert min(nav) > 0 and cash >= -1e-6 and all(q >= 0 for q in shares.values())
    return {'metrics': metrics(nav, dates), 'nav': nav, 'trades': trades,
            'trade_count': len(trades), 'cash': cash, 'shares': shares,
            'holdings': ledger[-1]['holdings'], 'ledger': ledger,
            'holding_days': dict(holding_counts), 'signals': targets}


def verify(prices, dates, corp, signals):
    # Golden tests for split accounting and no spurious split-day price crash.
    for code, day, ratio in [('513100', '2022-01-14', 5), ('513500', '2022-03-30', 2)]:
        assert any(e['type'] == 'split' and e['split_ratio'] == ratio for e in corp[(code, day)])
        idx = dates.index(day)
        actual = signals[code][idx] / signals[code][idx - 1]
        expected = prices[code][day][1] * ratio / prices[code][dates[idx - 1]][1]
        assert abs(actual - expected) < 1e-10 and 0.9 < actual < 1.1
    # A later corporate action cannot alter signals at an earlier date.
    cutoff = dates.index('2021-12-31') + 1
    truncated = signal_series(prices, dates[:cutoff], corp)
    assert all(abs(truncated[code][-1] - signals[code][cutoff - 1]) < 1e-12 for code in CODES)
    # An ex-date buyer is not entitled; a prior-close holder receives the cash.
    test_dates = ['2022-01-03', '2022-01-04', '2022-01-05']
    test_prices = {code: {day: [1.0, 1.0] for day in test_dates} for code in CODES}
    test_prices['510300']['2022-01-05'] = [.9, .9]
    test_events = {('510300', '2022-01-05'): [{'type': 'cash_dividend', 'amount_per_share': .1}]}
    test_signals = signal_series(test_prices, test_dates, test_events)
    test = run(test_prices, test_dates, test_events, test_signals, fee=0, fixed='510300')
    assert abs(test['nav'][-1] - 1.0) < 1e-10
    delayed = run(test_prices, test_dates, test_events, test_signals, fee=0, fixed='510300', dividend_delay=2)
    assert abs(delayed['nav'][-1] - 1.0) < 1e-10
    assert delayed['ledger'][-1]['dividends_receivable'] > 0


def period_metrics(result, dates, start, end):
    indices = [i for i, day in enumerate(dates) if start <= day <= end]
    return metrics([result['nav'][i] for i in indices], [dates[i] for i in indices])


def write_report(output, dates):
    rows = []
    names = {'legacy_schedule': '原调仓日历 · 研究主方案', 'legacy_delay': '原日历 · 分红延迟2交易日',
             'legacy_higher_cost': '原日历 · 高摩擦', 'baseline': '固定双周 A', 'opposite_phase': '固定双周 B',
             'higher_cost': '固定双周 A · 高摩擦', 'momentum_40d': '固定双周 A · 40日动量'}
    for key, name in names.items():
        item = output['variants'][key]
        m = item['metrics']
        rows.append(f"<tr><td>{html.escape(name)}</td><td>{m['total_pct']:.2f}%</td><td>{m['cagr_pct']:.2f}%</td><td>-{m['max_drawdown_pct']:.2f}%</td><td>{m['final_yuan']:,.0f}</td><td>{item['trade_count']}</td></tr>")
    for code, item in output['benchmarks_cash_dividends'].items():
        m = item['metrics']
        rows.append(f"<tr><td>持有 {NAMES[code]}</td><td>{m['total_pct']:.2f}%</td><td>{m['cagr_pct']:.2f}%</td><td>-{m['max_drawdown_pct']:.2f}%</td><td>{m['final_yuan']:,.0f}</td><td>{item['trade_count']}</td></tr>")
    period_rows = []
    for start, end in [('2014-01-15','2018-12-31'), ('2019-01-01','2022-12-31'), ('2023-01-01',dates[-1])]:
        m = period_metrics(output['variants']['baseline'], dates, start, end)
        period_rows.append(f"<tr><td>{start} 至 {end}</td><td>{m['total_pct']:.2f}%</td><td>{m['cagr_pct']:.2f}%</td><td>-{m['max_drawdown_pct']:.2f}%</td></tr>")
    page = '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>慢富十倍 · 独立回测</title><style>body{background:#10141c;color:#e8edf5;font:16px system-ui;margin:0}main{max-width:1100px;margin:auto;padding:28px}h1{color:#f1c85b}h2{margin-top:38px}p,li{line-height:1.7;color:#c5cedb}.notice{background:#392723;border-left:4px solid #f48569;padding:16px}table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:right;padding:11px;border-bottom:1px solid #303b4d}th:first-child,td:first-child{text-align:left}th{color:#9faec3}.up{color:#ff6262}.down{color:#43c99e}.scroll{overflow:auto}.small{font-size:14px}code{color:#f1c85b}</style></head><body><main><h1>慢富十倍 · 独立回测审计</h1><p>区间：START 至 END ｜ 初始资金 300 万元 ｜ 历史模拟，不代表未来收益</p><div class="notice"><strong>结论：策略收益对调仓周和交易摩擦非常敏感；结果尚不足以证明实盘可靠。</strong><br>独立账本未调用原回测引擎，但原始价格和企业事件仍来自项目文件，尚未完整独立交叉验证。</div><h2>同一数据上的策略与单资产对照</h2><div class="scroll"><table><thead><tr><th>场景</th><th>累计收益</th><th>年化收益</th><th>最大回撤</th><th>期末资产（元）</th><th>交易笔数</th></tr></thead><tbody>ROWS</tbody></table></div><h2>固定双周 A：分时段表现</h2><p>以下仅对同一历史路径分段描述，不是样本外验证；各段均使用该段首日收盘净值作为起点。</p><div class="scroll"><table><thead><tr><th>时段</th><th>累计收益</th><th>年化收益</th><th>最大回撤</th></tr></thead><tbody>PERIODS</tbody></table></div><h2>模型与边界</h2><ul><li>使用 <code>prices_true_nofq.json</code> 的不复权开盘、收盘价；拆分和现金分红按 <code>events_table.json</code> 处理。动量使用按事件逐日向前计算的可比收益序列。</li><li>20 日动量先排序取前 2，再过滤正动量和 20 日波动率不超过 2%；20 日组合年化波动目标 15%，仓位不超过 100%。</li><li>信号日收盘生成、下一共同交易日开盘执行；买入按 100 份整数倍、现金不足不透支，卖出先执行。基准成本每侧 0.08%，未计滑点；高摩擦为每侧费用 0.16% 加滑点 0.10%。</li><li>两种固定双周只相差一个周五；节假日无补调。原调仓日历按公共交易日序号计算，假期可能跳过。五只 ETF 的共同交易日共漏 3 天；不模拟停牌无法成交、涨跌停、深度冲击或 QDII 溢价实时变化。</li><li>股息按除息日入账、以前一交易日持有份额计算；事件表存在未核实项目。真实发放日、税费、整数/零股处理和实际执行可能不同。</li><li>分时段结果不是独立样本外实验。当前参数和标的可能经过历史挑选，未证明抗过拟合；Sharpe 假定零无风险利率。</li></ul><p class="small">独立实现：<code>audit/independent_backtest.py</code>；完整结果：<code>audit/independent_backtest_results.json</code>。报告中的收益为模拟，不是实盘收益或承诺。</p></main></body></html>'''
    page = page.replace('股息按除息日入账、以前一交易日持有份额计算；事件表存在未核实项目。真实发放日、税费、整数/零股处理和实际执行可能不同。', '主方案股息按除息日入账、以前一交易日持有份额计算；另测延迟两个共同交易日到账，仅为压力假设，不代表实际发放日。事件表及税费仍需逐笔核实。')
    page = page.replace('区间：START 至 END ｜ 初始资金 300 万元 ｜ 历史模拟，不代表未来收益', '区间：START 至 END ｜ 初始资金 300 万元 ｜ 历史模拟，不代表未来收益')
    REPORT.write_text(page.replace('START', dates[0]).replace('END', dates[-1]).replace('ROWS', ''.join(rows)).replace('PERIODS', ''.join(period_rows)))


def main():
    prices, dates, corp = load()
    signals = signal_series(prices, dates, corp)
    verify(prices, dates, corp, signals)
    variants = {
        'baseline': run(prices, dates, corp, signals),
        'opposite_phase': run(prices, dates, corp, signals, phase=1),
        'legacy_schedule': run(prices, dates, corp, signals, schedule='legacy'),
        'legacy_delay': run(prices, dates, corp, signals, schedule='legacy', dividend_delay=2),
        'legacy_higher_cost': run(prices, dates, corp, signals, schedule='legacy', fee=.0016, slip=.001),
        'higher_cost': run(prices, dates, corp, signals, fee=.0016, slip=.001),
        'momentum_40d': run(prices, dates, corp, signals, window=40),
    }
    benchmarks = {code: run(prices, dates, corp, signals, fixed=code) for code in CODES}
    output = {'start': dates[0], 'end': dates[-1], 'trading_days': len(dates),
              'input_sha256': {'prices_true_nofq.json': hashlib.sha256(PRICES.read_bytes()).hexdigest(),
                               'events_table.json': hashlib.sha256(EVENTS.read_bytes()).hexdigest()},
              'assumptions': {'capital': CAPITAL, 'fee_each_side': .0008, 'slippage': 0,
                              'lot': 100, 'signal': '20-day total-return momentum, top 2 then positive and 20-day daily vol <= 2%',
                              'rebalance': 'legacy variant uses original index-based Friday calendar; other variants use alternating calendar Fridays; holidays skipped',
                              'portfolio_vol_target': .15, 'dividends': 'cash on ex-date, previous-close entitlement',
                              'calendar': 'intersection of all five ETFs; no missing-price execution model'},
              'variants': variants, 'benchmarks_cash_dividends': benchmarks}
    OUTPUT.write_text(json.dumps(output, ensure_ascii=False, separators=(',', ':')))
    write_report(output, dates)
    print('期间', dates[0], dates[-1], '交易日',len(dates))
    for name, result in variants.items():
        print(name, json.dumps(result['metrics'], ensure_ascii=False), 'trades',result['trade_count'])
    for code,result in benchmarks.items():
        print('benchmark',code,json.dumps(result['metrics'],ensure_ascii=False))
    print('saved', OUTPUT)
    print('saved', REPORT)


if __name__ == '__main__':
    main()
