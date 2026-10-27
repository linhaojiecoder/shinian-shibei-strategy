// Electron 主进程：十二年十倍复利策略 · 实盘跟踪版
const { app, BrowserWindow, Menu, ipcMain } = require('electron');
const path = require('path');
const fs = require('fs');
const eng = require('./engine.js');

const continuity = require('./modules/continuity.js');
const trading = require('./modules/trading.js');
const report = require('./modules/report.js');
const scheduler = require('./modules/scheduler.js');

// ---------- 共享上下文：跨模块可变状态集中于此，避免各模块持有过期引用 ----------
const ctx = {
  state: null,
  lastSignal: null,
  realtimePrices: {}, // code -> { price, prevClose }（盘中实时价，收盘结算后清空）
  win: null,
  HIST: null,
};

// 向各模块注入共享上下文
continuity.init(ctx);
trading.init(ctx);
report.init(ctx);

// ---------- 历史回测序列（2014→2026-10-23），供组合总览接续 ----------
const HIST_FILE = path.join(__dirname, 'src', 'data.json');
try {
  ctx.HIST = JSON.parse(fs.readFileSync(HIST_FILE, 'utf8'));
} catch (e) {
  ctx.HIST = null;
  console.error('加载历史回测数据失败:', e.message);
}

async function refreshData() {
  const { state } = ctx;
  const priceHistory = state.priceHistory || {};
  let fetchOkCount = 0;
  for (const e of eng.ETFS) {
    try {
      const rows = await eng.fetchKline(e.qt, 80);
      if (rows && rows.length) {
        fetchOkCount++;
        const existing = {};
        (priceHistory[e.code] || []).forEach(r => { existing[r.date] = r; });
        rows.forEach(r => { existing[r.date] = r; });
        priceHistory[e.code] = Object.keys(existing).sort().map(d => existing[d]);
      }
    } catch (err) {
      console.error(`拉取 ${e.label} 失败:`, err.message);
    }
  }
  // 全部拉取失败时，读本地缓存兜底，避免清空/丢失已有价格历史
  if (fetchOkCount === 0) {
    const cache = eng.loadKlineCache();
    if (cache && cache.priceHistory) {
      state.priceHistory = cache.priceHistory;
      console.log('行情接口全部失败，已回退到本地缓存');
    }
  } else {
    state.priceHistory = priceHistory;
    // 拉取成功后更新缓存
    try { eng.saveKlineCache({ priceHistory: state.priceHistory, updatedAt: new Date().toISOString() }); } catch (e) {}
  }

  // 同时拉取「真实价（不复权）」，专用于市值/盈亏/当日盈亏显示。
  // priceHistory 存的是不复权价（用于信号动量/波动，最近20日无拆分/分红，口径正确），
  // 显示市值和当日盈亏也用真实成交价（不复权），两者口径一致。
  try {
    const qts = eng.ETFS.map(e => e.qt);
    const rt = await eng.fetchRealtime(qts);
    const realPrices = state.realPrices || {};
    for (const e of eng.ETFS) {
      const it = rt[e.qt];
      if (it && isFinite(it.price) && it.price > 0) {
        realPrices[e.code] = {
          price: it.price,          // 最新真实价
          prevClose: it.prevClose,  // 真实昨收价
          time: it.time,
        };
      }
    }
    state.realPrices = realPrices;
  } catch (err) {
    console.error('拉取真实价失败:', err.message);
  }
}

