#!/usr/bin/env python3
"""生成 App 数据文件（慢富十倍·复利策略）
- 统一用 2016-01 起十年复利回放数据（无前视偏差）
- 计算"今日操作"信号（哪些标的满足三关买入/跌破MA20卖出）
"""
import json
from datetime import datetime

sim = json.load(open('backtest_data/sim_full_v3.json'))
S = sim['summary']
nav_series = sim['nav_series']
hold_series = sim['hold_series']
trades = sim['trades']

# 月度收益
by_month = {}
for x in nav_series:
    by_month.setdefault(x['date'][:7], []).append(x['nav'])
monthly = [{'month': m, 'ret': round((by_month[m][-1]/by_month[m][0]-1)*100, 2)} for m in sorted(by_month)]

# 最新状态
last = nav_series[-1]
latest_holds = hold_series[-1]['holds']

# ===== 计算今日操作信号 =====
# 新策略（无止损·双周·20日动量·TOP2·波动过滤）：20日动量>0 且 波动率<=2%，取前2名
prices = json.load(open('backtest_data/prices_full_open.json'))
NAMES = [('510300','沪深300'),('159915','创业板'),('513100','纳指'),('513500','标普500'),('518880','黄金')]
dates = sorted(set.intersection(*[set(d for d,_ in prices[n]) for n,_ in NAMES]))
latest = dates[-1]
i = len(dates)-1
close = {n:{d:v[1] for d,v in prices[n]} for n,_ in NAMES}
MD = VOL = 20

signals = []
for code, name in NAMES:
    mom = close[code][dates[i]]/close[code][dates[i-MD]] - 1
    rets = [close[code][dates[j]]/close[code][dates[j-1]]-1 for j in range(i-VOL+1, i+1)]
    m = sum(rets)/len(rets)
    vol = (sum((r-m)**2 for r in rets)/len(rets))**0.5
    pass_all = mom > 0 and vol <= 0.02
    signals.append({
        'name': name, 'mom': round(mom*100, 2), 'vol': round(vol*100, 2),
        'pass': pass_all, 'price': close[code][dates[i]]
    })

# 通过筛选的标的，按动量排序取前2
passed = sorted([s for s in signals if s['pass']], key=lambda s: -s['mom'])
buy_list = [s['name'] for s in passed[:2]]

# 今日操作结论
is_friday = datetime.strptime(latest, '%Y-%m-%d').weekday() == 4
if buy_list:
    action_type = 'buy'
    action_title = '买入信号'
else:
    action_type = 'hold'
    action_title = '空仓观望'

today_action = {
    'date': latest,
    'is_friday': is_friday,
    'type': action_type,
    'title': action_title,
    'buy': buy_list,
    'sell': [],
    'detail': '五标的均未通过筛选，空仓等待' if action_type == 'hold' else
              ('动量前2：' + '、'.join(buy_list) + '，按波动率目标仓位买入，下个调仓日开盘执行'),
}

# ===== 计算沪深300基准（买入持有）=====
hs300_close = close['510300']
# 取与 nav_series 相同的日期序列
nav_dates = [x['date'] for x in nav_series]
base0 = hs300_close[nav_dates[0]]
hs300_series = []
for d in nav_dates:
    hs300_series.append({'date': d, 'nav': round(hs300_close[d]/base0, 6)})

app_data = {
    'strategy_name': '慢富十倍·复利策略',
    'slogan': '慢慢变富，与时间为友',
    'capital': 3000000,
    'start_date': '2014-01-02',
    'latest_date': last['date'],
    'summary': {
        'total_ret': S['total_ret'],
        'ann': S['ann'],
        'mdd': S['mdd'],
        'sharpe': S['sharpe'],
        'days': S['days'],
        'trades': S['trades'],
        'final_total': S['final_total'],
        'final_nav': round(last['nav'], 4),
        'year_ret': S.get('year_ret', {}),
    },
    'latest_state': {
        'total': last['total'],
        'nav': last['nav'],
        'cash': last['cash'],
        'market': last['market'],
        'holds_label': latest_holds,
    },
    'nav_series': nav_series,
    'hold_series': hold_series,
    'monthly': monthly,
    'trades': trades,
    'signals': signals,
    'today_action': today_action,
    'hs300_series': hs300_series,
}

json.dump(app_data, open('app_1.0/src/data.json','w'), ensure_ascii=False)
print('✅ data.json 已生成')
print('   策略名:', app_data['strategy_name'])
print('   期末总资产:', round(app_data['latest_state']['total']))
print('   累计收益:', str(S['total_ret'])+'%')
print('   今日操作:', action_title, '| 买入', buy_list or '无')
