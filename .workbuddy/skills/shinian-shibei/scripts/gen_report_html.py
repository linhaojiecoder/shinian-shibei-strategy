#!/usr/bin/env python3
"""十二年十倍策略 · 精美 HTML 复盘页面生成器
读 app_1.0/src/data.json，生成自包含 HTML（数据内嵌 + ECharts 图表）。
双击用浏览器打开即可，颜色跟随 A 股习惯（涨红跌绿）。
输出：backtest_data/复盘报告.html
"""
import json, os

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "app_1.0", "src", "data.json")
OUT = os.path.join(BASE, "backtest_data", "复盘报告.html")

d = json.load(open(DATA))

summary = d["summary"]
latest = d["latest_state"]
nav_series = d["nav_series"]
hs300 = d["hs300_series"]
monthly = d["monthly"]
signals = d["signals"]
action = d["today_action"]
year_ret = summary.get("year_ret", {})

# 现价映射
price_map = {s["name"]: s["price"] for s in signals}

# 持仓明细（精确 shares + cost）
holdings = latest.get("holdings", {})
rows = []
for label, h in holdings.items():
    shares = h["shares"]
    cost = h["cost"]
    price = price_map.get(label)
    pnl_pct = round((price - cost) / cost * 100, 2) if (price and cost) else None
    rows.append({
        "label": label, "shares": shares, "cost": cost,
        "price": price, "pnl_pct": pnl_pct,
        "pnl_class": "up" if (pnl_pct or 0) >= 0 else "down",
    })

# 净值曲线（抽稀，全量 3102 点直接给前端，前端按需显示）
nav_dates = [x["date"] for x in nav_series]
nav_vals = [round(x["nav"], 4) for x in nav_series]
hs300_vals = [round(x["nav"], 4) for x in hs300]

# 年度收益
years = list(year_ret.keys())
year_vals = [year_ret[y] for y in years]

# 月度收益（近 12 个月）
recent_monthly = monthly[-12:]
m_labels = [m["month"] for m in recent_monthly]
m_vals = [m["ret"] for m in recent_monthly]

# 信号
sig_rows = []
for s in signals:
    sig_rows.append({
        "name": s["name"], "mom": s["mom"], "vol": s["vol"],
        "pass": s["pass"], "price": s["price"],
    })

# 序列化为 JS 变量
def js(o):
    return json.dumps(o, ensure_ascii=False)

payload = {
    "nav_dates": nav_dates, "nav_vals": nav_vals, "hs300_vals": hs300_vals,
    "years": years, "year_vals": year_vals,
    "m_labels": m_labels, "m_vals": m_vals,
    "rows": rows, "sig_rows": sig_rows,
}

# 计算几个展示值
final_total = latest["total"]
final_nav = summary["final_nav"]
total_ret = summary["total_ret"]
ann = summary["ann"]
mdd = summary["mdd"]
sharpe = summary["sharpe"]
capital = d["capital"]
cash = latest["cash"]
market = latest["market"]

up_color = "#e24b4a"      # 涨=红（A股习惯）
down_color = "#1d9e75"    # 跌=绿

