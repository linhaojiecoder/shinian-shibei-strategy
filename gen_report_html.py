#!/usr/bin/env python3
"""慢富十倍·复利策略 · 精美 HTML 复盘页面生成器
读 app_1.0/src/data.json，生成自包含 HTML（数据内嵌 + ECharts 图表）。
双击用浏览器打开即可，颜色跟随 A 股习惯（涨红跌绿）。
输出：backtest_data/复盘报告.html
"""
import json, os, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "app_1.0", "src", "data.json")
OUT = os.path.join(BASE, "backtest_data", "复盘报告.html")

d = json.load(open(DATA))


def next_rebalance_date(latest_date, trades):
    """推算下次调仓「信号日」（双周周五）。
    规则：最近一次成交日是周一（周五信号日 → 次一交易日周一开盘成交），
    下一个信号日 = 最近信号日 + 14 天。
    从 trades 最近一条成交日反推：成交日(周一) - 3 天 = 信号日(周五)。
    """
    if not trades:
        return None
    last_trade = trades[-1]["date"]
    last_dt = datetime.datetime.strptime(last_trade, "%Y-%m-%d")
    # 成交日所在周周五 = 成交日 + (4 - weekday) 天（weekday: 周一=0..周日=6）
    signal_dt = last_dt + datetime.timedelta(days=(4 - last_dt.weekday()))
    # 若成交日本身晚于该周五（如成交日就是周五收盘后），信号日应回退上一周五
    if signal_dt > last_dt:
        signal_dt = signal_dt - datetime.timedelta(days=7)
    # 下一个信号日 = 最近信号日 + 14 天
    nxt = signal_dt + datetime.timedelta(days=14)
    # 若已过 latest_date，继续 +14 直到未来
    latest_dt = datetime.datetime.strptime(latest_date, "%Y-%m-%d")
    while nxt <= latest_dt:
        nxt = nxt + datetime.timedelta(days=14)
    return nxt.strftime("%Y-%m-%d")

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

