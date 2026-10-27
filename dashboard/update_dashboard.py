#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多资产动量轮动策略 · 每日仪表盘生成器
- 拉取 5 只 ETF 最新行情
- 计算 20日动量 / MA20 / 20日波动率 三关信号
- 更新 300 万模拟持仓（状态持久化在 state.json）
- 生成自包含 HTML 仪表盘
"""
import json, math, subprocess, time, os
from datetime import datetime, date

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "..", "backtest_data")
PRICES_JSON = os.path.join(DATA_DIR, "prices.json")
STATE_JSON = os.path.join(BASE, "state.json")
OUT_HTML = os.path.join(BASE, "index.html")

ETFS = [
    ("510300", "sh510300", "沪深300"),
    ("159915", "sz159915", "创业板"),
    ("513100", "sh513100", "纳指"),
    ("513500", "sh513500", "标普500"),
    ("518880", "sh518880", "黄金"),
]
NAMES = [c for c, _, _ in ETFS]
LABEL = {c: n for c, _, n in ETFS}

CAPITAL = 3_000_000  # 300 万
MD = 20   # 动量窗口
MA_N = 20  # 均线窗口
VOL_N = 20  # 波动率窗口
VOL_LIMIT = 0.02  # 波动率>2%剔除
TOP_K = 3
COST = 0.0008  # 单边成本


def fetch(code, start, end):
    r = subprocess.run(
        ["westock", "kline", code, "--period", "day", "--start", start, "--end", end],
        capture_output=True, text=True, timeout=60,
    )
    return r.stdout


def parse(lines):
    rows = []
    for ln in lines.splitlines():
        ln = ln.strip()
        if not ln.startswith("|"):
            continue
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if len(cells) < 3 or cells[0] == "date" or "---" in cells[0]:
            continue
        try:
            rows.append((cells[0], float(cells[2])))
        except (ValueError, IndexError):
            continue
    return rows


def load_prices():
    """加载历史价格；若不存在则拉取，并增量更新到最新交易日"""
    data = {}
    if os.path.exists(PRICES_JSON):
        with open(PRICES_JSON) as f:
            data = json.load(f)

    # 拉取最近 60 天，确保覆盖今日
    today = date.today().isoformat()
    # 往前推 90 自然日
    from datetime import timedelta
    start = (date.today() - timedelta(days=120)).isoformat()
    for code, wcode, _ in ETFS:
        out = fetch(wcode, start, today)
        rows = parse(out)
        if code not in data:
            data[code] = rows
        else:
            # 合并：按日期去重更新
            merged = {d: v for d, v in data[code]}
            for d, v in rows:
                merged[d] = v
            data[code] = sorted(merged.items())
    return data


def stats_on(dates, px, i):
    """在索引 i 处计算各标的三关指标"""
    out = {}
    for n in NAMES:
        if i < MD:
            out[n] = None
            continue
        mom = px[n][dates[i]] / px[n][dates[i - MD]] - 1
        ma20 = sum(px[n][dates[j]] for j in range(i - MA_N + 1, i + 1)) / MA_N
        # 波动率
        rets = [px[n][dates[j]] / px[n][dates[j - 1]] - 1 for j in range(i - VOL_N + 1, i + 1)]
        m = sum(rets) / len(rets)
        vol = (sum((r - m) ** 2 for r in rets) / len(rets)) ** 0.5
        above_ma = px[n][dates[i]] > ma20
        out[n] = {
            "price": px[n][dates[i]],
            "mom": mom,
            "ma20": ma20,
            "vol": vol,
            "above_ma": above_ma,
        }
    return out


def compute_signal(dates, px):
    i = len(dates) - 1
    metrics = stats_on(dates, px, i)
    moms = {n: metrics[n]["mom"] for n in NAMES}
    ranked = sorted(NAMES, key=lambda n: moms[n], reverse=True)
    holds = []
    for n in ranked[:TOP_K]:
        m = metrics[n]
        if m["mom"] > 0 and m["above_ma"] and m["vol"] <= VOL_LIMIT:
            holds.append(n)
    return metrics, ranked, holds, dates[i]


def load_state():
    if os.path.exists(STATE_JSON):
        with open(STATE_JSON) as f:
            state = json.load(f)
        # 兼容旧格式：holdings 是 {code: shares} 的，迁移为 {code: {shares, cost}}
        if state.get("holdings"):
            first = next(iter(state["holdings"].values()))
            if isinstance(first, (int, float)):
                new_hold = {}
                for c, s in state["holdings"].items():
                    # 旧数据没有成本价，用最近一笔买入价近似（缺省0，后续补）
                    cost = 0.0
                    for t in reversed(state.get("trades", [])):
                        if t.get("code") == c and t.get("action") == "买入":
                            cost = t.get("price", 0.0)
                            break
                    new_hold[c] = {"shares": s, "cost": cost}
                state["holdings"] = new_hold
        return state
    return {
        "started": None,
        "capital": CAPITAL,
        "cash": CAPITAL,
        "holdings": {},   # {code: {shares, cost}}
        "nav_history": [],  # [{date, nav, cash, market_value, holds}]
        "trades": [],     # [{date, action, code, label, shares, price, amount}]
    }


def save_state(state):
    with open(STATE_JSON, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def main():
    print("拉取行情...")
    data = load_prices()
    # 对齐日期
    date_sets = [set(d for d, _ in data[n]) for n in NAMES]
    dates = sorted(set.intersection(*date_sets))
    px = {n: {d: v for d, v in data[n]} for n in NAMES}
    latest = dates[-1]

    metrics, ranked, target_holds, sig_date = compute_signal(dates, px)

    state = load_state()
    if state["started"] is None:
        state["started"] = latest
        state["cash"] = CAPITAL
        state["holdings"] = {}
        state["nav_history"] = []
        state["trades"] = []

    # 执行调仓：把持仓对齐到 target_holds
    # 1. 卖出不再持有的
    for code in list(state["holdings"].keys()):
        if code not in target_holds:
            h = state["holdings"].pop(code)
            shares = h["shares"]
            price = px[code][latest]
            amount = shares * price * (1 - COST)
            state["cash"] += amount
            state["trades"].append({
                "date": latest, "action": "卖出", "code": code,
                "label": LABEL[code], "shares": shares, "price": round(price, 3),
                "amount": round(amount, 2),
            })
    # 2. 等权买入目标标的
    if target_holds:
        n_holds = len(target_holds)
        # 计算当前总市值
        market = sum(state["holdings"][c]["shares"] * px[c][latest] for c in state["holdings"])
        total = state["cash"] + market
        target_each = total / n_holds
        for code in target_holds:
            price = px[code][latest]
            cur = state["holdings"].get(code, {"shares": 0, "cost": 0.0})
            cur_shares = cur["shares"]
            cur_value = cur_shares * price
            # 需要调整到的份额
            target_value = target_each
            diff_value = target_value - cur_value
            if diff_value > price:  # 买入
                shares = int(diff_value / (price * (1 + COST)))
                if shares >= 100:
                    shares = shares // 100 * 100
                    cost = shares * price * (1 + COST)
                    if cost <= state["cash"]:
                        state["cash"] -= cost
                        # 加权平均成本
                        old_shares = cur["shares"]
                        old_cost = cur["cost"]
                        total_shares = old_shares + shares
                        if total_shares > 0:
                            new_cost = (old_shares * old_cost + shares * price) / total_shares
                        else:
                            new_cost = price
                        state["holdings"][code] = {"shares": total_shares, "cost": new_cost}
                        state["trades"].append({
                            "date": latest, "action": "买入", "code": code,
                            "label": LABEL[code], "shares": shares,
                            "price": round(price, 3), "amount": round(cost, 2),
                        })
            elif state["holdings"].get(code) is None:
                # 无持仓但需建立（金额不足一手时也记录成本为0占位）
                pass

    # 计算净值
    market = sum(state["holdings"][c]["shares"] * px[c][latest] for c in state["holdings"])
    total = state["cash"] + market
    nav = total / CAPITAL

    # 更新净值历史（去重同一天）
    hist = state["nav_history"]
    if hist and hist[-1]["date"] == latest:
        hist[-1] = {
            "date": latest, "nav": round(nav, 4), "cash": round(state["cash"], 2),
            "market": round(market, 2), "total": round(total, 2),
            "holds": {LABEL[c]: round(state["holdings"][c]["shares"] * px[c][latest], 2) for c in state["holdings"]},
        }
    else:
        hist.append({
            "date": latest, "nav": round(nav, 4), "cash": round(state["cash"], 2),
            "market": round(market, 2), "total": round(total, 2),
            "holds": {LABEL[c]: round(state["holdings"][c]["shares"] * px[c][latest], 2) for c in state["holdings"]},
        })
    state["nav_history"] = hist[-200:]  # 保留最近200条

    save_state(state)

    # 生成 HTML
    gen_html(state, metrics, ranked, target_holds, sig_date, px, latest, nav, market, total)

    print(f"完成。信号日 {sig_date}，持仓 {[LABEL[c] for c in target_holds] or '空仓'}，总资产 ¥{total:,.0f}，净值 {nav:.4f}")

    # 打印今日明确买卖指令（供人工照单操作）
    print("\n===== 今日操作指令 =====")
    today_actions = [t for t in state["trades"] if t["date"] == latest]
    if today_actions:
        for t in today_actions:
            if t["action"] == "卖出":
                print(f"🔴 卖出 {t['label']}：{t['shares']:,} 份 × {t['price']} ≈ ¥{t['amount']:,.0f}")
            else:
                print(f"🟢 买入 {t['label']}：{t['shares']:,} 份 × {t['price']} ≈ ¥{t['amount']:,.0f}")
    else:
        print("维持现状，今日无买卖操作。")
    print(f"当前持仓：{[LABEL[c] for c in state['holdings']] or '空仓（货基）'}")
    print("=========================\n")
    return state


def gen_html(state, metrics, ranked, target_holds, sig_date, px, latest, nav, market, total):
    hist = state["nav_history"]
    nav_dates = [h["date"] for h in hist]
    nav_vals = [h["nav"] for h in hist]
    total_vals = [h["total"] for h in hist]

    # 信号表
    rows_html = ""
    for n in ranked:
        m = metrics[n]
        pass3 = n in target_holds
        rows_html += f"""
        <tr>
          <td><b>{LABEL[n]}</b><br><span class="code">{n}</span></td>
          <td>{m['price']:.3f}</td>
          <td class="{'up' if m['mom']>0 else 'down'}">{m['mom']*100:+.2f}%</td>
          <td>{m['vol']*100:.2f}%</td>
          <td>{'✓站上' if m['above_ma'] else '✗跌破'}</td>
          <td class="{'hold' if pass3 else 'drop'}">{'持有' if pass3 else '剔除'}</td>
        </tr>"""

    # 持仓明细
    hold_rows = ""
    if state["holdings"]:
        for c, h in state["holdings"].items():
            s = h["shares"]
            cost_px = h["cost"]
            cur_px = px[c][latest]
            val = s * cur_px
            cost_val = s * cost_px
            pct = val / total * 100 if total > 0 else 0
            # 持有收益率 = (现价 - 成本价)/成本价
            if cost_px > 0:
                hold_ret = (cur_px / cost_px - 1) * 100
                hold_profit = val - cost_val
            else:
                hold_ret = 0.0
                hold_profit = 0.0
            ret_cls = "up" if hold_ret >= 0 else "down"
            ret_sign = "+" if hold_ret >= 0 else ""
            hold_rows += f"""
            <tr><td><b>{LABEL[c]}</b></td><td>{s:,} 份</td><td>{cost_px:.3f}</td><td>{cur_px:.3f}</td><td class="up">¥{val:,.0f}</td><td>{pct:.1f}%</td><td class="{ret_cls}">{ret_sign}{hold_ret:.2f}%</td></tr>"""
    else:
        hold_rows = '<tr><td colspan="7" style="color:#999;">当前空仓，资金在货基</td></tr>'

    # 交易记录（最近15条）
    trade_rows = ""
    for t in reversed(state["trades"][-15:]):
        cls = "buy" if t["action"] == "买入" else "sell"
        trade_rows += f"""
        <tr><td>{t['date']}</td><td class="{cls}">{t['action']}</td><td>{t['label']}</td><td>{t['shares']:,}</td><td>¥{t['amount']:,.0f}</td></tr>"""

    hold_labels = [LABEL[c] for c in target_holds] if target_holds else ["空仓（货基）"]
    hold_big = " + ".join(hold_labels)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>300万动量轮动 · 实时仪表盘</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
<style>
  *{{margin:0;padding:0;box-sizing:border-box;}}
  body{{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;background:#0e1117;color:#e6e8eb;padding:20px;}}
  .wrap{{max-width:1000px;margin:0 auto;}}
  .top{{display:flex;justify-content:space-between;align-items:flex-end;margin-bottom:16px;flex-wrap:wrap;gap:10px;}}
  .top h1{{font-size:20px;}}
  .top .time{{font-size:12px;color:#8b949e;}}
  .cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:16px;}}
  .card{{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:16px;}}
  .card .label{{font-size:12px;color:#8b949e;}}
  .card .val{{font-size:24px;font-weight:700;margin-top:6px;}}
  .up{{color:#f0b90b;}} .down{{color:#0ecb81;}} .hold{{color:#f0b90b;font-weight:700;}} .drop{{color:#8b949e;}}
  .buy{{color:#f0b90b;font-weight:700;}} .sell{{color:#0ecb81;font-weight:700;}}
  .panel{{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:18px;margin-bottom:16px;}}
  .panel h2{{font-size:15px;margin-bottom:14px;padding-left:10px;border-left:3px solid #f0b90b;}}
  table{{width:100%;border-collapse:collapse;font-size:13px;}}
  th,td{{padding:9px 8px;text-align:center;border-bottom:1px solid #21262d;}}
  th{{color:#8b949e;font-weight:500;font-size:12px;}}
  .code{{font-size:11px;color:#8b949e;}}
  .chart{{height:300px;}}
  .signal-big{{font-size:26px;font-weight:700;color:#f0b90b;text-align:center;padding:14px;}}
  .note{{font-size:11px;color:#8b949e;line-height:1.6;margin-top:8px;}}
</style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <h1>📊 300万 · 多资产动量轮动仪表盘</h1>
    <div class="time">信号日期 {sig_date} ｜ 生成于 {now_str}</div>
  </div>

  <div class="cards">
    <div class="card"><div class="label">总资产</div><div class="val up">¥{total:,.0f}</div></div>
    <div class="card"><div class="label">持仓市值</div><div class="val">¥{market:,.0f}</div></div>
    <div class="card"><div class="label">现金（货基）</div><div class="val">¥{state['cash']:,.0f}</div></div>
    <div class="card"><div class="label">累计净值 / 收益</div><div class="val {'up' if nav>=1 else 'down'}">{nav:.4f}<span style="font-size:14px;">({(nav-1)*100:+.2f}%)</span></div></div>
  </div>

  <div class="panel">
    <h2>当前信号：{hold_big}</h2>
    <div class="signal-big">{hold_big}</div>
    <div class="note">规则：20日涨幅前3名，过三关（涨幅&gt;0 + 站上MA20 + 波动率≤2%）等权持有，跌破MA20当天清仓。</div>
  </div>

    <div class="panel">
    <h2>持仓明细</h2>
    <table>
      <tr><th>标的</th><th>份额</th><th>成本价</th><th>现价</th><th>市值</th><th>占比</th><th>持有收益</th></tr>
      {hold_rows}
    </table>
  </div>

  <div class="panel">
    <h2>五标的信号（今日）</h2>
    <table>
      <tr><th>标的</th><th>收盘/现价</th><th>20日涨幅</th><th>20日波动率</th><th>vs MA20</th><th>判定</th></tr>
      {rows_html}
    </table>
  </div>

  <div class="panel">
    <h2>净值曲线</h2>
    <div id="navChart" class="chart"></div>
  </div>

  <div class="panel">
    <h2>最近交易记录</h2>
    <table>
      <tr><th>日期</th><th>动作</th><th>标的</th><th>份额</th><th>金额</th></tr>
      {trade_rows or '<tr><td colspan="5" style="color:#999;">暂无交易</td></tr>'}
    </table>
  </div>

  <div class="note" style="text-align:center;padding:16px;">
    数据源：真实行情（westock）｜ 300万模拟盘 ｜ 仅供个人参考，不构成投资建议<br>
    回测年化55%/回撤-8%为历史理想值，实盘受交易成本影响，请按年化20-30%预期
  </div>
</div>
<script>
  var navDates = {json.dumps(nav_dates)};
  var navVals = {json.dumps(nav_vals)};
  var totalVals = {json.dumps(total_vals)};
  var chart = echarts.init(document.getElementById('navChart'));
  chart.setOption({{
    backgroundColor: 'transparent',
    grid: {{left: 60, right: 20, top: 30, bottom: 30}},
    tooltip: {{trigger: 'axis'}},
    xAxis: {{type: 'category', data: navDates, axisLine: {{lineStyle: {{color: '#30363d'}}}}, axisLabel: {{color: '#8b949e'}}}},
    yAxis: {{
      type: 'value', scale: true,
      axisLabel: {{color: '#8b949e'}},
      splitLine: {{lineStyle: {{color: '#21262d'}}}}
    }},
    series: [{{
      name: '总资产(万元)',
      type: 'line',
      data: totalVals.map(function(v){{return (v/10000).toFixed(2);}}),
      smooth: true,
      showSymbol: false,
      lineStyle: {{color: '#f0b90b', width: 2}},
      areaStyle: {{color: 'rgba(240,185,11,0.12)'}}
    }}]
  }});
  window.addEventListener('resize', function(){{chart.resize();}});
</script>
</body>
</html>"""

    with open(OUT_HTML, "w") as f:
        f.write(html)


if __name__ == "__main__":
    main()
