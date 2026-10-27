#!/usr/bin/env python3
"""修正 2014-2015 QDII 价格僵住问题（v2，锚点插值法）。

方法：对每个僵住日，找到最近的前一个"正常成交日"作为锚点，
用美股指数从锚点日到当前日的累计涨幅，反推 ETF 应有的价格。
不依赖全局跟踪倍率，避免 513500 溢价折价噪音把倍率算成负数。

- 513100 纳指 -> us.NDX
- 513500 标普 -> us.INX
"""
import urllib.request, json, time

ETF_INDEX = {'513100': 'us.NDX', '513500': 'us.INX'}

def fetch_index(sym):
    url = f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sym},day,2014-01-01,2015-12-31,500,'
    req = urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
    r = urllib.request.urlopen(req, timeout=20)
    d = json.loads(r.read().decode('utf-8'))
    k = d['data'][sym]
    kl = k.get('day') or k.get('qfqday') or []
    return {x[0]: float(x[2]) for x in kl}

def fix(etf_code, index_code):
    etf = json.load(open('backtest_data/prices_2014_2015.json'))[etf_code]
    idx_close = fetch_index(index_code)
    dates = [r[0] for r in etf]
    etf_map = {r[0]: r[1] for r in etf}

    fixed = []
    fixed_count = 0
    last_good_date = None  # 最近一个"价格有变化"的日期（锚点）

    for i, d in enumerate(dates):
        op_, cl_ = etf_map[d]
        if i == 0:
            fixed.append([d, [op_, cl_]])
            last_good_date = d
            continue

        prev_cl = fixed[-1][1][1]
        is_stuck = (cl_ == etf_map[dates[i-1]][1])  # 用原始判断是否僵住

        if is_stuck and d in idx_close and last_good_date in idx_close:
            # 僵住且美股开市：用指数从锚点到现在的涨幅反推
            anchor_cl = etf_map[last_good_date][1]
            idx_ret = idx_close[d] / idx_close[last_good_date] - 1
            new_cl = anchor_cl * (1 + idx_ret)
            # 开盘价也按比例近似
            new_op = op_ * (new_cl / anchor_cl) if anchor_cl > 0 else op_
            fixed.append([d, [round(new_op,3), round(new_cl,3)]])
            fixed_count += 1
        else:
            fixed.append([d, [op_, cl_]])
            if not is_stuck:
                last_good_date = d  # 更新锚点

    print(f'{etf_code}: 修正 {fixed_count} 个僵住日')
    return fixed

result = {}
for etf, idx in ETF_INDEX.items():
    result[etf] = fix(etf, idx)
    time.sleep(0.5)

data = json.load(open('backtest_data/prices_2014_2015.json'))
for etf in ETF_INDEX:
    data[etf] = result[etf]
json.dump(data, open('backtest_data/prices_2014_2015_fixed.json','w'), ensure_ascii=False)

# 验证
print('\n=== 修正后质量验证 ===')
for n in ['513100','513500']:
    f = data[n]
    fc = [r[1][1] for r in f]
    same = sum(1 for i in range(1,len(fc)) if fc[i]==fc[i-1])
    print(f'{n}: 剩余连续同价 {same}天, 价格区间 {min(fc):.3f}~{max(fc):.3f}')