# 持仓明细（精确 shares + cost + 增强字段）
holdings = latest.get("holdings", {})
rows = []
for label, h in holdings.items():
    shares = h["shares"]
    cost = h["cost"]
    price = price_map.get(label)
    pnl_pct = round((price - cost) / cost * 100, 2) if (price and cost) else None
    mv = h.get("mv")
    day_pnl = h.get("day_pnl")
    total_pnl = h.get("total_pnl")
    weight = h.get("weight")
    hold_days = h.get("hold_days")
    rows.append({
        "label": label, "shares": shares, "cost": cost,
        "price": price, "pnl_pct": pnl_pct,
        "pnl_class": "up" if (pnl_pct or 0) >= 0 else "down",
        "mv": mv, "day_pnl": day_pnl, "total_pnl": total_pnl,
        "weight": weight, "hold_days": hold_days,
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
today_pnl = latest.get("today_pnl", 0)
asset_change = latest.get("asset_change", 0)
pos_total_pnl = latest.get("pos_total_pnl", 0)

# 下次调仓信号日（双周周五）与倒计时
nb_date = next_rebalance_date(d["latest_date"], d.get("trades", []))
nb_days = None
if nb_date:
    nb_dt = datetime.datetime.strptime(nb_date, "%Y-%m-%d")
    nb_days = (nb_dt.date() - datetime.date.today()).days
    nb_days = max(0, nb_days)

# 今日总资产变动百分比（相对昨日）
_prev_total = final_total - asset_change
if _prev_total and asset_change:
    asset_pct = round(asset_change / _prev_total * 100, 2)
    asset_pct_s = f"（{'+' if asset_pct>=0 else ''}{asset_pct:.2f}%）"
else:
    asset_pct_s = ""

up_color = "#e24b4a"      # 涨=红（A股习惯）
down_color = "#1d9e75"    # 跌=绿

html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>慢富十倍·复利策略 · 复盘报告</title>
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
  .next-reb {{
    display:flex; align-items:center; gap:10px; flex-wrap:wrap;
    background:linear-gradient(135deg, rgba(240,185,11,.10), rgba(240,185,11,.02));
    border:1px solid rgba(240,185,11,.28); border-radius:12px;
    padding:12px 16px; margin:0 0 var(--gap); font-size:13px;
  }}
  .next-reb .nr-icon {{ font-size:16px; }}
  .next-reb .nr-txt {{ color:var(--text); }}
  .next-reb .nr-txt b {{ color:var(--accent); }}
  .next-reb .nr-count {{ color:var(--muted); margin-left:auto; white-space:nowrap; }}
  .next-reb .nr-count b {{ color:var(--text); }}
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
  /* 移动端卡片式列表（桌面端隐藏，≤640px 显示） */
  .card-list {{ display:none; }}
  .hold-card {{
    background:var(--card2); border:1px solid var(--border); border-radius:12px;
    padding:14px 16px; margin-bottom:10px;
  }}
  .hold-card:last-child {{ margin-bottom:0; }}
  .hc-head {{ display:flex; align-items:center; justify-content:space-between; margin-bottom:10px; }}
  .hc-name {{ font-size:15px; font-weight:700; }}
  .hc-mv {{ font-size:14px; font-weight:700; }}
  .hc-grid {{ display:grid; grid-template-columns:repeat(2, minmax(0,1fr)); gap:10px 14px; }}
  .hc-item {{ min-width:0; }}
  .hc-item .k {{ font-size:11px; color:var(--muted); }}
  .hc-item .v {{ font-size:14px; font-weight:600; margin-top:2px; }}
  .hc-item .v.sub {{ font-size:12px; font-weight:500; color:var(--muted); }}
  .sig-card-m {{
    display:flex; align-items:center; gap:12px;
    background:var(--card2); border:1px solid var(--border); border-radius:12px;
    padding:12px 16px; margin-bottom:10px;
  }}
  .sig-card-m:last-child {{ margin-bottom:0; }}
  .scm-name {{ font-size:14px; font-weight:700; flex:1; min-width:0; }}
  .scm-mom {{ font-size:14px; font-weight:700; }}
  .scm-vol {{ font-size:12px; color:var(--muted); }}

  table {{ width:100%; border-collapse:collapse; font-size:14px; min-width:520px; }}
  th {{ text-align:left; color:var(--muted); font-weight:500; font-size:12px;
       padding:10px 8px; border-bottom:1px solid var(--border); white-space:nowrap; }}
  td {{ padding:13px 8px; border-bottom:1px solid var(--border); white-space:nowrap; }}
  tr:last-child td {{ border-bottom:none; }}
  .up {{ color:var(--up); }}
  .down {{ color:var(--down); }}
  .muted2 {{ color:var(--muted); font-size:11px; }}
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
    /* 移动端：表格隐藏，改用卡片式竖排 */
    .table-wrap {{ display:none; }}
    .card-list {{ display:block; }}
    .next-reb {{ align-items:flex-start; flex-direction:column; gap:6px; padding:12px 14px; font-size:12px; }}
    .next-reb .nr-count {{ margin-left:0; }}
    .hc-grid {{ gap:8px 10px; }}
    .hc-item .v {{ font-size:13px; }}
  }}
