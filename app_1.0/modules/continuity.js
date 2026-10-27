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
  const finalNav = ls.nav;            // 11.411241
  const finalTotal = ls.total;        // 34233722
  const finalCash = ls.cash;          // 2208996
  // 期末持仓：标普500(513500) + 纳指(513100)
  const codeByLabel = {};
  eng.ETFS.forEach(e => { codeByLabel[e.label] = e.code; });
  // 从回测交易流水还原真实持仓成本（逐笔加权：买入抬升成本，清仓归零）
  const costMap = {};   // code -> 加权成本价
  const qtyMap = {};    // code -> 累计份额
  (HIST.trades || []).forEach(t => {
    const code = t.code;
    if (!code) return;
    if (t.action.includes('买')) {
      // 买入：加权抬升成本
      const q = (qtyMap[code] || 0) + t.shares;
      costMap[code] = q > 0 ? ((costMap[code] || 0) * (qtyMap[code] || 0) + t.price * t.shares) / q : t.price;
      qtyMap[code] = q;
    } else if (t.action.includes('减')) {
      // 减仓：只减份额，成本价不变
      const q = (qtyMap[code] || 0) - t.shares;
      qtyMap[code] = Math.max(0, q);
      if (q <= 0) costMap[code] = 0;
    } else if (t.action.includes('卖')) {
      // 卖出（清仓）：份额减，≤0 归零
      const q = (qtyMap[code] || 0) - t.shares;
      if (q <= 0) { qtyMap[code] = 0; costMap[code] = 0; }
      else { qtyMap[code] = q; }
    }
  });
  // 份额直接用回测流水还原的 qtyMap（精确份额），不再用市值反推。
  // 之前用 holdsLabel/price 反推，price 取的是接续时刻(10-26)的价格而非回测期末(10-23)价，
  // 导致份额算错（标普 6234700 vs 正确 6198800）。改为 qtyMap 直接取，彻底消除隐患。
  const holdings = {};
  const holdsLabel = ls.holds_label || {};
  for (const label in holdsLabel) {
    const code = codeByLabel[label];
    if (!code) continue;
    const shares = Math.round(qtyMap[code] || 0);
    if (shares <= 0) continue;
    const cost = costMap[code] > 0 ? costMap[code] : 0;
    holdings[code] = { shares, cost };
  }
  // 现金直接用 latest_state 的 cash（回测期末现金），份额已由流水精确还原
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
