// 十二年十倍复利策略 · 信号引擎（Node.js 版，内置，无外部依赖）
// 与 live/signal_engine.py 逻辑完全一致，供 Electron 主进程使用。
// 数据源：腾讯实时行情 HTTP 接口（qt.gtimg.cn），纯内置请求，无需 westock/Python。

const https = require('https');
const fs = require('fs');
const path = require('path');
const os = require('os');

// ---------- 策略常量（与回测一致，勿改动） ----------
const ETFS = [
  { code: '510300', label: '沪深300ETF', qt: 'sh510300' },
  { code: '159915', label: '创业板ETF', qt: 'sz159915' },
  { code: '513100', label: '纳指ETF', qt: 'sh513100' },
  { code: '513500', label: '标普500ETF', qt: 'sh513500' },
  { code: '518880', label: '黄金ETF', qt: 'sh518880' },
];
const NAMES = ETFS.map(e => e.code);
const LABEL = {};
ETFS.forEach(e => { LABEL[e.code] = e.label; });

const MD = 20;            // 动量窗口
const VOL_N = 20;         // 个股波动率窗口
const VOL_LIMIT = 0.02;   // 个股日波动过滤阈值
const TOP_K = 2;          // 持仓数量
const VOL_TARGET = 0.15;  // 目标年化波动
const VOL_WIN = 20;       // 组合净值波动窗口
const TRADING_DAYS = 244;
const ANNF = Math.sqrt(TRADING_DAYS);

function isFriday(dateStr) {
  const d = new Date(dateStr + 'T00:00:00');
  return d.getDay() === 5;
}

// 双周调仓判定：与回测 is_friday(d) and (i//5)%2==0 一致
// i 为日期在交易日序列中的索引，dateStr 为该索引对应的日期
function isBiweekly(i, dateStr) {
  if (!isFriday(dateStr)) return false;
  return (Math.floor(i / 5) % 2) === 0;
}

function dailyVol(rets) {
  if (rets.length < 2) return 0;
  const m = rets.reduce((a, b) => a + b, 0) / rets.length;
  const v = rets.reduce((a, r) => a + (r - m) ** 2, 0) / rets.length;
  return Math.sqrt(v);
}

function annVol(rets) {
  return dailyVol(rets) * ANNF;
}

// ---------- 数据拉取（腾讯接口） ----------

// 延时工具（供重试退避使用）
function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

// 通用重试包装：对 fn() 做自动重试，失败后按 delayMs * 2^n 指数退避，
// retries 为最大重试次数（即首次失败后再尝试 retries 次），全部失败才 reject
function fetchWithRetry(fn, retries = 3, delayMs = 1500) {
  return fn().catch((err) => {
    if (retries <= 0) throw err;
    return sleep(delayMs).then(() => fetchWithRetry(fn, retries - 1, delayMs * 2));
  });
}

// 校验单个价格：必须是有限数（isFinite）且 >0，否则返回 NaN 视为异常
function sanitizePrice(p) {
  const n = +p;
  return (Number.isFinite(n) && n > 0) ? n : NaN;
}

// 过滤 K 线异常行：剔除 date 非法、open/close 为 0、负数、NaN、Infinity 的行
function validateKlineRows(rows) {
  if (!Array.isArray(rows)) return [];
  return rows
    .filter(r => {
      if (!r || typeof r.date !== 'string') return false;
      const o = sanitizePrice(r.open);
      const c = sanitizePrice(r.close);
      return !Number.isNaN(o) && !Number.isNaN(c);
    })
    .map(r => ({ date: r.date, open: sanitizePrice(r.open), close: sanitizePrice(r.close) }));
}

// 拉取日线（单次请求，内部使用）：https://web.ifzq.gtimg.cn/appstock/app/kline/kline?param=<code>,day,<start>,<end>,<n>,
// 返回 [{date, open, close}]，返回前已过滤异常价格行。
// 口径说明（2026-10-27 修正，经 westock/腾讯多源实测）：
//   - 本接口「第 6 个参数留空」返回真正的不复权价（拆分/分红跳空完整保留），
//     是唯一口径正确、无跳空抹平问题的价格。
//   - westock 的 kline 复权功能有缺陷：默认/--fq qfq 返回前复权价（拆分跳空被抹平），
//     --fq nofq 返回跨拆分日口径错乱的数据，--fq bfq 直接报错，均不可用。
//   - 本策略信号为「20 日动量/波动」（比值），最近 20 个交易日内无拆分/分红事件，
//     故直接用不复权价算信号即可，无需复权因子。
//   - 「当日盈亏/涨跌幅」另用实时接口真实价（fetchRealtime 的 price/prevClose）计算。
function fetchKlineOnce(qtCode, days) {
  return new Promise((resolve, reject) => {
    const url = `https://web.ifzq.gtimg.cn/appstock/app/kline/kline?param=${qtCode},day,,,${days},`;
    https.get(url, { headers: { 'User-Agent': 'Mozilla/5.0' } }, (res) => {
      let raw = [];
      res.on('data', c => raw.push(c));
      res.on('end', () => {
        try {
          const d = JSON.parse(Buffer.concat(raw).toString('utf8'));
          const k = d.data[qtCode];
          const kl = (k && (k.day || k.qfqday || k.hfqday)) || [];
          const rows = kl.map(x => ({ date: x[0], open: +x[1], close: +x[2] }));
          resolve(validateKlineRows(rows));
        } catch (e) { reject(e); }
      });
    }).on('error', reject);
  });
}

