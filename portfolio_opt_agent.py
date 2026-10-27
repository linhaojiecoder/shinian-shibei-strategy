#!/usr/bin/env python3
"""组合优化替代等权TOP2动量 · 对比回测

用现代组合优化（风险平价/等风险贡献/最小方差/最大夏普）替代"等权TOP2动量"，
在同一引擎、同一成本、同一调仓节奏下做公平对比。

标的池：510300 沪深300 / 159915 创业板 / 513100 纳指 / 513500 标普500 / 518880 黄金
规则：次日开盘成交 · 无止损 · 双周调仓 · 20日动量选股 · 单边0.08%成本 · 300万起
"""
import json, os, math
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "backtest_data", "prices_10y_open.json")

ETFS = [("510300","沪深300"),("159915","创业板"),("513100","纳指"),("513500","标普500"),("518880","黄金")]
NAMES = [c for c,_ in ETFS]
LABEL = {c:n for c,n in ETFS}
N = len(NAMES)

CAPITAL = 3_000_000
MD = 20          # 动量窗口
VOL_N = 20       # 波动率过滤窗口
VOL_LIMIT = 0.02
COST = 0.0008
START = "2016-01-01"
LOT = 100
TRADING_DAYS = 244

DATES = []


# ---------------- 线性代数（纯Python，5x5足够） ----------------

def matvec(A, x):
    return [sum(A[i][j]*x[j] for j in range(len(x))) for i in range(len(A))]

def dot(x, y):
    return sum(a*b for a, b in zip(x, y))

def quadratic(A, x):
    return dot(x, matvec(A, x))

def inverse(A, ridge=1e-10):
    """Gauss-Jordan 求逆，加极小对角ridge保证稳定"""
    n = len(A)
    M = []
    for i in range(n):
        row = [A[i][j] for j in range(n)] + [1.0 if i == j else 0.0 for j in range(n)]
        row[i] += ridge
        M.append(row)
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[piv][col]) < 1e-16:
            raise ValueError("singular matrix")
        if piv != col:
            M[col], M[piv] = M[piv], M[col]
        pv = M[col][col]
        for j in range(2*n):
            M[col][j] /= pv
        for r in range(n):
            if r != col and abs(M[r][col]) > 1e-16:
                f = M[r][col]
                for j in range(2*n):
                    M[r][j] -= f * M[col][j]
    return [row[n:] for row in M]


# ---------------- 权重计算 ----------------

def erc_weights(cov, max_iter=5000, tol=1e-12):
    """等风险贡献权重（Maillard et al. 乘法迭代）"""
    n = len(cov)
    w = [1.0/n]*n
    for _ in range(max_iter):
        sw = matvec(cov, w)
        var = dot(w, sw)
        if var <= 1e-20:
            return w
        target = var / n
        nw = []
        for i in range(n):
            rc = w[i]*sw[i]
            nw.append(w[i]*math.sqrt(target/rc) if (rc > 1e-20 and sw[i] > 0) else 0.0)
        s = sum(nw)
        if s <= 0:
            break
        nw = [x/s for x in nw]
        diff = max(abs(nw[i]-w[i]) for i in range(n))
        w = nw
        if diff < tol:
            break
    return w


def minvar_weights(cov):
    """最小方差（长仓、全仓，枚举active set精确求解）"""
    n = len(cov)
    best, best_var = None, float("inf")
    for mask in range(1, 1 << n):
        idx = [i for i in range(n) if (mask >> i) & 1]
        m = len(idx)
        sub = [[cov[a][b] for b in idx] for a in idx]
        inv = inverse(sub)
        num = matvec(inv, [1.0]*m)
        den = sum(num)
        if den <= 0:
            continue
        wsub = [x/den for x in num]
        if all(x > 1e-9 for x in wsub):
            v = quadratic(sub, wsub)
            if v < best_var:
                best_var = v
                wf = [0.0]*n
                for k, i in enumerate(idx):
                    wf[i] = wsub[k]
                best = wf
    return best if best is not None else [1.0/n]*n


def maxsharpe_weights(cov, means):
    """最大夏普（长仓、全仓，枚举active set精确求解）"""
    n = len(cov)
    best, best_sh = None, -float("inf")
    for mask in range(1, 1 << n):
        idx = [i for i in range(n) if (mask >> i) & 1]
        m = len(idx)
        sub = [[cov[a][b] for b in idx] for a in idx]
        mu = [means[i] for i in idx]
        inv = inverse(sub)
        num = matvec(inv, mu)
        den = sum(num)
        if den <= 0:
            continue
        wsub = [x/den for x in num]
        if all(x > 1e-9 for x in wsub):
            v = quadratic(sub, wsub)
            if v <= 1e-20:
                continue
            sh = dot(mu, wsub) / math.sqrt(v)
            if sh > best_sh:
                best_sh = sh
                wf = [0.0]*n
                for k, i in enumerate(idx):
                    wf[i] = wsub[k]
                best = wf
    return best if best is not None else [1.0/n]*n


# ---------------- 回测引擎 ----------------

def pstdev(x):
    m = sum(x)/len(x)
    return math.sqrt(sum((v-m)**2 for v in x)/len(x))