</style>
</head>
<body>
<div class="wrap">
  <div class="head">
    <div>
      <div class="title">慢富十倍·复利策略</div>
      <div class="sub">慢慢变富，与时间为友 · A股 ETF 动量轮动</div>
    </div>
    <div class="date-badge">
      数据截至 <b>{d['latest_date']}</b><br>
      初始本金 ¥{capital:,}
    </div>
  </div>

  <div class="hero">
    <div class="big">
      <div class="label">总资产</div>
      <div class="num">¥{final_total:,.0f}</div>
      <div class="note">今日 <span class="{ 'up' if asset_change>=0 else 'down' }">{asset_change:+,.0f}</span>{asset_pct_s}</div>
    </div>
    <div class="big">
      <div class="label">今日盈亏</div>
      <div class="num { 'up' if today_pnl>=0 else 'down' }">{today_pnl:+,.0f}</div>
      <div class="note">持仓浮动盈亏 {pos_total_pnl:+,.0f}</div>
    </div>
    <div class="big">
      <div class="label">累计收益</div>
      <div class="num { 'up' if total_ret>=0 else 'down' }">{total_ret:+.1f}%</div>
      <div class="note">初始本金 ¥{capital:,}</div>
    </div>
  </div>

  <div class="next-reb">
    <span class="nr-icon">🗓</span>
    <span class="nr-txt">下次调仓：<b>{nb_date}</b>（周五信号，次一交易日开盘执行）</span>
    <span class="nr-count">距今 <b>{nb_days}</b> 天</span>
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
        <thead><tr><th>标的</th><th>持仓(份)</th><th>成本/现价</th><th>市值</th><th>当日盈亏</th><th>总盈亏</th><th>个股仓位</th><th>持股天数</th></tr></thead>
        <tbody id="holdBody"></tbody>
      </table>
    </div>
    <div class="card-list" id="holdCards"></div>
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
    <div class="card-list" id="sigCards"></div>
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
const fmtMoney = v => v==null ? '—' : '¥' + Math.round(v).toLocaleString();
const fmtSigned = v => v==null ? '—' : (v>=0?'+':'') + Math.round(v).toLocaleString();
const fmtPct = v => v==null ? '—' : (v>=0?'+':'') + v.toFixed(2) + '%';
const cls = v => v==null ? '' : (v>=0?'up':'down');
hb.innerHTML = rows.map(r => `
  <tr>
    <td style="font-weight:600">${{r.label}}</td>
    <td>${{r.shares.toLocaleString()}}</td>
    <td>${{r.cost.toFixed(4)}}<br><span class="muted2">${{r.price}}</span></td>
    <td>${{fmtMoney(r.mv)}}</td>
    <td class="${{cls(r.day_pnl)}}">${{fmtSigned(r.day_pnl)}}</td>
    <td class="${{cls(r.total_pnl)}}">${{fmtSigned(r.total_pnl)}}<br><span class="muted2">${{fmtPct(r.pnl_pct)}}</span></td>
    <td>${{r.weight==null?'—':r.weight.toFixed(2)+'%'}}</td>
    <td>${{r.hold_days==null?'—':r.hold_days+'天'}}</td>
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

// 移动端卡片：持仓（每标的竖排字段）
const hc = document.getElementById('holdCards');
hc.innerHTML = rows.map(r => `
  <div class="hold-card">
    <div class="hc-head">
      <span class="hc-name">${{r.label}}</span>
      <span class="hc-mv">${{fmtMoney(r.mv)}}</span>
    </div>
    <div class="hc-grid">
      <div class="hc-item"><div class="k">持仓(份)</div><div class="v">${{r.shares.toLocaleString()}}</div></div>
      <div class="hc-item"><div class="k">成本 / 现价</div><div class="v">${{r.cost.toFixed(4)}} <span class="v sub">/ ${{r.price}}</span></div></div>
      <div class="hc-item"><div class="k">当日盈亏</div><div class="v ${{cls(r.day_pnl)}}">${{fmtSigned(r.day_pnl)}}</div></div>
      <div class="hc-item"><div class="k">总盈亏</div><div class="v ${{cls(r.total_pnl)}}">${{fmtSigned(r.total_pnl)}} <span class="v sub">${{fmtPct(r.pnl_pct)}}</span></div></div>
      <div class="hc-item"><div class="k">个股仓位</div><div class="v">${{r.weight==null?'—':r.weight.toFixed(2)+'%'}}</div></div>
      <div class="hc-item"><div class="k">持股天数</div><div class="v">${{r.hold_days==null?'—':r.hold_days+'天'}}</div></div>
    </div>
  </div>`).join('');

// 移动端卡片：五标的信号
const sc = document.getElementById('sigCards');
sc.innerHTML = P.sig_rows.map(s => `
  <div class="sig-card-m">
    <span class="scm-name">${{s.name}}</span>
    <span class="scm-vol">波动 ${{s.vol.toFixed(2)}}%</span>
    <span class="scm-mom ${{s.mom>=0?'up':'down'}}">${{(s.mom>=0?'+':'') + s.mom.toFixed(2)}}%</span>
    <span class="tag ${{s.pass?'pass':'no'}}">${{s.pass?'通过':'未通过'}}</span>
  </div>`).join('');

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
