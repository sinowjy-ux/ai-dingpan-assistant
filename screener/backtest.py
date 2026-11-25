# -*- coding: utf-8 -*-
"""全市场回测：按各方法的买点、卖点、止损逐笔模拟，并与同期同持有期的“随机买入”基准对比。
用法：python3 backtest.py [起始日 2025-01-01] [结束日]
输出：cache/backtest_trades.json、cache/backtest_summary.json"""
import json
import os
import sys
import time
from multiprocessing import Pool

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import datastore  # noqa: E402
import engine  # noqa: E402

COST = 0.0015  # 单边成本（佣金+印花税+滑点）≈ 0.15%
ONLY = set(filter(None, os.environ.get("SCREENER_ONLY", "").split(",")))


def _exit_shortterm(ctx, e, entry, stop, max_hold, two_day_rule=False, ma20_stop=False):
    """短线卖法：买入后从第二天起，哪天不涨停哪天收盘卖；跌破止损收盘卖；最多持有 max_hold 天。"""
    n = len(ctx.c)
    for k in range(e, min(n, e + max_hold + 1)):
        if k == e:
            if ctx.c[k] < stop:
                return k, ctx.c[k], "止损"
            continue
        if ctx.c[k] < stop or (ma20_stop and not np.isnan(ctx.ma[20][k]) and ctx.c[k] < ctx.ma[20][k]):
            return k, ctx.c[k], "止损"
        if two_day_rule and k - e >= 2 and ctx.c[k] <= entry:
            return k, ctx.c[k], "两天不涨"
        if not ctx.lu[k]:
            return k, ctx.c[k], "不涨停卖出"
    k = min(n - 1, e + max_hold)
    return (k, ctx.c[k], "到期") if k > e else None