def compute_weights(mode, K, W, i, close, rets):
    """在信号日 i（收盘后）计算 N 只标的的目标权重（和为1，未持有=0）"""
    # 20日波动（过滤用）
    vol20 = []
    for n in range(N):
        r = rets[n][i-VOL_N+1:i+1]
        vol20.append(pstdev(r))
    # 20日动量
    mom = [close[NAMES[n]][DATES[i]] / close[NAMES[n]][DATES[i-MD]] - 1 for n in range(N)]

    # 选择标的
    if mode.endswith("_full"):
        sel = list(range(N))
    else:
        ranked = sorted(range(N), key=lambda k: mom[k], reverse=True)
        sel = [k for k in ranked[:K] if mom[k] > 0 and vol20[k] <= VOL_LIMIT]

    w = [0.0]*N
    if not sel:
        return w

    if mode.startswith("equal"):
        for k in sel:
            w[k] = 1.0/len(sel)
        return w

    if mode.startswith("rp"):
        # 1/波动率加权（波动率用W日窗口样本标准差）
        inv = []
        for n in range(N):
            r = rets[n][i-W+1:i+1]
            sd = pstdev(r)
            inv.append(1.0/sd if sd > 0 else 0.0)
        s = sum(inv[k] for k in sel)
        for k in sel:
            w[k] = inv[k]/s if s > 0 else 1.0/len(sel)
        return w

    # 需要协方差矩阵的模式
    cov = [[0.0]*N for _ in range(N)]
    means = [0.0]*N
    for a in range(N):
        ra = rets[a][i-W+1:i+1]
        means[a] = sum(ra)/W
        for b in range(N):
            rb = rets[b][i-W+1:i+1]
            cov[a][b] = sum((ra[t]-means[a])*(rb[t]-means[b]) for t in range(W)) / (W-1)

    if mode.startswith("erc"):
        sub = [[cov[a][b] for b in sel] for a in sel]
        wsub = erc_weights(sub)
    elif mode.startswith("minvar"):
        sub = [[cov[a][b] for b in sel] for a in sel]
        wsub = minvar_weights(sub)
    elif mode.startswith("maxsharpe"):
        sub = [[cov[a][b] for b in sel] for a in sel]
        sub_mu = [means[k] for k in sel]
        wsub = maxsharpe_weights(sub, sub_mu)
    else:
        return w

    for k, idx in enumerate(sel):
        w[idx] = wsub[k]
    return w