// ---------- 算信号 ----------
function computeNow() {
  const { state, HIST } = ctx;
  const closeMap = {};
  const openMap = {};
  for (const n of eng.NAMES) {
    closeMap[n] = (state.priceHistory[n] || []).map(r => ({ date: r.date, close: r.close }));
    openMap[n] = (state.priceHistory[n] || []).map(r => ({ date: r.date, open: r.open }));
  }

  // 对齐：取所有标的的「并集」全部日期（而非交集），对缺失日做前向填充（ffill）。
  // 解决 QDII（如纳指 513100）行情更新慢、少最新一根 K 线时，信号整体回退到交集旧日的问题。
  const allDatesSet = new Set();
  for (const n of eng.NAMES) {
    closeMap[n].forEach(x => allDatesSet.add(x.date));
  }
  const allDates = [...allDatesSet].sort();

  function ffillSeries(series) {
    const byDate = {};
    series.forEach(x => { byDate[x.date] = x; });
    let last = null;
    const out = [];
    for (const d of allDates) {
      if (byDate[d]) { last = byDate[d]; }
      if (last) out.push({ date: d, close: last.close, open: last.open });
    }
    return out;
  }
  for (const n of eng.NAMES) {
    closeMap[n] = ffillSeries(closeMap[n]).map(x => ({ date: x.date, close: x.close }));
    openMap[n] = ffillSeries(openMap[n]).map(x => ({ date: x.date, open: x.open }));
  }

  const dateSets = eng.NAMES.map(n => new Set(closeMap[n].map(x => x.date)));
  let common = [...dateSets[0]];
  for (let i = 1; i < dateSets.length; i++) common = common.filter(d => dateSets[i].has(d));
  common.sort();
  if (!common.length) return null;
  const latest = common[common.length - 1];

  const closeOn = {};
  const openOn = {};
  for (const n of eng.NAMES) {
    const cm = {}; const om = {};
    closeMap[n].forEach(x => { cm[x.date] = x.close; });
    openMap[n].forEach(x => { om[x.date] = x.open; });
    closeOn[n] = cm[latest] || 0;
    openOn[n] = om[latest] || 0;
  }
  const navNow = eng.currentNav(state, closeOn);

  // scale 用"历史回测净值 + 实盘净值"合并序列，避免冷启动时波动率目标失效
  let navForScale = state.navArr || [];
  if (HIST && HIST.nav_series && state.continuityDone) {
    const histNavs = HIST.nav_series.map(x => x.nav);
    navForScale = histNavs.concat(navForScale);
  }
  const sig = eng.computeSignal(closeMap, navForScale, navNow);
  return { sig, latest, closeOn, openOn, navNow, common };
}

async function runUpdate() {
  try {
    await refreshData();
    const r = computeNow();
    if (!r) return;
    const { sig, latest, closeOn, openOn, navNow, common } = r;
    const state = ctx.state;

    // 当日交易日索引（用于双周判定）
    const idx = common.length - 1;

    // ==== 首次运行：不重复处理已结算过的交易日 ====
    if (state.lastTradeDate === latest) {
      // 同一天重复运行（比如手动刷新），只重算净值，不重复交易
      ctx.lastSignal = r;
      report.writeDailyReport([]);
      if (ctx.win) ctx.win.webContents.send('signal-update', buildPayload());
      return;
    }

    // ==== 1) 执行 pending 信号（T-1 双周调仓日算出的信号，T 日开盘成交）====
    let todayTrades = [];
    if (state.pending && state.pending.target !== undefined) {
      todayTrades = trading.executeTrades(state.pending.target, state.pending.scale, openOn, latest);
      if (todayTrades.length) {
        state.tradeLog = (state.tradeLog || []).concat(todayTrades);
      }
      state.pending = null;
    }

    // ==== 2) 双周调仓日：收盘算新信号，存入 pending（供下一交易日开盘成交）====
    if (eng.isBiweekly(idx, latest)) {
      state.pending = { target: sig.target, scale: sig.scale, signalDate: latest };
    }

    // ==== 3) 收盘重估净值，追加序列 ====
    // 交易已用开盘价执行，收盘净值用收盘价重估
    const navClose = eng.currentNav(state, closeOn);
    state.navArr = state.navArr || [];
    state.navArr.push(navClose);
    state.navDates = state.navDates || [];
    state.navDates.push(latest);
    state.lastSignalDate = latest;
    state.lastTradeDate = latest;
    eng.saveState(state);

    ctx.lastSignal = r;
    ctx.realtimePrices = {}; // 收盘结算后清空盘中实时价，回到日线收盘价
    report.writeDailyReport(todayTrades);
    if (ctx.win) ctx.win.webContents.send('signal-update', buildPayload());
  } catch (e) {
    console.error('更新失败:', e);
  }
}

// ---------- 盘中实时刷新（每 5 分钟，交易日 9:30-15:00） ----------
async function refreshIntraday() {
  const now = new Date();
  if (!scheduler.isTradingDay(now) || !scheduler.isTradingHours(now)) return; // 非交易时段不拉
  try {
    const qts = eng.ETFS.map(e => e.qt);
    const rt = await eng.fetchRealtime(qts);
    for (const e of eng.ETFS) {
      const it = rt[e.qt];
      if (it && isFinite(it.price) && it.price > 0) {
        ctx.realtimePrices[e.code] = it;
      }
    }
    // 只推送价格更新，不触发交易/不滚净值/不写日报
    if (ctx.win && ctx.lastSignal) {
      ctx.win.webContents.send('signal-update', buildPayload());
    }
  } catch (e) {
    console.error('盘中刷新失败:', e);
  }
}