def simulate(ctx, sig):
    """返回 (entry_idx, entry_px, exit_idx, exit_px, reason) 或 None（未成交/数据不足）"""
    t, m, n = sig["t"], sig["method"], len(ctx.c)
    if t + 1 >= n:
        return None
    if m in ("二次涨停", "涨停换筹"):
        e = t + 1
        if ctx.o[e] > ctx.c[t] * 1.05:  # 高开超过 5% 不买
            return None
        entry = ctx.o[e]
        r = _exit_shortterm(ctx, e, entry, sig["stop"], 5 if m == "二次涨停" else 4,
                            two_day_rule=(m == "涨停换筹"), ma20_stop=(m == "涨停换筹"))
    elif m == "看涨吞没":
        e, entry = t, ctx.c[t]  # 阳线尾盘买
        r = _exit_shortterm(ctx, e, entry, sig["stop"], 5)
    elif m == "三波下跌反弹":
        e, entry = t, ctx.c[t]
        r = None
        for k in range(e + 1, min(n, e + 11)):
            if ctx.c[k] < sig["stop"]:
                r = (k, ctx.c[k], "止损")
                break
            if ctx.h[k] >= entry * 1.10:
                r = (k, max(ctx.o[k], entry * 1.10), "止盈10%")
                break
        if r is None:
            k = min(n - 1, e + 10)
            if k <= e:
                return None
            r = (k, ctx.c[k], "到期")
    elif m in ("筹码峰突破", "箱体突破", "底部三K反转"):
        # 等回踩：之后 3 天内回到信号日收盘价即成交
        if m in ("箱体突破", "底部三K反转"):
            e, entry = t, ctx.c[t]  # 突破当天买
        else:
            e = None
            for k in range(t + 1, min(n, t + 4)):
                if ctx.l[k] <= ctx.c[t]:
                    e, entry = k, min(ctx.o[k], ctx.c[t])
                    break
            if e is None:
                return None
        r = None
        had_lu = False
        for k in range(e, min(n, e + 20)):
            if ctx.c[k] < sig["stop"]:
                r = (k, ctx.c[k], "止损")
                break
            if had_lu and not ctx.lu[k]:
                r = (k, ctx.c[k], "炸板卖出")
                break
            had_lu = had_lu or ctx.lu[k]
            if k > e and ctx.h[e:k + 1].max() >= entry * 1.10 and ctx.c[k] <= entry:
                r = (k, ctx.c[k], "保本出局")  # 永远不让盈利变亏损
                break
        if r is None:
            k = min(n - 1, e + 20)
            if k <= e:
                return None
            r = (k, ctx.c[k], "到期")
    elif m == "假跌破回升":
        e, entry = t, ctx.c[t]
        neck, upper, unit = sig["neck"], sig["upper"], sig["unit"]
        level = 0  # 已突破的档位：0=未突破上颈线
        r = None
        for k in range(e + 1, min(n, e + 250)):
            if level == 0 and ctx.c[k] < sig["stop"]:
                r = (k, ctx.c[k], "止损")
                break
            new_level = int((ctx.c[k] - upper) // unit) + 1 if ctx.c[k] > upper else 0
            if new_level > level:
                level = new_level
            elif level >= 1 and ctx.c[k] < upper + (level - 1) * unit:
                r = (k, ctx.c[k], "跌破第%d档止盈" % level)
                break
        if r is None:
            k = min(n - 1, e + 249)
            if k <= e:
                return None
            r = (k, ctx.c[k], "未平仓")
    else:
        return None
    if r is None:
        return None
    k, px, reason = r
    return e, float(entry), k, float(px), reason


def run_one(args):
    code, name, fs, d0, d1 = args
    rows = datastore.read(code)
    if len(rows) < 300:
        return [], []
    idx = [i for i, r in enumerate(rows) if d0 <= r["date"] <= d1]
    if not idx:
        return [], []
    try:
        ctx = engine.Ctx(code, name, rows, fs, chip_days=range(idx[0] - 25, idx[-1] + 1))
    except Exception:  # noqa: BLE001
        return [], []
    trades, base = [], []
    last = {}
    hits = []  # (t, method) 用于统计“共振”
    for t in idx:
        for m, f in engine.DETECTORS.items():
            if ONLY and m not in ONLY:
                continue
            if t - last.get(m, -999) < engine.P["cooldown"]:
                continue
            sig = f(ctx, t)
            if not sig:
                continue
            last[m] = t
            hits.append((t, m))
            res = len({mm for tt, mm in hits if t - 10 <= tt <= t})
            sim = simulate(ctx, sig)
            if not sim:
                continue
            e, ep, x, xp, why = sim
            ret = xp / ep * (1 - COST) ** 2 - 1
            trades.append({"method": m, "code": code, "name": name, "date": sig["date"], "score": sig["score"],
                           "entry_date": ctx.dates[e], "entry": round(ep, 3), "exit_date": ctx.dates[x],
                           "exit": round(xp, 3), "ret": round(ret * 100, 2), "hold": x - e, "reason": why,
                           "resonance": res})
    # 基准：每 5 个交易日随机抽一个买点，持有 3/5/10/20/60 天的收益（代表“不用方法、随便买”）
    for t in idx[::5]:
        for h in (3, 5, 10, 20, 60):
            if t + h < len(rows):
                base.append((h, ctx.c[t + h] / ctx.c[t] * (1 - COST) ** 2 - 1))
    return trades, base


def summarize(trades, base):
    bh = {}
    for h, r in base:
        bh.setdefault(h, []).append(r)
    bstat = {h: {"mean": float(np.mean(v) * 100), "win": float(np.mean(np.array(v) > 0) * 100), "n": len(v)}
             for h, v in bh.items()}

    def nearest(h):
        return min(bstat, key=lambda x: abs(x - h)) if bstat else None
    out = {}
    for m in engine.DETECTORS:
        ts = [t for t in trades if t["method"] == m]
        if not ts:
            out[m] = {"n": 0}
            continue
        r = np.array([t["ret"] for t in ts])
        hold = float(np.mean([t["hold"] for t in ts]))
        b = bstat.get(nearest(max(1, round(hold))), {})
        wins, losses = r[r > 0], r[r <= 0]
        out[m] = {"n": len(ts), "win": round(float((r > 0).mean() * 100), 1), "mean": round(float(r.mean()), 2),
                  "median": round(float(np.median(r)), 2), "avg_win": round(float(wins.mean()), 2) if len(wins) else 0,
                  "avg_loss": round(float(losses.mean()), 2) if len(losses) else 0,
                  "payoff": round(float(wins.mean() / -losses.mean()), 2) if len(wins) and len(losses) and losses.mean() < 0 else None,
                  "p10": round(float(np.percentile(r, 10)), 2), "p90": round(float(np.percentile(r, 90)), 2),
                  "hold": round(hold, 1), "base_hold": nearest(max(1, round(hold))),
                  "base_mean": round(b.get("mean", 0), 2), "base_win": round(b.get("win", 0), 1),
                  "edge": round(float(r.mean()) - b.get("mean", 0), 2),
                  "reasons": {k: int(v) for k, v in zip(*np.unique([t["reason"] for t in ts], return_counts=True))}}
    # 共振检验：10 个交易日内同一只股票命中 ≥2 种方法 vs 只命中 1 种
    reso = {}
    for label, cond in (("单一方法", lambda t: t.get("resonance", 1) <= 1), ("2种及以上共振", lambda t: t.get("resonance", 1) >= 2)):
        r = np.array([t["ret"] for t in trades if cond(t)])
        if len(r):
            reso[label] = {"n": int(len(r)), "win": round(float((r > 0).mean() * 100), 1),
                           "mean": round(float(r.mean()), 2), "median": round(float(np.median(r)), 2)}
    return {"methods": out, "baseline": bstat, "resonance": reso}


TREND_GATED = ("筹码峰突破", "箱体突破", "假跌破回升")  # 样本外检验通过：仅在沪深300 位于 20 日线上方时有效（假跌破回升为突破上颈线买法）


def _ew_index(codes, start):
    """全市场等权指数（日收益均值，剔除 ±25% 以上的异常值），用于剔除大盘涨跌"""
    import collections
    rets = collections.defaultdict(list)
    for c in codes:
        rows = [r for r in datastore.read(c) if r["date"] >= start]
        for a, b in zip(rows[:-1], rows[1:]):
            r = b["close"] / a["close"] - 1
            if abs(r) < 0.25:
                rets[b["date"]].append(r)
    dates = sorted(d for d in rets if len(rets[d]) > 500)
    idx, lvl = {}, 1.0
    for d in dates:
        lvl *= 1 + float(np.mean(rets[d]))
        idx[d] = lvl
    return dates, idx


def market_regime():
    """沪深300ETF（510300）相对 20 日线：返回 {date: True/False}"""
    import data as D
    rows = D.fetch_history("510300", "A股", "5y")["rows"]  # 含腾讯实时补齐的最新一天
    d = [r["date"] for r in rows]
    c = np.array([r["close"] for r in rows])
    return {d[i]: bool(c[i] > c[i - 19:i + 1].mean()) for i in range(19, len(d))}


def alpha(trades, codes, start):
    import bisect
    dates, idx = _ew_index(codes, start)
    reg = market_regime()

    def ew(a, b):
        i = bisect.bisect_right(dates, a) - 1
        j = bisect.bisect_right(dates, b) - 1
        return idx[dates[j]] / idx[dates[i]] - 1 if i >= 0 and j >= 0 else None
    out = {}
    for m in engine.DETECTORS:
        rows = []
        for t in trades:
            if t["method"] != m:
                continue
            e = ew(t["entry_date"], t["exit_date"])
            if e is not None:
                rows.append((t["date"][:4], t["ret"] - e * 100, reg.get(t["date"], False)))
        if not rows:
            continue

        def stat(xs):
            xs = np.array(xs)
            return {"n": int(len(xs)), "mean": round(float(xs.mean()), 2), "beat": round(float((xs > 0).mean() * 100), 1)} if len(xs) else None
        years = sorted({y for y, _, _ in rows})
        o = {"all": stat([x for _, x, _ in rows]), "years": {y: stat([x for yy, x, _ in rows if yy == y]) for y in years}}
        if m in TREND_GATED:
            o["gated"] = {"all": stat([x for _, x, g in rows if g]),
                          "years": {y: stat([x for yy, x, g in rows if yy == y and g]) for y in years}}
        ys = [o["years"][y]["mean"] for y in years if o["years"][y] and o["years"][y]["n"] >= 100]
        gs = [o["gated"]["years"][y]["mean"] for y in years if m in TREND_GATED and o["gated"]["years"][y] and o["gated"]["years"][y]["n"] >= 100]
        if gs and all(x > 0 for x in gs):
            o["verdict"] = "有效（需大盘在20日线上）"
        elif ys and all(x > 0.3 for x in ys):
            o["verdict"] = "有效"
        elif ys and any(x > 0 for x in ys) and sum(ys) > 0:
            o["verdict"] = "不稳定"
        else:
            o["verdict"] = "无效"
        out[m] = o
    return out


def main(d0="2025-01-01", d1="2099-12-31", workers=None):
    uni = datastore.load_universe()
    jobs = [(u["code"], u["name"], u["float_shares"], d0, d1) for u in uni if os.path.exists(datastore.path(u["code"]))]
    t0 = time.time()
    trades, base = [], []
    with Pool(workers or max(2, os.cpu_count() - 2)) as pool:
        for i, (tr, bs) in enumerate(pool.imap_unordered(run_one, jobs, chunksize=8), 1):
            trades += tr
            base += bs
            if i % 500 == 0:
                print("%d/%d  信号 %d  %.0fs" % (i, len(jobs), len(trades), time.time() - t0), flush=True)
    summ = summarize(trades, base)
    summ["alpha"] = alpha(trades, [j[0] for j in jobs], d0)
    summ.update({"start": d0, "end": d1, "stocks": len(jobs), "seconds": round(time.time() - t0)})
    json.dump(trades, open(os.path.join(HERE, "cache", "backtest_trades.json"), "w", encoding="utf-8"), ensure_ascii=False)
    json.dump(summ, open(os.path.join(HERE, "cache", "backtest_summary.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for m, a in summ["alpha"].items():
        print("%-6s 超额 %+.2f%%  %s  %s" % (m, a["all"]["mean"], {y: v["mean"] for y, v in a["years"].items() if v},
                                         a["verdict"]), flush=True)
    return summ


if __name__ == "__main__":
    main(*sys.argv[1:3])
