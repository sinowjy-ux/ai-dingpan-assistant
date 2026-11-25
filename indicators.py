# -*- coding: utf-8 -*-
"""技术指标与统计函数（纯 Python，便于逐项验证）。缺值统一用 None。"""
import math


def sma(xs, n):
    out, s = [], 0.0
    for i, x in enumerate(xs):
        s += x
        if i >= n:
            s -= xs[i - n]
        out.append(s / n if i >= n - 1 else None)
    return out


def ema(xs, n):
    k = 2.0 / (n + 1)
    out, e = [], None
    for x in xs:
        e = x if e is None else x * k + e * (1 - k)
        out.append(e)
    return out


def rolling_std(xs, n):
    """总体标准差（ddof=0），布林带惯例"""
    out = []
    for i in range(len(xs)):
        if i < n - 1:
            out.append(None)
            continue
        w = xs[i - n + 1:i + 1]
        m = sum(w) / n
        out.append(math.sqrt(sum((v - m) ** 2 for v in w) / n))
    return out


def bollinger(closes, n=20, k=2.0):
    mid = sma(closes, n)
    sd = rolling_std(closes, n)
    up = [m + k * s if m is not None else None for m, s in zip(mid, sd)]
    lo = [m - k * s if m is not None else None for m, s in zip(mid, sd)]
    pb = [((c - l) / (u - l)) if u is not None and u != l else None for c, u, l in zip(closes, up, lo)]
    bw = [((u - l) / m) if m else None for u, l, m in zip(up, lo, mid)]
    return {"mid": mid, "upper": up, "lower": lo, "pctb": pb, "bandwidth": bw}


def macd(closes, fast=12, slow=26, sig=9):
    ef, es = ema(closes, fast), ema(closes, slow)
    dif = [a - b for a, b in zip(ef, es)]
    dea = ema(dif, sig)
    hist = [2 * (a - b) for a, b in zip(dif, dea)]  # 国内惯例 ×2
    return {"dif": dif, "dea": dea, "hist": hist}


def rsi_state(closes, n=14):
    """Wilder RSI。返回 (rsi 序列, 最后的 avg_gain, avg_loss)"""
    out = [None] * len(closes)
    if len(closes) <= n:
        return out, None, None
    gains = [max(closes[i] - closes[i - 1], 0) for i in range(1, n + 1)]
    losses = [max(closes[i - 1] - closes[i], 0) for i in range(1, n + 1)]
    ag, al = sum(gains) / n, sum(losses) / n
    out[n] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    for i in range(n + 1, len(closes)):
        ch = closes[i] - closes[i - 1]
        ag = (ag * (n - 1) + max(ch, 0)) / n
        al = (al * (n - 1) + max(-ch, 0)) / n
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out, ag, al


def rsi(closes, n=14):
    return rsi_state(closes, n)[0]


def price_for_rsi(last_close, ag, al, target, n=14):
    """反推：下一根收盘价为多少时，RSI 恰好等于 target（Wilder 平滑）。"""
    rs = target / (100.0 - target)
    g0, l0 = ag * (n - 1), al * (n - 1)
    # 情形1：下跌 d≥0 => RS = g0 / (l0 + d)
    d = g0 / rs - l0
    if d >= 0:
        return last_close - d
    # 情形2：上涨 u≥0 => RS = (g0 + u) / l0
    u = rs * l0 - g0
    return last_close + max(u, 0)


def atr(highs, lows, closes, n=14):
    trs = []
    for i in range(len(closes)):
        if i == 0:
            trs.append(highs[0] - lows[0])
        else:
            trs.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    out = [None] * len(trs)
    if len(trs) < n:
        return out
    a = sum(trs[:n]) / n
    out[n - 1] = a
    for i in range(n, len(trs)):
        a = (a * (n - 1) + trs[i]) / n
        out[i] = a
    return out


def obv(closes, vols):
    out, s = [0.0], 0.0
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            s += vols[i]
        elif closes[i] < closes[i - 1]:
            s -= vols[i]
        out.append(s)
    return out


def pivots(highs, lows, k=5):
    """分形高低点：左右各 k 根内的极值"""
    ph, pl = [], []
    for i in range(k, len(highs) - k):
        if highs[i] == max(highs[i - k:i + k + 1]):
            ph.append((i, highs[i]))
        if lows[i] == min(lows[i - k:i + k + 1]):
            pl.append((i, lows[i]))
    return ph, pl


# ---------- 收益/风险统计 ----------

def log_returns(closes):
    return [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes)) if closes[i - 1] > 0]


def simple_returns(closes):
    return [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]


def mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def stdev(xs):
    if len(xs) < 2:
        return 0.0
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def ann_vol(closes, days=252):
    return stdev(log_returns(closes)) * math.sqrt(days)


def max_drawdown(closes):
    peak, mdd = closes[0], 0.0
    for c in closes:
        peak = max(peak, c)
        mdd = min(mdd, c / peak - 1)
    return mdd


def sharpe(closes, rf=0.0):
    r = simple_returns(closes)
    s = stdev(r)
    return ((mean(r) - rf / 252) / s * math.sqrt(252)) if s else 0.0


def sortino(closes, rf=0.0):
    r = simple_returns(closes)
    dn = [min(x, 0) for x in r]
    dd = math.sqrt(sum(x * x for x in dn) / len(dn)) if dn else 0
    return ((mean(r) - rf / 252) / dd * math.sqrt(252)) if dd else 0.0


def percentile(xs, p):
    s = sorted(xs)
    if not s:
        return None
    k = (len(s) - 1) * p
    f, c = math.floor(k), math.ceil(k)
    return s[f] if f == c else s[f] + (s[c] - s[f]) * (k - f)


def align(a_rows, b_rows):
    """按日期对齐两条序列的收盘价"""
    bm = {r["date"]: r["close"] for r in b_rows}
    xs, ys = [], []
    for r in a_rows:
        if r["date"] in bm:
            xs.append(r["close"])
            ys.append(bm[r["date"]])
    return xs, ys


def beta_corr(a_closes, b_closes):
    ra, rb = simple_returns(a_closes), simple_returns(b_closes)
    n = min(len(ra), len(rb))
    ra, rb = ra[-n:], rb[-n:]
    if n < 20:
        return None, None
    ma, mb = mean(ra), mean(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb)) / (n - 1)
    va, vb = stdev(ra) ** 2, stdev(rb) ** 2
    beta = cov / vb if vb else None
    corr = cov / math.sqrt(va * vb) if va and vb else None
    return beta, corr


def norm_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs_put(S, K, T, r, sigma):
    if T <= 0 or sigma <= 0:
        return max(K - S, 0)
    d1 = (math.log(S / K) + (r + sigma ** 2 / 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return K * math.exp(-r * T) * norm_cdf(-d2) - S * norm_cdf(-d1)


def bs_call(S, K, T, r, sigma):
    if T <= 0 or sigma <= 0:
        return max(S - K, 0)
    d1 = (math.log(S / K) + (r + sigma ** 2 / 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * norm_cdf(d1) - K * math.exp(-r * T) * norm_cdf(d2)