// 拉取日线（对外入口）：带自动重试，失败指数退避，全部失败才 reject
function fetchKline(qtCode, days = 60) {
  return fetchWithRetry(() => fetchKlineOnce(qtCode, days));
}

// 拉取实时行情（单次请求，内部使用）：https://qt.gtimg.cn/q=sh513100,sh513500,...
// 返回 { code: { price, prevClose, time } }
function fetchRealtimeOnce(codes) {
  return new Promise((resolve, reject) => {
    const q = codes.join(',');
    const url = `https://qt.gtimg.cn/q=${q}`;
    https.get(url, { headers: { 'User-Agent': 'Mozilla/5.0' } }, (res) => {
      let raw = [];
      res.on('data', c => raw.push(c));
      res.on('end', () => {
        try {
          const txt = Buffer.concat(raw).toString('utf8');
          const out = {};
          txt.split(';').forEach(line => {
            const m = line.match(/v_(\w+)="([^"]*)"/);
            if (!m) return;
            const f = m[2].split('~');
            out[m[1]] = {
              price: +f[3],
              prevClose: +f[4],
              time: f[30] || '',
            };
          });
          resolve(out);
        } catch (e) { reject(e); }
      });
    }).on('error', reject);
  });
}

// 拉取实时行情（对外入口）：带自动重试
function fetchRealtime(codes) {
  return fetchWithRetry(() => fetchRealtimeOnce(codes));
}

// ---------- 信号计算（纯函数） ----------
// closeMap: { code: [{date, close}...] } 完整序列
// navArr: 组合净值序列（截至 T-1，不含当日）
// navNow: T 日收盘后组合净值（用于 scale 对齐回测）
function computeSignal(closeMap, navArr, navNow) {
  const dateSets = NAMES.map(n => new Set(closeMap[n].map(x => x.date)));
  let common = [...dateSets[0]];
  for (let i = 1; i < dateSets.length; i++) {
    common = common.filter(d => dateSets[i].has(d));
  }
  common.sort();
  if (!common.length) return null;
  const T = common[common.length - 1];
  const i = common.length - 1;

  // 个股动量 + 日波动
  const metrics = {};
  for (const n of NAMES) {
    const cmap = {};
    closeMap[n].forEach(x => { cmap[x.date] = x.close; });
    if (!(T in cmap) || common.length <= MD) {
      metrics[n] = { mom: 0, vol: 999 };
      continue;
    }
    const mom = cmap[T] / cmap[common[i - MD]] - 1;
    const rets = [];
    for (let j = i - VOL_N + 1; j <= i; j++) {
      rets.push(cmap[common[j]] / cmap[common[j - 1]] - 1);
    }
    metrics[n] = { mom, vol: dailyVol(rets) };
  }

  const ranked = NAMES.slice().sort((a, b) => metrics[b].mom - metrics[a].mom);
  const target = ranked.slice(0, TOP_K).filter(n => metrics[n].mom > 0 && metrics[n].vol <= VOL_LIMIT);

  // scale（波动率目标）
  let combined = navArr.slice();
  if (navNow != null) combined = combined.concat([navNow]);
  let scale = 1.0;
  if (combined.length >= VOL_WIN + 1) {
    const rets = [];
    for (let j = combined.length - VOL_WIN; j < combined.length; j++) {
      rets.push(combined[j] / combined[j - 1] - 1);
    }
    const av = annVol(rets);
    scale = av > 0 ? Math.max(0, Math.min(1, VOL_TARGET / av)) : 1.0;
  }

  let note = '';
  if (!target.length) note = '无标的通过动量/波动过滤（空仓）';
  else if (target.length === 1) note = '仅 1 只通过过滤';

  return {
    date: T,
    index: i,
    mom: Object.fromEntries(NAMES.map(n => [n, +metrics[n].mom.toFixed(4)])),
    vol: Object.fromEntries(NAMES.map(n => [n, +metrics[n].vol.toFixed(4)])),
    target,
    scale: +scale.toFixed(4),
    isRebalance: isBiweekly(i, T),
    note,
  };
}

// ---------- 状态持久化 ----------
const STATE_FILE = path.join(os.homedir(), '.shinian-shibei', 'state.json');

function defaultState(capital) {
  return {
    capital: capital || 3000000,
    cash: capital || 3000000,
    holdings: {},   // code -> {shares, cost}
    navArr: [],     // 净值序列（接续历史后为绝对净值）
    navDates: [],   // 与 navArr 对应的日期
    lastSignalDate: null,
    priceHistory: {}, // code -> [{date, open, close}] 滚动历史
    pending: null,    // 待成交信号 {target, scale, signalDate}（T日算，T+1开盘成交）
    tradeLog: [],     // 模拟交易记录
    lastTradeDate: null, // 已处理到哪个交易日（防重复）
    continuityDone: false, // 是否已接续历史回测
  };
}

