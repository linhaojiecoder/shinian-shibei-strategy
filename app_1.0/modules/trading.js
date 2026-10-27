// 交易执行逻辑：目标持仓计算 + 虚拟交易执行（对齐回测成交规则）
const eng = require('../engine.js');

// 交易常量（与回测一致，勿改动）
const LOT = 100;
const COST = 0.0008;

let ctx = null;

// 注入共享上下文（state 是可变对象，reset-state 后会整体重新赋值，需经 ctx.state 始终取最新引用）
function init(_ctx) {
  ctx = _ctx;
}

// ---------- 计算目标持仓（整手） ----------
function computeTargetPlan(sig, priceOn) {
  const { state } = ctx;
  const target = sig.target;
  const scale = sig.scale;
  let total = state.cash;
  for (const c in state.holdings) {
    total += state.holdings[c].shares * (priceOn[c] || 0);
  }
  const n = target.length;
  const each = n > 0 ? total * scale / n : 0;
  const plan = {};
  for (const c of target) {
    const p = priceOn[c] || 0;
    if (p > 0) plan[c] = Math.floor(each / p / LOT) * LOT;
  }
  return { plan, each, total };
}

// ---------- 执行虚拟交易（用给定价格，对齐回测成交规则） ----------
function executeTrades(target, scale, priceOn, date) {
  const { state } = ctx;
  const total = state.cash + Object.keys(state.holdings).reduce((s, c) => s + state.holdings[c].shares * (priceOn[c] || 0), 0);
  const n = target.length;
  const each = n > 0 ? total * scale / n : 0;
  const log = [];

  // 1) 卖出不在目标内的
  for (const c of Object.keys(state.holdings)) {
    if (!target.includes(c)) {
      const h = state.holdings[c];
      const p = priceOn[c] || 0;
      state.cash += h.shares * p * (1 - COST);
      log.push({ date, action: '卖出', code: c, label: eng.LABEL[c], shares: h.shares, price: +p.toFixed(3) });
      delete state.holdings[c];
    }
  }
  // 2) 对目标内标的调至目标权重
  for (const c of target) {
    const p = priceOn[c] || 0;
    if (p <= 0) continue;
    const cur = state.holdings[c] ? state.holdings[c].shares : 0;
    const curV = cur * p;
    const diff = each - curV;
    if (diff > p) {
      const sh = Math.floor(diff / (p * (1 + COST)) / LOT) * LOT;
      if (sh > 0) {
        const old = state.holdings[c] ? state.holdings[c].shares : 0;
        const oldCost = state.holdings[c] ? state.holdings[c].cost : 0;
        const totalSh = old + sh;
        const newCost = totalSh > 0 ? (old * oldCost + sh * p) / totalSh : p;
        state.holdings[c] = { shares: totalSh, cost: newCost };
        state.cash -= sh * p * (1 + COST);
        log.push({ date, action: '买入', code: c, label: eng.LABEL[c], shares: sh, price: +p.toFixed(3) });
      }
    } else if (diff < -p) {
      const sh = Math.min(cur, Math.floor((-diff) / (p * (1 - COST)) / LOT) * LOT);
      if (sh > 0) {
        const newSh = cur - sh;
        state.cash += sh * p * (1 - COST);
        if (newSh > 0) state.holdings[c].shares = newSh;
        else delete state.holdings[c];
        log.push({ date, action: '减仓', code: c, label: eng.LABEL[c], shares: sh, price: +p.toFixed(3) });
      }
    }
  }
  return log;
}

module.exports = { init, computeTargetPlan, executeTrades };