// ---------- 构建给渲染进程的 payload ----------
function buildPayload() {
  const r = ctx.lastSignal;
  if (!r) return null;
  const state = ctx.state;
  const realtimePrices = ctx.realtimePrices;
  const HIST = ctx.HIST;
  const { sig, latest, closeOn, navNow } = r;
  const { plan, each, total } = trading.computeTargetPlan(sig, closeOn);

  const holdings = [];
  let totalAssets = state.cash;
  for (const c in state.holdings) {
    const h = state.holdings[c];
    const rt0 = realtimePrices[c] || (state.realPrices && state.realPrices[c]);
    const price = (rt0 && isFinite(rt0.price) && rt0.price > 0) ? rt0.price : (closeOn[c] || 0);
    totalAssets += h.shares * price;
  }
  // 持股起始日：实盘 tradeLog 最近一次买入；否则回溯回测流水（接续仓位）
  function heldSince(code) {
    const live = (state.tradeLog || []).filter(t => t.code === code && String(t.action).includes('买'));
    if (live.length) return live[live.length - 1].date;
    if (HIST && HIST.trades) {
      const ht = HIST.trades.filter(t => t.code === code && String(t.action).includes('买'));
      if (ht.length) return ht[ht.length - 1].date;
    }
    return null;
  }
  for (const c in state.holdings) {
    const h = state.holdings[c];
    // 市值/盈亏/当日盈亏用「真实价（不复权）」。
    // 优先盘中实时价，其次 state.realPrices（收盘后的真实价），最后退回不复权收盘价（兜底）。
    const rt = realtimePrices[c] || (state.realPrices && state.realPrices[c]);
    let price = closeOn[c] || 0;
    let prevPrice = null;
    if (rt && isFinite(rt.price) && rt.price > 0) {
      price = rt.price;
      prevPrice = isFinite(rt.prevClose) && rt.prevClose > 0 ? rt.prevClose : null;
    }
    const value = h.shares * price;
    const costTotal = h.shares * h.cost;
    // 当日盈亏基准（昨收价）：
    //   - 有真实价时：用真实价的 prevClose（昨收）
    //   - 否则退回不复权序列的上一日收盘（仅兜底，正常不会走到）
    const rows = (state.priceHistory && state.priceHistory[c]) || [];
    const hasLatest = rows.length > 0 && rows[rows.length - 1].date === latest;
    if (prevPrice === null) {
      prevPrice = price; // 默认持平 → 当日盈亏 0
      if (hasLatest && rows.length >= 2) {
        prevPrice = rows[rows.length - 2].close;
      }
    }
    holdings.push({
      code: c, label: eng.LABEL[c],
      shares: h.shares, cost: h.cost,
      price, value,
      costTotal,
      profit: value - costTotal,
      profitPct: costTotal > 0 ? (value - costTotal) / costTotal : 0,
      prevPrice,
      dayPnl: h.shares * (price - prevPrice),
      dayPnlPct: prevPrice > 0 ? (price - prevPrice) / prevPrice : 0,
      positionPct: totalAssets > 0 ? (h.shares * price) / totalAssets : 0,
      since: heldSince(c),
    });
  }

  const etfDetail = eng.ETFS.map(e => {
    const rtp = realtimePrices[e.code] || (state.realPrices && state.realPrices[e.code]);
    const showPrice = (rtp && isFinite(rtp.price) && rtp.price > 0) ? rtp.price : (closeOn[e.code] || 0);
    return {
      code: e.code, label: e.label,
      mom: sig.mom[e.code], vol: sig.vol[e.code],
      price: showPrice,
    };
  });

  const actions = [];
  if (sig.isRebalance) {
    for (const c in state.holdings) {
      if (!sig.target.includes(c)) {
        actions.push({ type: 'sell', code: c, label: eng.LABEL[c], shares: state.holdings[c].shares, note: '清仓' });
      }
    }
    for (const c of sig.target) {
      const cur = (state.holdings[c] || {}).shares || 0;
      const tgt = plan[c] || 0;
      if (tgt > cur) actions.push({ type: 'buy', code: c, label: eng.LABEL[c], shares: tgt - cur, note: `加至 ${tgt} 份` });
      else if (tgt < cur) actions.push({ type: 'reduce', code: c, label: eng.LABEL[c], shares: cur - tgt, note: `减至 ${tgt} 份` });
      else actions.push({ type: 'hold', code: c, label: eng.LABEL[c], shares: cur, note: '不变' });
    }
  }

  // 组合总览连续序列：历史回测 nav_series + 实盘每日净值（绝对金额）
  let overviewSeries = [];
  if (HIST && HIST.nav_series) {
    overviewSeries = HIST.nav_series.map(x => ({
      date: x.date, nav: x.nav, total: Math.round(x.total),
    }));
  }
  if (state.continuityDone && state.navArr && state.navArr.length) {
    const histLastDate = overviewSeries.length ? overviewSeries[overviewSeries.length - 1].date : null;
    for (let k = 0; k < state.navArr.length; k++) {
      const nav = state.navArr[k];
      const d = (state.navDates && state.navDates[k]) || null;
      if (d && d === histLastDate) continue; // 跳过与历史期末重复的首个点
      overviewSeries.push({
        date: d || `实盘+${k}`,
        nav: +nav.toFixed(6),
        // nav 为绝对净值（2014 年 1.0 = 300 万起步），total 要乘回测起步本金而非当前 capital
        total: Math.round(nav * (HIST ? HIST.capital : 3000000)),
      });
    }
  }

  return {
    latest,
    capital: state.capital,
    cash: state.cash,
    nav: navNow,
    navArr: state.navArr,
    overviewSeries,
    holdings,
    etfDetail,
    target: sig.target.map(c => eng.LABEL[c]),
    scale: sig.scale,
    mom: sig.mom,
    vol: sig.vol,
    isRebalance: sig.isRebalance,
    note: sig.note,
    actions,
    plan,
    each,
    total,
    tradeLog: (state.tradeLog || []).slice(-20).reverse(), // 最近20笔交易
    pendingSignal: state.pending ? { date: state.pending.signalDate, target: state.pending.target.map(c => eng.LABEL[c]), scale: state.pending.scale } : null,
    isPaperTrading: true,
    lastUpdate: new Date().toLocaleString('zh-CN'),
  };
}

