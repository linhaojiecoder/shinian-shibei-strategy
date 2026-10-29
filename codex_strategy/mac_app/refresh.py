#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a read-only V1 research snapshot in the app's private directory."""
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import math
from pathlib import Path
import engine

root = Path(__file__).resolve().parent
data_dir = Path(sys.argv[1])
mode = sys.argv[2]
data_dir.mkdir(parents=True, exist_ok=True)
destination = data_dir / 'snapshot.json'
pending_market = None
if mode == 'refresh':
    china = dt.timezone(dt.timedelta(hours=8))
    now = dt.datetime.now(china)
    # Do not treat an unfinished session as a daily close.
    end = now.date() if now.hour >= 16 else now.date() - dt.timedelta(days=1)
    with tempfile.TemporaryDirectory(prefix='codex-v1-') as temp:
        path = Path(temp) / 'download.json'
        subprocess.run([sys.executable, str(root / 'fresh_data.py'), end.isoformat(), str(path)],
                       check=True, stdout=sys.stderr, timeout=150)
        data = json.loads(path.read_text())
        if any(len(data['prices'].get(code, [])) < 1000 for code in engine.CODES):
            raise ValueError('历史行情不完整，已保留原有数据')
        if any(data['prices'][code][-1][0] > end.isoformat() for code in engine.CODES):
            raise ValueError('行情包含尚未收盘的数据')
        previous_path = data_dir / 'market.json'
        previous = json.loads((previous_path if previous_path.exists() else root / 'baseline.json').read_text())
        previous_asof = max(set.intersection(*(set(dict(previous['prices'][code])) for code in engine.CODES)))
        for code in engine.CODES:
            old_prices = dict(previous['prices'][code])
            new_prices = dict(data['prices'][code])
            for day, values in old_prices.items():
                if day not in new_prices or new_prices[day][:2] != values[:2]:
                    raise ValueError(f'{code} 历史价格 {day} 有变化或缺失，需先核查；未替换原数据')
            for kind in ('dividends', 'splits'):
                old_events = previous['actions'][code][kind]
                new_events = data['actions'][code][kind]
                if any(event not in new_events for event in old_events):
                    raise ValueError(f'{code} 历史分红/拆分数据变化，需先核查；未替换原数据')
                date_key = 'ex_date' if kind == 'dividends' else 'date'
                if any(event not in old_events and event[date_key] <= previous_asof for event in new_events):
                    raise ValueError(f'{code} 出现新增历史分红/拆分，需先核查；未替换原数据')
        prices, days, actions, indices = engine.prepare(data)
        if len(days) < 1000 or days[-1] < previous_asof:
            raise ValueError('共同交易日不足或行情倒退，已保留原有数据')
        pending_market = data
else:
    snapshot = data_dir / 'market.json'
    data = json.loads((snapshot if snapshot.exists() else root / 'baseline.json').read_text())

prices, days, actions, indices = engine.prepare(data)
result = engine.simulate(prices, days, actions, indices)
last = result['ledger'][-1]
latest_signal = result['signals'][-1] if result['signals'] else None
latest_orders = [order for order in result['orders'] if order['date'] == days[-1]]
previous = result['ledger'][-2]
details = {}
for code, holding in last['holdings'].items():
    share = holding['shares']
    close = prices[code][days[-1]][1]
    prior_holding = previous['holdings'].get(code)
    has_event = bool(actions.get((code, days[-1]))) or any(order['code'] == code for order in latest_orders)
    # Per-position daily P&L is not reliably comparable on trade/event days.
    daily = (share * (close - prices[code][days[-2]][1])
             if prior_holding and prior_holding['shares'] == share and not has_event else None)
    first = len(days) - 1
    while first > 0 and code in result['ledger'][first - 1]['holdings']:
        first -= 1
    details[code] = {'market': share * close, 'profit': share * (close - holding['cost']),
                     'daily_profit': daily, 'weight': share * close / last['total'],
                     'holding_days': (dt.date.fromisoformat(days[-1]) - dt.date.fromisoformat(days[first])).days + 1}
scores = {}
i = len(days) - 1
for code in engine.CODES:
    seq = indices[code]
    daily_returns = [seq[j] / seq[j - 1] - 1 for j in range(i - 19, i + 1)]
    mean = sum(daily_returns) / 20
    scores[code] = {'momentum': seq[i] / seq[i - 20] - 1,
                    'volatility': math.sqrt(sum((x - mean) ** 2 for x in daily_returns) / 20),
                    'price': prices[code][days[-1]][1]}
output = {'asof':days[-1], 'metrics':result['metrics'], 'state':last,
          'latest_signal':latest_signal, 'latest_orders':latest_orders,
          'position_details': details, 'scores': scores,
          'daily_change': last['total'] - previous['total'],
          'daily_change_pct': (last['total'] / previous['total'] - 1) * 100,
          'latest_prices':{code:prices[code][days[-1]][1] for code in engine.CODES},
          'nav': [{'date':row['date'], 'total':row['total']} for row in result['ledger']],
          'source':'新浪不复权行情 / 天天基金分红与拆分', 'generated_at':dt.datetime.now().astimezone().isoformat(),
          'simulated':True}
temp_output = data_dir / 'snapshot.json.tmp'
temp_output.write_text(json.dumps(output, ensure_ascii=False))
if pending_market is not None:
    temp_snapshot = data_dir / 'market.json.tmp'
    temp_snapshot.write_text(json.dumps(pending_market, ensure_ascii=False))
    os.replace(temp_snapshot, data_dir / 'market.json')
os.replace(temp_output, destination)
print(json.dumps({'path':str(destination), 'asof':days[-1]},ensure_ascii=False))