html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>十二年十倍策略 · 复盘报告</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
<style>
  :root {{
    --bg: #0e1117;
    --card: #161b26;
    --card2: #1b2230;
    --border: #232a38;
    --text: #e8ecf3;
    --muted: #8b93a7;
    --up: #ff5c5c;
    --down: #2dd4a7;
    --accent: #f0b90b;
    --gap: 12px;
    --pad: 18px;
  }}
  *, *::before, *::after {{ margin:0; padding:0; box-sizing:border-box; }}
  html, body {{ max-width:100%; overflow-x:hidden; }}
  body {{
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
    padding: 20px 16px calc(48px + env(safe-area-inset-bottom));
    line-height: 1.5;
    -webkit-font-smoothing: antialiased;
  }}
  .wrap {{ width:100%; max-width:1080px; margin:0 auto; }}
  .head {{ display:flex; justify-content:space-between; align-items:flex-end; flex-wrap:wrap; gap:12px; margin-bottom:16px; }}
  .head .title {{ font-size:22px; font-weight:700; letter-spacing:.5px; }}
  .head .sub {{ color:var(--muted); font-size:13px; margin-top:4px; }}
  .date-badge {{
    background: var(--card2); border:1px solid var(--border);
    border-radius:10px; padding:10px 14px; font-size:12px; color:var(--muted);
    max-width:100%; line-height:1.6;
  }}
  .date-badge b {{ color:var(--text); font-size:14px; }}
  .hero {{
    display:grid; grid-template-columns:repeat(3, minmax(0,1fr));
    gap:var(--gap); margin:0 0 var(--gap);
  }}
  .hero .big {{
    min-width:0; max-width:100%; overflow:hidden; background:var(--card);
    border:1px solid var(--border); border-radius:14px; padding:var(--pad) 20px;
  }}
  .hero .big .label {{ color:var(--muted); font-size:12px; margin-bottom:6px; }}
  .hero .big .num {{ font-size:28px; font-weight:700; line-height:1.15; }}
  .hero .big .num.up {{ color:var(--up); }}
  .hero .big .num.down {{ color:var(--down); }}
  .hero .big .note {{ color:var(--muted); font-size:12px; margin-top:4px; }}
  .metrics {{ display:grid; grid-template-columns:repeat(4, minmax(0,1fr)); gap:var(--gap); margin-bottom:0; }}
  .metrics .m {{
    min-width:0; background:var(--card); border:1px solid var(--border);
    border-radius:12px; padding:16px;
  }}
  .metrics .m .label {{ color:var(--muted); font-size:12px; }}
  .metrics .m .num {{ font-size:20px; font-weight:700; margin-top:4px; }}
  .section {{ margin:24px 0 12px; }}
  .section .h {{ font-size:16px; font-weight:700; margin-bottom:2px; }}
  .section .d {{ color:var(--muted); font-size:13px; }}
  .card {{
    background:var(--card); border:1px solid var(--border);
    border-radius:14px; padding:var(--pad) 20px; min-width:0;
  }}
  .chart {{ width:100%; height:360px; }}
  .chart-sm {{ width:100%; height:280px; }}
  .table-wrap {{ width:100%; overflow-x:auto; -webkit-overflow-scrolling:touch; }}
  table {{ width:100%; border-collapse:collapse; font-size:14px; min-width:520px; }}
  th {{ text-align:left; color:var(--muted); font-weight:500; font-size:12px;
       padding:10px 8px; border-bottom:1px solid var(--border); white-space:nowrap; }}
  td {{ padding:13px 8px; border-bottom:1px solid var(--border); white-space:nowrap; }}
  tr:last-child td {{ border-bottom:none; }}
  .up {{ color:var(--up); }}
  .down {{ color:var(--down); }}
  .tag {{
    display:inline-block; padding:3px 10px; border-radius:20px;
    font-size:12px; font-weight:600;
  }}
  .tag.hold {{ background:#1d2a3a; color:#7fb3ff; }}
  .tag.buy {{ background:#3a1d1d; color:var(--up); }}
  .tag.pass {{ background:#12291f; color:var(--down); }}
  .tag.no {{ background:#251d1d; color:#8b93a7; }}
  .action-box {{
    display:flex; align-items:center; gap:14px; flex-wrap:wrap;
    background:var(--card); border:1px solid var(--border);
    border-radius:14px; padding:var(--pad) 20px; margin-top:var(--gap);
  }}
  .action-box .big-tag {{
    font-size:17px; font-weight:700; padding:8px 18px; border-radius:10px;
    white-space:nowrap;
  }}
  .action-box .detail {{ color:var(--muted); font-size:14px; flex:1; min-width:200px; }}
  .footer {{ color:var(--muted); font-size:12px; text-align:center; margin-top:32px; line-height:1.8; }}

  @media (max-width:900px) {{
    .hero {{ grid-template-columns:repeat(3, minmax(0,1fr)); gap:10px; }}
    .hero .big {{ padding:14px; }}
    .hero .big .num {{ font-size:24px; }}
    .metrics {{ grid-template-columns:repeat(2, minmax(0,1fr)); }}
    .chart {{ height:320px; }}
  }}
  @media (max-width:640px) {{
    body {{ padding:16px 14px calc(40px + env(safe-area-inset-bottom)); }}
    .head {{ flex-direction:column; align-items:flex-start; gap:10px; margin-bottom:14px; }}
    .head .title {{ font-size:20px; }}
    .head .sub {{ font-size:12px; }}
    .date-badge {{ padding:9px 12px; font-size:11px; width:100%; }}
    .date-badge b {{ font-size:13px; }}
    .hero {{ grid-template-columns:1fr; gap:10px; }}
    .hero .big {{ padding:14px 16px; }}
    .hero .big .num {{ font-size:24px; }}
    .metrics {{ grid-template-columns:repeat(2, minmax(0,1fr)); gap:10px; }}
    .metrics .m {{ padding:14px; }}
    .metrics .m .label {{ font-size:11px; }}
    .metrics .m .num {{ font-size:18px; margin-top:3px; }}
    .section {{ margin:22px 0 10px; }}
    .section .h {{ font-size:15px; }}
    .section .d {{ font-size:12px; }}
    .card {{ padding:14px 16px; }}
    .chart {{ height:260px; }}
    .chart-sm {{ height:220px; }}
    .action-box {{ flex-direction:column; align-items:flex-start; gap:10px; padding:14px 16px; }}
    .action-box .detail {{ min-width:0; font-size:13px; }}
    .footer {{ margin-top:28px; padding:16px 0 8px; font-size:11px; }}
    table {{ min-width:460px; }}
  }}
</style>
</head>
<body>
<div class="wrap">
  <div class="head">
    <div>
      <div class="title">十二年十倍复利策略</div>
      <div class="sub">慢慢变富，与时间为友 · A股 ETF 动量轮动</div>
    </div>
    <div class="date-badge">
      数据截至 <b>{d['latest_date']}</b><br>
      初始本金 ¥{capital:,}
    </div>
  </div>

  <div class="hero">
    <div class="big">
      <div class="label">期末总资产</div>
      <div class="num">¥{final_total:,.0f}</div>
      <div class="note">累计收益 <span class="{ 'up' if total_ret>=0 else 'down' }">{total_ret:+.2f}%</span></div>
    </div>
    <div class="big">
      <div class="label">年化收益</div>
      <div class="num { 'up' if ann>=0 else 'down' }">{ann:+.2f}%</div>
      <div class="note">最大回撤 {mdd}%</div>
    </div>
    <div class="big">
      <div class="label">当前净值</div>
      <div class="num">{final_nav:.2f}</div>
      <div class="note">现金 ¥{cash:,.0f} · 持仓 ¥{market:,.0f}</div>
    </div>
  </div>

  <div class="metrics">
    <div class="m"><div class="label">最大回撤</div><div class="num">-{mdd}%</div></div>
    <div class="m"><div class="label">夏普比率</div><div class="num">{sharpe}</div></div>
    <div class="m"><div class="label">累计收益</div><div class="num { 'up' if total_ret>=0 else 'down' }">{total_ret:+.1f}%</div></div>
    <div class="m"><div class="label">交易次数</div><div class="num">{summary['trades']}</div></div>
  </div>

  <div class="section">
    <div class="h">净值曲线（策略 vs 沪深300）</div>
    <div class="d">2014 年至今，初始净值 1.0</div>
  </div>
  <div class="card"><div id="navChart" class="chart"></div></div>

  <div class="section">
    <div class="h">当前持仓</div>
    <div class="d">精确份额与成本价（不复权真实价口径）</div>
  </div>
  <div class="card">
    <div class="table-wrap">
      <table>
        <thead><tr><th>标的</th><th>持有份额</th><th>成本价</th><th>现价</th><th>浮动盈亏</th></tr></thead>
        <tbody id="holdBody"></tbody>
      </table>
    </div>
  </div>

  <div class="action-box">
    <div class="big-tag { 'buy' if action['type']=='buy' else 'hold' }">{action['title']}</div>
    <div class="detail">{action['detail']}</div>
  </div>

  <div class="section">
    <div class="h">五标的动量信号</div>
    <div class="d">20 日动量 &gt; 0 且波动率 ≤ 2% 才通过筛选</div>
  </div>
  <div class="card">
    <div class="table-wrap">
      <table>
        <thead><tr><th>标的</th><th>20日动量</th><th>波动率</th><th>现价</th><th>筛选</th></tr></thead>
        <tbody id="sigBody"></tbody>
      </table>
    </div>
  </div>

  <div class="section">
    <div class="h">年度收益</div>
    <div class="d">每年收益（%）</div>
  </div>
  <div class="card"><div id="yearChart" class="chart-sm"></div></div>

  <div class="section">
    <div class="h">近 12 月收益</div>
  </div>
  <div class="card"><div id="monthChart" class="chart-sm"></div></div>

  <div class="footer">数据口径：不复权真实价 + 份额拆分正确处理 + 分红现金入账 · 自动生成，仅供个人参考，不构成投资建议</div>
</div>

<script>
const P = {js(payload)};
const UP = "{up_color}";
const DOWN = "{down_color}";

const rows = P.rows;
const hb = document.getElementById('holdBody');
hb.innerHTML = rows.map(r => `
  <tr>
    <td style="font-weight:600">${{r.label}}</td>
    <td>${{r.shares.toLocaleString()}}</td>
    <td>${{r.cost.toFixed(4)}}</td>
    <td>${{r.price}}</td>
    <td class="${{r.pnl_class}}">${{(r.pnl_pct>=0?'+':'') + r.pnl_pct.toFixed(2)}}%</td>
  </tr>`).join('');

const sb = document.getElementById('sigBody');
sb.innerHTML = P.sig_rows.map(s => `
  <tr>
    <td style="font-weight:600">${{s.name}}</td>
    <td class="${{s.mom>=0?'up':'down'}}">${{(s.mom>=0?'+':'') + s.mom.toFixed(2)}}%</td>
    <td>${{s.vol.toFixed(2)}}%</td>
    <td>${{s.price}}</td>
    <td><span class="tag ${{s.pass?'pass':'no'}}">${{s.pass?'通过':'未通过'}}</span></td>
  </tr>`).join('');

function lineChart(el, dates, s1, s2, name1, name2) {{
  const c = echarts.init(el);
  c.setOption({{
    backgroundColor: 'transparent',
    grid: {{ left:50, right:20, top:20, bottom:30 }},
    tooltip: {{ trigger:'axis', backgroundColor:'#1b2230', borderColor:'#232a38', textStyle:{{color:'#e8ecf3'}} }},
    xAxis: {{ type:'category', data:dates, axisLine:{{lineStyle:{{color:'#232a38'}}}},
              axisLabel:{{color:'#8b93a7', fontSize:11}} }},
    yAxis: {{ type:'value', scale:true, splitLine:{{lineStyle:{{color:'#1c2230'}}}},
              axisLabel:{{color:'#8b93a7', fontSize:11}} }},
    series: [
      {{ name:name1, type:'line', data:s1, showSymbol:false, lineStyle:{{width:2, color:'#f0b90b'}},
         areaStyle:{{color:'rgba(240,185,11,0.08)'}} }},
      {{ name:name2, type:'line', data:s2, showSymbol:false, lineStyle:{{width:1.5, color:'#7fb3ff'}} }},
    ],
    legend: {{ textStyle:{{color:'#8b93a7'}}, top:0, icon:'roundRect' }}
  }});
  return c;
}}

function barChart(el, labels, vals) {{
  const c = echarts.init(el);
  c.setOption({{
    backgroundColor:'transparent',
    grid: {{ left:50, right:20, top:20, bottom:30 }},
    tooltip: {{ trigger:'axis', backgroundColor:'#1b2230', borderColor:'#232a38', textStyle:{{color:'#e8ecf3'}} }},
    xAxis: {{ type:'category', data:labels, axisLine:{{lineStyle:{{color:'#232a38'}}}},
              axisLabel:{{color:'#8b93a7', fontSize:11}} }},
    yAxis: {{ type:'value', splitLine:{{lineStyle:{{color:'#1c2230'}}}},
              axisLabel:{{color:'#8b93a7', fontSize:11, formatter:'{{value}}%'}} }},
    series: [{{
      type:'bar', data: vals.map(v=>{{return {{value:v, itemStyle:{{color: v>=0?UP:DOWN}}}};}}),
      barWidth:'55%'
    }}]
  }});
  return c;
}}

lineChart(document.getElementById('navChart'), P.nav_dates, P.nav_vals, P.hs300_vals, '策略', '沪深300');
barChart(document.getElementById('yearChart'), P.years, P.year_vals);
barChart(document.getElementById('monthChart'), P.m_labels, P.m_vals);

window.addEventListener('resize', () => {{
  ['navChart','yearChart','monthChart'].forEach(id => {{
    const c = echarts.getInstanceByDom(document.getElementById(id));
    if (c) c.resize();
  }});
}});
</script>
</body>
</html>
"""

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w") as f:
    f.write(html)

print(f"✅ 复盘报告已生成：{OUT}")
print(f"   数据截至 {d['latest_date']}，累计收益 {total_ret:+.2f}%，期末 ¥{final_total:,.0f}")