// ---------- IPC ----------
function registerIpc() {
  ipcMain.handle('get-signal', () => buildPayload());
  ipcMain.handle('refresh', async () => { await runUpdate(); return buildPayload(); });
  // 历史回测数据：前端通过 IPC 读取（避免 file:// 协议下 fetch 被 CORS 拦截）
  ipcMain.handle('get-data', () => ctx.HIST);

  ipcMain.handle('update-holdings', (e, payload) => {
    try {
      const { cash, holdings } = payload;
      if (typeof cash === 'number') ctx.state.cash = cash;
      if (holdings) ctx.state.holdings = holdings;
      eng.saveState(ctx.state);
      const r = computeNow();
      if (r) ctx.lastSignal = r;
      return { ok: true, payload: buildPayload() };
    } catch (err) {
      return { ok: false, error: err.message };
    }
  });

  ipcMain.handle('reset-state', (e, capital) => {
    ctx.state = eng.defaultState(capital);
    ctx.lastSignal = null;
    eng.saveState(ctx.state);
    return { ok: true };
  });
}

function createWindow() {
  ctx.win = new BrowserWindow({
    width: 1280,
    height: 860,
    minWidth: 1000,
    minHeight: 680,
    title: '十二年十倍复利策略 · 实盘跟踪',
    backgroundColor: '#0a0e14',
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js'),
    },
  });

  ctx.win.loadFile(path.join(__dirname, 'src', 'index.html'));
  Menu.setApplicationMenu(null);
}

app.whenReady().then(async () => {
  // 开机/登录自启（隐藏窗口启动也照常自动运行）
  app.setLoginItemSettings({ openAtLogin: true, args: ['--hidden'] });
  ctx.state = eng.loadState();
  registerIpc();
  createWindow();
  // 首次接续历史回测：先拉价格，再把实盘模拟盘初始化为回测期末状态
  if (!ctx.state.continuityDone) {
    await refreshData();
    continuity.initContinuity();
  }
  runUpdate();
  scheduler.scheduleNext(runUpdate);
  scheduler.scheduleIntraday(refreshIntraday); // 盘中每 5 分钟刷新实时价

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

app.on('before-quit', () => {
  scheduler.clearTimers();
});
