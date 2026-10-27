#!/usr/bin/env python3
"""生成策略净值曲线对比 HTML（含最大回撤标注）"""
import json, os

BASE = os.path.dirname(os.path.abspath(__file__))
d = json.load(open(os.path.join(BASE, "backtest_data", "curve_compare.json")))

dates = d["dates"]
strategies = d["strategies"]

# 颜色配置（每只策略固定色）
COLORS = {
    "原策略 MA20·周频·20日动量·TOP3": "#e24b4a",
    "最优版 年线止损·周频·250日动量·TOP3": "#d85a30",
    "无止损·双周·20日动量·TOP2": "#ef9f27",
    "满仓纳指（基准）": "#378add",
    "满仓沪深300（基准）": "#888780",
}

# 生成 ECharts series 和 markArea（最大回撤区间标注）
series_js = []
for s in strategies:
    name = s["name"]
    color = COLORS.get(name, "#999")
    # 总资产（万元）
    totals_w = [round(v/10000, 2) for v in s["total"]]
    # 最大回撤区间（找到峰值和谷底的日期）
    peak_date = s["mdd_peak_date"]
    trough_date = s["mdd_trough_date"]
    series_js.append({
        "name": name,
        "color": color,
        "total_w": totals_w,
        "peak_date": peak_date,
        "trough_date": trough_date,
    })

# 构建指标表
metrics_rows = []
for s in strategies:
    metrics_rows.append({
        "name": s["name"],
        "color": COLORS.get(s["name"], "#999"),
        "ann": s["ann"],
        "mdd": s["mdd"],
        "sharpe": s["sharpe"],
        "total_ret": s["total_ret"],
        "final": s["final_total"]/10000,
    })

data_payload = {
    "dates": dates,
    "series": series_js,
}

html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>策略净值曲线对比（含最大回撤）</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ background:#0b0f17; color:#e5e9f0; font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif; padding:24px; }}
  .wrap {{ max-width:1000px; margin:0 auto; }}
  h1 {{ font-size:20px; font-weight:600; margin-bottom:4px; }}
  .sub {{ font-size:13px; color:#7d8896; margin-bottom:20px; }}
  .legend {{ display:flex; flex-wrap:wrap; gap:16px; margin-bottom:14px; font-size:13px; }}
  .legend span {{ display:flex; align-items:center; gap:6px; }}
  .dot {{ width:10px; height:10px; border-radius:2px; display:inline-block; }}
  #chart {{ width:100%; height:460px; }}
  table {{ width:100%; border-collapse:collapse; margin-top:20px; font-size:13px; }}
  th,td {{ padding:10px 12px; text-align:right; border-bottom:1px solid #1f2937; }}
  th:first-child, td:first-child {{ text-align:left; }}
  th {{ color:#7d8896; font-weight:500; background:#111722; }}
  tr:hover td {{ background:#151b26; }}
  .cname {{ display:flex; align-items:center; gap:8px; }}
  .pos {{ color:#f6465d; }}
  .neg {{ color:#0ecb81; }}
  .badge-best {{ display:inline-block; font-size:11px; padding:1px 8px; border-radius:4px; background:#f0b90b; color:#0a0e14; margin-left:8px; font-weight:600; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>五种策略 · 十年净值曲线对比（含最大回撤）</h1>
  <div class="sub">300 万本金 · 2016-01-04 至 2026-10-23 · 信号次日开盘成交（无前视偏差）· 单边 0.08% 成本</div>
  <div class="legend" id="legend"></div>
  <div id="chart"></div>
  <table>
    <thead>
      <tr><th>策略</th><th>年化</th><th>最大回撤</th><th>夏普</th><th>累计收益</th><th>期末资产</th></tr>
    </thead>
    <tbody id="tbody"></tbody>
  </table>
</div>
<script src="./echarts.min.js"></script>
<script>
const DATA = {json.dumps(data_payload, ensure_ascii=False)};
const METRICS = {json.dumps(metrics_rows, ensure_ascii=False)};

// 图例
document.getElementById('legend').innerHTML = METRICS.map(m =>
  '<span><span class="dot" style="background:' + m.color + '"></span>' + m.name + '</span>'
).join('');

// 指标表
document.getElementById('tbody').innerHTML = METRICS.map((m,i) => {{
  const annCls = m.ann>=0?'pos':'neg';
  const retCls = m.total_ret>=0?'pos':'neg';
  const best = (i===1) ? '<span class="badge-best">最优</span>' : '';
  return '<tr>' +
    '<td><span class="cname"><span class="dot" style="background:' + m.color + '"></span>' + m.name + best + '</span></td>' +
    '<td class="' + annCls + '">' + (m.ann>=0?'+':'') + m.ann.toFixed(2) + '%</td>' +
    '<td class="neg">-' + m.mdd.toFixed(2) + '%</td>' +
    '<td>' + m.sharpe.toFixed(2) + '</td>' +
    '<td class="' + retCls + '">' + (m.total_ret>=0?'+':'') + m.total_ret.toFixed(2) + '%</td>' +
    '<td>' + m.final.toFixed(0) + '万</td>' +
  '</tr>';
}}).join('');

// 图表
const chart = echarts.init(document.getElementById('chart'));
const series = DATA.series.map(s => ({{
  name: s.name,
  type: 'line',
  data: s.total_w,
  smooth: true,
  showSymbol: false,
  lineStyle: {{ width: 2, color: s.color }},
  itemStyle: {{ color: s.color }},
  emphasis: {{ focus: 'series' }},
  markArea: {{
    silent: true,
    itemStyle: {{ color: 'rgba(246,70,93,0.06)' }},
    data: [[
      {{ xAxis: s.peak_date }},
      {{ xAxis: s.trough_date }},
    ]],
  }},
  markLine: {{
    silent: true,
    symbol: 'none',
    lineStyle: {{ color: s.color, type: 'dashed', width: 1, opacity: 0.5 }},
    label: {{ show: false }},
    data: [
      {{ xAxis: s.peak_date, label: {{ show: false }} }},
      {{ xAxis: s.trough_date, label: {{ show: false }} }},
    ],
  }},
}}));

chart.setOption({{
  backgroundColor: 'transparent',
  tooltip: {{
    trigger: 'axis',
    backgroundColor: '#151b26',
    borderColor: '#2a3342',
    textStyle: {{ color: '#e5e9f0', fontSize: 12 }},
    formatter: function(ps) {{
      let s = ps[0].axisValue + '<br/>';
      ps.forEach(p => {{
        s += p.marker + p.seriesName + '：<b>' + p.value.toFixed(0) + '万</b><br/>';
      }});
      return s;
    }},
  }},
  legend: {{ show: false }},
  grid: {{ left: 60, right: 20, top: 20, bottom: 40 }},
  xAxis: {{
    type: 'category',
    data: DATA.dates,
    boundaryGap: false,
    axisLine: {{ lineStyle: {{ color: '#1f2937' }} }},
    axisLabel: {{ color: '#7d8896', fontSize: 11 }},
  }},
  yAxis: {{
    type: 'value',
    scale: true,
    axisLabel: {{ color: '#7d8896', formatter: v => v.toFixed(0) + '万' }},
    splitLine: {{ lineStyle: {{ color: 'rgba(31,41,55,0.5)' }} }},
  }},
  series: series,
}});

window.addEventListener('resize', () => chart.resize());
</script>
</body>
</html>
"""

out = os.path.join(BASE, "app_1.0", "src", "curve_compare.html")
open(out, "w").write(html)
print("✅ 生成:", out)
print(f"   数据点: {len(dates)} 天 × {len(strategies)} 策略")
