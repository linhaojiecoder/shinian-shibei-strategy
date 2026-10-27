// 历史回测接续逻辑：把实盘模拟盘初始化为回测期末状态
const eng = require('../engine.js');

let ctx = null;

// 注入共享上下文（state 是可变对象，reset-state 后会整体重新赋值，需经 ctx.state 始终取最新引用）
function init(_ctx) {
  ctx = _ctx;
}

// ---------- 接续历史回测：把实盘模拟盘初始化为回测期末状态 ----------
// 历史回测 nav_series 最后一天 2026-10-23 为期末（持标普500+纳指，总资产3423万）。
// 实盘模拟盘从该期末状态接续，之后每个交易日收盘自动滚净值，实现"2014至今"连续。
function initContinuity() {
  const { state, HIST } = ctx;
  if (!HIST || !HIST.latest_state) return;
  const ls = HIST.latest_state;
  const finalNav = ls.nav;            // 10.507067
  const finalTotal = ls.total;        // 31521200
  const finalCash = ls.cash;          // 2037713
  // 期末持仓：标普500(513500) + 纳指(513100)
  const codeByLabel = {};
  eng.ETFS.forEach(e => { codeByLabel[e.label] = e.code; });

  // ==== 精确持仓还原（根治跨份额拆分成本失真）====
  // 回测 sim_v4.py 在拆分日已正确调整 shares（×ratio）和 cost（÷ratio），
  // 期末精确的 shares/cost 直接导出到 latest_state.holdings。
  // 这里优先读精确值，绝不再从交易流水反推（流水价格是不复权价、跨拆分点，
  // 反推会把拆分前旧价与拆分后新价混加权，导致成本价严重失真 —— 历史 bug 根源）。
  const holdings = {};
  const preciseHoldings = ls.holdings || {};
  if (Object.keys(preciseHoldings).length > 0) {
    for (const label in preciseHoldings) {
      const code = codeByLabel[label];
      if (!code) continue;
      const h = preciseHoldings[label];
      const shares = Math.round(h.shares || 0);
      const cost = (h.cost > 0) ? h.cost : 0;
      if (shares <= 0) continue;
      holdings[code] = { shares, cost };
    }
  } else {
    // 兜底：极老版本 data.json 无 holdings 字段时，退回流水反推（仅兼容，正常不触发）
    const costMap = {}; const qtyMap = {};
    (HIST.trades || []).forEach(t => {
      const code = t.code;
      if (!code) return;
      if (t.action.includes('买')) {
        const q = (qtyMap[code] || 0) + t.shares;
        costMap[code] = q > 0 ? ((costMap[code] || 0) * (qtyMap[code] || 0) + t.price * t.shares) / q : t.price;
        qtyMap[code] = q;
      } else if (t.action.includes('减')) {
        const q = (qtyMap[code] || 0) - t.shares;
        qtyMap[code] = Math.max(0, q);
        if (q <= 0) costMap[code] = 0;
      } else if (t.action.includes('卖')) {
        const q = (qtyMap[code] || 0) - t.shares;
        if (q <= 0) { qtyMap[code] = 0; costMap[code] = 0; }
        else { qtyMap[code] = q; }
      }
    });
    const holdsLabel = ls.holds_label || {};
    for (const label in holdsLabel) {
      const code = codeByLabel[label];
      if (!code) continue;
      const shares = Math.round(qtyMap[code] || 0);
      if (shares <= 0) continue;
      const cost = costMap[code] > 0 ? costMap[code] : 0;
      holdings[code] = { shares, cost };
    }
  }

  // 现金直接用 latest_state 的 cash（回测期末现金）
  const cash = Math.max(0, finalCash);

  state.capital = Math.round(finalTotal);
  state.cash = Math.round(cash);
  state.holdings = holdings;
  // 实盘净值序列：从期末净值开始（绝对净值，nav≈11.41）
  state.navArr = [finalNav];
  state.navDates = [(HIST.nav_series[HIST.nav_series.length - 1] || {}).date || null];
  state.lastTradeDate = (HIST.nav_series[HIST.nav_series.length - 1] || {}).date || null;
  state.continuityDone = true;
  eng.saveState(state);
  console.log(`已接续历史回测：期末总资产 ${Math.round(finalTotal).toLocaleString()}，现金 ${Math.round(cash).toLocaleString()}，持仓 ${Object.keys(holdings).join(',')}`);
}

module.exports = { init, initContinuity };