function loadState(capital) {
  try {
    if (fs.existsSync(STATE_FILE)) {
      const s = JSON.parse(fs.readFileSync(STATE_FILE, 'utf8'));
      return Object.assign(defaultState(capital), s);
    }
  } catch (e) {}
  return defaultState(capital);
}

function saveState(st) {
  fs.mkdirSync(path.dirname(STATE_FILE), { recursive: true });
  fs.writeFileSync(STATE_FILE, JSON.stringify(st, null, 2));
}

// 当前净值：净值序列基数 = 回测起步本金 300万（2014年 nav=1.0 → 300万），
// 不能除以 st.capital（接续后被设为期末总资产 3152万，会导致新净值≈1.0、曲线断崖）
const BASE_CAPITAL = 3000000;
function currentNav(st, closeOn) {
  let mv = 0;
  for (const c of NAMES) {
    const h = st.holdings[c];
    if (h) mv += h.shares * (closeOn[c] || 0);
  }
  return (st.cash + mv) / BASE_CAPITAL;
}

// ---------- A股交易日历（法定节假日，简化版） ----------
// 2024-2026 年真实休市日（仅列「周一~周五中因法定节假日休市」的日期），
// 来源：上交所/深交所各年度「部分节假日休市安排」公告。
// 周末休市由 isTradingDay 的周几判断统一排除，此处不再重复列出。
const HOLIDAYS = new Set([
  // 2024
  '2024-01-01', // 元旦
  '2024-02-09', '2024-02-12', '2024-02-13', '2024-02-14', '2024-02-15', '2024-02-16', // 春节
  '2024-04-04', '2024-04-05', // 清明
  '2024-05-01', '2024-05-02', '2024-05-03', // 劳动节
  '2024-06-10', // 端午
  '2024-09-16', '2024-09-17', // 中秋
  '2024-10-01', '2024-10-02', '2024-10-03', '2024-10-04', '2024-10-07', // 国庆
  // 2025
  '2025-01-01', // 元旦
  '2025-01-28', '2025-01-29', '2025-01-30', '2025-01-31', '2025-02-03', '2025-02-04', // 春节
  '2025-04-04', // 清明
  '2025-05-01', '2025-05-02', '2025-05-05', // 劳动节
  '2025-06-02', // 端午
  '2025-10-01', '2025-10-02', '2025-10-03', '2025-10-06', '2025-10-07', '2025-10-08', // 国庆+中秋
  // 2026
  '2026-01-01', '2026-01-02', // 元旦
  '2026-02-16', '2026-02-17', '2026-02-18', '2026-02-19', '2026-02-20', '2026-02-23', // 春节
  '2026-04-06', // 清明
  '2026-05-01', '2026-05-04', '2026-05-05', // 劳动节
  '2026-06-19', // 端午
  '2026-09-25', // 中秋
  '2026-10-01', '2026-10-02', '2026-10-05', '2026-10-06', '2026-10-07', // 国庆
]);

// 是否为 A 股交易日：周一~周五 且 不在法定节假日表内
// dateStr 形如 'YYYY-MM-DD'
function isTradingDay(dateStr) {
  const m = String(dateStr).match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!m) return false;
  const y = +m[1], mo = +m[2], dd = +m[3];
  const d = new Date(y, mo - 1, dd);
  const dow = d.getDay();
  if (dow === 0 || dow === 6) return false; // 周末休市
  const key = `${m[1]}-${m[2]}-${m[3]}`;
  return !HOLIDAYS.has(key);
}

// ---------- 数据缓存兜底 ----------
// 行情接口全部失败时，可读本地缓存兜底（当前仅提供读写函数，未强制接入 fetchKline）
const CACHE_FILE = path.join(os.homedir(), '.shinian-shibei', 'kline_cache.json');

function saveKlineCache(cacheObj) {
  fs.mkdirSync(path.dirname(CACHE_FILE), { recursive: true });
  fs.writeFileSync(CACHE_FILE, JSON.stringify(cacheObj, null, 2));
}

function loadKlineCache() {
  try {
    if (fs.existsSync(CACHE_FILE)) {
      return JSON.parse(fs.readFileSync(CACHE_FILE, 'utf8'));
    }
  } catch (e) {}
  return null;
}

module.exports = {
  ETFS, NAMES, LABEL, MD, VOL_N, VOL_LIMIT, TOP_K, VOL_TARGET, VOL_WIN,
  isFriday, isBiweekly, dailyVol, annVol,
  fetchKline, fetchRealtime, computeSignal,
  loadState, saveState, currentNav, defaultState, STATE_FILE,
  fetchWithRetry, sanitizePrice, validateKlineRows,
  HOLIDAYS, isTradingDay,
  CACHE_FILE, saveKlineCache, loadKlineCache,
};
