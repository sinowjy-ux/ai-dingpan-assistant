# -*- coding: utf-8 -*-
"""筹码分布（CYQ，移动成本分布）—— 与同花顺/通达信同一思路的近似实现。

每个交易日：旧筹码 × (1 − 换手率)，再把当日成交量按三角分布摊到 [最低价, 最高价]，峰值在当日均价。
换手率 = 成交量 / 流通股本（无流通股本时用 成交量 / 近 250 日平均成交量 × 2% 近似，见 turnover_proxy）。

输出（对任意一天）：
  peak      筹码峰价格（筹码最多的价位，即“最长那根筹码线”）
  profit    获利比例（收盘价以下筹码占比）
  avg_cost  平均成本
  c90, c70  90% / 70% 筹码区间集中度（%）= (上沿−下沿)/(上沿+下沿)×100
  peaks     显著峰个数（1 = 单峰）
"""
import numpy as np

BINS = 240


def turnover_proxy(vol):
    """缺流通股本时的换手率近似：假设长期平均换手 2%/日。"""
    v = np.asarray(vol, float)
    base = np.convolve(v, np.ones(250) / 250, mode="full")[: len(v)]
    cnt = np.minimum(np.arange(1, len(v) + 1), 250)
    base = base * 250 / cnt
    return np.clip(v / np.where(base > 0, base, 1) * 0.02, 0, 1)


def _count_peaks(hist):
    """平滑后计数显著峰：峰高 ≥ 最高峰 25%，且两侧回落到 ≤ 峰高 60%。"""
    k = np.array([1, 2, 3, 2, 1], float)
    h = np.convolve(hist, k / k.sum(), mode="same")
    mx = h.max()
    if mx <= 0:
        return 0
    mid = h[1:-1]
    peaks = (np.nonzero((mid >= h[:-2]) & (mid > h[2:]) & (mid >= 0.25 * mx))[0] + 1).tolist()
    # 合并相邻且中间没有明显低谷的峰
    merged = []
    for p in peaks:
        if merged:
            q = merged[-1]
            valley = h[q:p + 1].min()
            if valley > 0.6 * min(h[p], h[q]):
                if h[p] > h[q]:
                    merged[-1] = p
                continue
        merged.append(p)
    return len(merged)


def _range_conc(cum, grid, pct):
    lo_q, hi_q = (1 - pct) / 2, (1 + pct) / 2
    lo = grid[min(np.searchsorted(cum, lo_q), len(grid) - 1)]
    hi = grid[min(np.searchsorted(cum, hi_q), len(grid) - 1)]
    return (hi - lo) / (hi + lo) * 100 if hi + lo > 0 else None


def compute(rows, float_shares=None, want=None):
    """rows: [{date,open,high,low,close,volume}]（升序）。
    want: 需要输出统计的下标集合（默认只要最后一天）；返回 {idx: stats}。"""
    n = len(rows)
    if n < 30:
        return {}
    hi = np.array([r["high"] for r in rows])
    lo = np.array([r["low"] for r in rows])
    cl = np.array([r["close"] for r in rows])
    op = np.array([r["open"] for r in rows])
    vol = np.array([r["volume"] for r in rows], float)
    if float_shares:
        to = np.clip(vol / float_shares, 0, 1)
        # 流通股本口径异常（复权/股本变动）时退回近似法
        if np.median(to[-120:]) < 1e-4 or np.median(to[-120:]) > 0.3:
            to = turnover_proxy(vol)
    else:
        to = turnover_proxy(vol)
    pmin, pmax = lo.min() * 0.98, hi.max() * 1.02
    grid = np.linspace(pmin, pmax, BINS)
    step = grid[1] - grid[0]
    dist = np.zeros(BINS)
    want = set(want) if want is not None else {n - 1}
    out = {}
    for t in range(n):
        a, b = lo[t], hi[t]
        avg = (op[t] + hi[t] + lo[t] + cl[t]) / 4
        i0 = int((a - pmin) / step)
        i1 = int((b - pmin) / step) + 1
        seg = grid[i0:i1 + 1]
        if len(seg) == 0 or b - a < 1e-9:
            day = np.zeros(BINS)
            day[min(int((cl[t] - pmin) / step), BINS - 1)] = 1.0
        else:
            # 三角分布：在 avg 处最高，两端为 0（端点给极小值保证非空）
            w = np.where(seg <= avg, (seg - a) / max(avg - a, 1e-9), (b - seg) / max(b - avg, 1e-9))
            w = np.clip(w, 0.02, None)
            day = np.zeros(BINS)
            day[i0:i0 + len(seg)] = w / w.sum()
        r = to[t] if t > 0 else 1.0
        dist = dist * (1 - r) + day * r
        if t in want:
            tot = dist.sum()
            p = dist / tot
            cum = np.cumsum(p)
            pk = int(p.argmax())
            ci = min(int((cl[t] - pmin) / step), BINS - 1)
            out[t] = {
                "peak": float(grid[pk]),
                "profit": float(cum[ci] * 100),
                "avg_cost": float((p * grid).sum()),
                "c90": _range_conc(cum, grid, 0.90),
                "c70": _range_conc(cum, grid, 0.70),
                "peaks": _count_peaks(p),
                "turnover": float(to[t] * 100),
            }
    return out