def run_backtest(mode, K, W, exec_mode="full"):
    """exec_mode: 'full'=全再平衡(减超配+加低配), 'topup'=只加不减(复刻参考脚本，赢家不动)"""
    data = json.load(open(DATA))
    date_sets = [set(d for d, _ in data[n]) for n in NAMES]
    global DATES
    DATES = sorted(set.intersection(*date_sets))
    DATES = [d for d in DATES if d >= START]
    close = {n: {d: v[1] for d, v in data[n]} for n in NAMES}
    openp = {n: {d: v[0] for d, v in data[n]} for n in NAMES}

    L = len(DATES)
    # 逐标的日收益（对齐DATES），rets[n][0]=0
    rets = []
    for n in NAMES:
        r = [0.0]*L
        for i in range(1, L):
            r[i] = close[n][DATES[i]] / close[n][DATES[i-1]] - 1
        rets.append(r)

    holdings = {}   # code -> shares
    cash = CAPITAL
    navs = []
    pending = None
    trades = 0
    warm = max(MD, W, VOL_N)

    for i, d in enumerate(DATES):
        # 执行pending（次日开盘成交）
        if i > 0 and pending is not None:
            if exec_mode == "full":
                mv = sum(holdings[c]*openp[c][d] for c in holdings)
                total = cash + mv
                for c in NAMES:
                    wt = pending.get(c, 0.0)
                    p = openp[c][d]
                    cur_sh = holdings.get(c, 0)
                    target_val = total * wt
                    diff = target_val - cur_sh * p
                    if diff > 0:
                        sh = int(diff / (p*(1+COST))) // LOT * LOT
                        if sh > 0:
                            cost = sh*p*(1+COST)
                            if cost <= cash + 1e-6:
                                holdings[c] = holdings.get(c, 0) + sh
                                cash -= cost
                                trades += 1
                    elif diff < 0:
                        sell_sh = min(cur_sh, int((-diff)/p) // LOT * LOT)
                        if sell_sh > 0:
                            holdings[c] -= sell_sh
                            if holdings[c] == 0:
                                del holdings[c]
                            cash += sell_sh*p*(1-COST)
                            trades += 1
            else:  # topup：先卖出不在目标内的，再只买低配的，永不减超配
                for code in list(holdings.keys()):
                    if code not in pending:
                        sh = holdings.pop(code)
                        cash += sh*openp[code][d]*(1-COST)
                        trades += 1
                if pending:
                    mv = sum(holdings[c]*openp[c][d] for c in holdings)
                    total = cash + mv
                    for c, wt in pending.items():
                        p = openp[c][d]
                        cur_sh = holdings.get(c, 0)
                        target_val = total * wt
                        diff = target_val - cur_sh * p
                        if diff > p:
                            sh = int(diff / (p*(1+COST))) // LOT * LOT
                            if sh > 0:
                                cost = sh*p*(1+COST)
                                if cost <= cash + 1e-6:
                                    holdings[c] = holdings.get(c, 0) + sh
                                    cash -= cost
                                    trades += 1
            pending = None

        # 双周调仓信号（T日收盘后计算）
        if i >= warm and is_biweekly(i):
            w = compute_weights(mode, K, W, i, close, rets)
            pending = {NAMES[c]: w[c] for c in range(N) if w[c] > 1e-9}

        # 收盘净值
        mv = sum(holdings[c]*close[c][d] for c in holdings)
        navs.append((cash + mv) / CAPITAL)

    return summarize(navs, trades)


def is_biweekly(i):
    d = DATES[i]
    return datetime.strptime(d, "%Y-%m-%d").weekday() == 4 and (i // 5) % 2 == 0


def summarize(navs, trades):
    days = len(navs)
    years = days / TRADING_DAYS
    total_ret = (navs[-1]/navs[0]-1)*100
    ann = (navs[-1]/navs[0])**(1/years)-1
    peak = navs[0]; mdd = 0.0
    for v in navs:
        peak = max(peak, v)
        mdd = max(mdd, (peak-v)/peak)
    rets = [navs[i]/navs[i-1]-1 for i in range(1, days)]
    m = sum(rets)/len(rets)
    sd = math.sqrt(sum((r-m)**2 for r in rets)/len(rets))
    sharpe = m/sd*math.sqrt(TRADING_DAYS) if sd > 0 else 0
    calmar = (ann*100)/(mdd*100) if mdd > 0 else 0
    return {
        "ann": ann*100, "mdd": mdd*100, "sharpe": sharpe, "calmar": calmar,
        "trades": trades, "total_ret": total_ret,
        "final": navs[-1]*CAPITAL, "years": years,
    }


# ---------------- 主流程 ----------------

def main():
    print(f"标的：{' / '.join(f'{c}{LABEL[c]}' for c in NAMES)}")
    print(f"成本{COST*100:.2f}%/边 · 双周调仓 · 次日开盘成交 · 300万起 · {START}~2026-10-23\n")

    # 方案定义：(name, mode, K, W, exec_mode)
    # 框架A：动量选股 + 只加不减（复刻参考脚本执行，与基线同框架，仅换权重）
    plans = [
        ("A·基线 等权TOP2",        "equal_top2",    2, 20, "topup"),
        ("A·RP(1/vol) TOP2",      "rp_top2",       2, 60, "topup"),
        ("A·RP(1/vol) TOP3",      "rp_top3",       3, 60, "topup"),
        ("A·ERC TOP3",            "erc_top3",      3, 60, "topup"),
        ("A·最小方差 TOP3",        "minvar_top3",   3, 60, "topup"),
        ("A·最大夏普 TOP3",        "maxsharpe_top3",3, 60, "topup"),
        # 框架B：全5标的恒满仓（全再平衡，含动量择时之外的纯配置）
        ("B·RP(1/vol) 全5",       "rp_full",       5, 60, "full"),
        ("B·ERC 全5",             "erc_full",      5, 60, "full"),
        ("B·最小方差 全5",         "minvar_full",   5, 60, "full"),
        ("B·最大夏普 全5",         "maxsharpe_full",5, 60, "full"),
        # 补充：长窗口
        ("B·RP(1/vol) 全5 W120",  "rp_full",       5, 120, "full"),
        ("B·最小方差 全5 W120",    "minvar_full",   5, 120, "full"),
        ("B·最大夏普 全5 W120",    "maxsharpe_full",5, 120, "full"),
    ]

    results = []
    for name, mode, K, W, em in plans:
        r = run_backtest(mode, K, W, em)
        r["name"] = name
        results.append(r)
        print(f"{name:26s} 年化{r['ann']:+6.2f}% 回撤-{r['mdd']:5.2f}% "
              f"夏普{r['sharpe']:5.2f} 卡玛{r['calmar']:6.3f} 交易{r['trades']:4d} 期末¥{r['final']:,.0f}")

    print("\n=== 按卡玛排序 TOP 榜 ===")
    for r in sorted(results, key=lambda x: -x["calmar"]):
        print(f"{r['name']:26s} 年化{r['ann']:+6.2f}% 回撤-{r['mdd']:5.2f}% 夏普{r['sharpe']:5.2f} 卡玛{r['calmar']:6.3f}")

    print("\n=== 按夏普排序 TOP 榜 ===")
    for r in sorted(results, key=lambda x: -x["sharpe"]):
        print(f"{r['name']:26s} 年化{r['ann']:+6.2f}% 回撤-{r['mdd']:5.2f}% 夏普{r['sharpe']:5.2f} 卡玛{r['calmar']:6.3f}")

    json.dump([{k: (round(v,3) if isinstance(v,float) else v) for k,v in r.items()}
               for r in results],
              open(os.path.join(BASE, "backtest_data", "portfolio_opt_results.json"), "w"),
              ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
