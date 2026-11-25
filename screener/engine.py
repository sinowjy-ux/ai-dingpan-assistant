# -*- coding: utf-8 -*-
"""形态识别引擎：把形态方法翻译成可计算的规则。
每个方法 detect_X(ctx, t) 判断第 t 天（信号日）是否出现信号，返回 dict 或 None。
dict 字段：method, date, score(0–100), stop(止损价), entry_rule(买点说明), detail(满足了哪些条件)

形态描述没有给出数值的地方（例如“低位”“明显放量”），这里取了明确阈值，全部集中在 P 里，可调。"""
import numpy as np

import chips

P = {
    "conc_hi": 10.0,        # 筹码集中度：都 <10% = 高度集中（常见口径）
    "conc_rel": 15.0,       # 相对集中的宽松上限（常见口径：一个 >10 一个 <10；这里给到 15 作为“相对集中”）
    "vol_double": 2.0,      # 倍量：当日量 ≥ 前一日 × 2（常见口径：至少一倍左右）
    "low_pos": 0.75,        # 低位：突破前收盘价在近 250 日高低区间的 75% 以下（形态描述只说“低位”）
    "low_mult": 1.35,       # 且不高于近 120 日最低价的 1.35 倍（排除已大幅拉升的）
    "lu_main": 0.097,       # 涨停判定：主板涨幅 ≥ 9.7% 且收于最高价
    "lu_gem": 0.197,        # 创业板/科创板 ≥ 19.7%
    "dbl_window": 40,       # 二次涨停：两个涨停最多相隔 40 个交易日（常见口径：一天到一个月甚至更久）
    "chip_lookback": 20,    # 二次涨停/看涨吞没：之前 20 个交易日内出现过筹码峰突破即满足“筹码突破之后”
    "engulf_pct": 0.04,     # 阳包阴：阴线跌幅、阳线涨幅都 ≥ 4%（常见口径）
    "pdf_look": 250,        # 假跌破回升：前低最多回看 250 个交易日
    "pdf_max_days": 120,    # 跌破后最多 120 个交易日内翻回（常见口径：一天到半年都算）
    "pdf_base": 10,         # 前低须是前 10 个交易日以来最低的K线实体（最近一段波段的低点）
    "pdf_rebound": 0.12,    # 前低之后至少反弹 12% 才算一次“来回震荡”
    "cooldown": 20,         # 同一只股票同一方法 20 个交易日内只取第一次信号
    "pdf_drawdown": 0.28,   # 自前高回撤 ≥ 28%（常见口径：30% 左右，29% 也行）
    "ms_big": 0.03,         # 底部三K反转：中大阴线/阳线幅度 ≥3%
    "ms_small": 0.015,      # 星线实体 ≤1.5%
    "yxt_vol": 1.25,        # 涨停换筹：明显放量 = 当日量 ≥ 前 5 日均量 × 1.25（前一日常是放量涨停，不和它比）
}


# 回测变体：通过环境变量覆盖参数（多进程子进程也能读到）
import json as _json  # noqa: E402
import os as _os  # noqa: E402
P.update(_json.loads(_os.environ.get("SCREENER_P", "{}")))
P.setdefault("pdf_stop", "neck")       # 假跌破回升止损：neck=跌破颈线（原始做法）/ bottom=跌破最低点
P.setdefault("pdf_confirm", 0.0)       # 翻回颈线的幅度要求（0 = 收盘高于颈线即可）
# 2026-11 改进（work/pdf_research.py、pdf_variants.py、pdf_breakout_check.py）：
# 翻回颈线当天买入在 2025、2026 两年都没有超额（持有 10 日 −0.03% / −0.71%），2025 年的盈利几乎全来自 4 月暴跌后的反弹；
# “翻回后等突破上颈线再买”在 12 组参数下两年都为正，且只在沪深300 站上 20 日线时有效。所以买点改为突破上颈线当天。
P.setdefault("pdf_mode", "breakout")   # breakout = 突破上颈线买（默认）；reversal = 翻回颈线当天买（原始做法，留作对照）
P.setdefault("pdf_wait", 60)           # 翻回后最多等 60 个交易日突破上颈线
P.setdefault("pdf_bk_stop", 0.05)      # 突破后收盘跌回上颈线下方 5% 止损


def board(code):
    if code.startswith(("300", "301", "688", "689")):
        return "gem"
    return "main"


def limit_pct(code):
    return 0.20 if board(code) == "gem" else 0.10


class Ctx:
    """一只股票的全部序列 + 筹码统计（按需计算的天）"""

    def __init__(self, code, name, rows, float_shares=None, chip_days=None):
        self.code, self.name, self.rows = code, name, rows
        n = len(rows)
        self.o = np.array([r["open"] for r in rows])
        self.h = np.array([r["high"] for r in rows])
        self.l = np.array([r["low"] for r in rows])
        self.c = np.array([r["close"] for r in rows])
        self.v = np.array([r["volume"] for r in rows], float)
        self.dates = [r["date"] for r in rows]
        self.pct = np.r_[np.nan, self.c[1:] / self.c[:-1] - 1]
        self.ma = {k: np.convolve(self.c, np.ones(k) / k, "full")[:n] for k in (5, 10, 20, 60)}
        for k in self.ma:
            self.ma[k][: k - 1] = np.nan
        self.vma5 = np.convolve(self.v, np.ones(5) / 5, "full")[:n]
        lim = P["lu_gem"] if board(code) == "gem" else P["lu_main"]
        self.lu = (self.pct >= lim) & (self.c >= self.h * 0.999)
        # 筹码：计算需要的那些天（含前一天，用于比较“新出现”）
        if chip_days is None:
            chip_days = range(max(0, n - 30), n)
        need = set()
        for t in chip_days:
            need.update((t, t - 1))
        need = {t for t in need if 0 <= t < n}
        self.chip = chips.compute(rows, float_shares, want=need) if n >= 60 else {}

    def low_position(self, t):
        a = max(0, t - 250)
        hi, lo = self.h[a:t + 1].max(), self.l[a:t + 1].min()
        lo120 = self.l[max(0, t - 120):t + 1].min()
        return hi > lo and (self.c[t - 1] - lo) / (hi - lo) <= P["low_pos"] and self.c[t - 1] <= lo120 * P["low_mult"]

    def concentrated(self, t, strict=True):
        s = self.chip.get(t)
        if not s or s["c90"] is None:
            return False
        if strict:
            return s["c90"] < P["conc_hi"] and s["c70"] < P["conc_hi"]
        return min(s["c90"], s["c70"]) < P["conc_hi"] and max(s["c90"], s["c70"]) < P["conc_rel"]


def _sig(ctx, t, method, score, stop, entry_rule, detail):
    s = ctx.chip.get(t, {})
    return {"method": method, "code": ctx.code, "name": ctx.name, "date": ctx.dates[t], "t": t,
            "close": round(float(ctx.c[t]), 3), "pct": round(float(ctx.pct[t]) * 100, 2),
            "score": int(max(0, min(100, score))), "stop": round(float(stop), 3),
            "entry_rule": entry_rule, "detail": detail,
            "c90": round(s["c90"], 2) if s.get("c90") is not None else None,
            "c70": round(s["c70"], 2) if s.get("c70") is not None else None,
            "peak": round(s["peak"], 3) if s.get("peak") else None,
            "profit": round(s["profit"], 1) if s.get("profit") is not None else None}


# ---------- A. 筹码峰突破买入法 ----------
def detect_single_peak(ctx, t):
    if t < 60 or t - 1 not in ctx.chip:
        return None
    pre = ctx.chip[t - 1]  # 突破前的筹码形态
    if pre["peaks"] != 1 or not ctx.concentrated(t - 1, strict=False):
        return None
    vr = ctx.v[t] / ctx.v[t - 1] if ctx.v[t - 1] > 0 else 0
    if vr < P["vol_double"] or ctx.c[t] <= pre["peak"] or ctx.c[t] <= ctx.o[t]:
        return None
    if not ctx.low_position(t):
        return None
    strict = ctx.concentrated(t - 1, strict=True)
    score = 60 + (15 if strict else 0) + min(15, (vr - 2) * 5) + max(0, 10 - (pre["c90"] - 5))
    return _sig(ctx, t, "筹码峰突破", score, pre["peak"] * 0.97,
                "等回踩：次日起回踩到信号日收盘价附近买入，稳健可等回踩 10 日/20 日线",
                ["突破前单峰%s集中（90%%=%.1f%%, 70%%=%.1f%%）" % ("高度" if strict else "相对", pre["c90"], pre["c70"]),
                 "倍量 %.1f 倍" % vr, "收盘 %.2f > 筹码峰 %.2f" % (ctx.c[t], pre["peak"]), "低位"])


def recent_single_peak(ctx, t, look=None):
    look = look or P["chip_lookback"]
    for k in range(t, max(60, t - look) - 1, -1):
        if k in ctx.chip and k - 1 in ctx.chip and detect_single_peak(ctx, k):
            return ctx.dates[k]
    return None


def chip_ok_now(ctx, t):
    """“筹码单峰密集”：单峰，且 70% 集中度 <10%、90% 集中度 <20%（形态描述未给数值，取宽松口径）"""
    s = ctx.chip.get(t)
    return bool(s and s["peaks"] == 1 and s["c70"] is not None and s["c70"] < 10 and s["c90"] < 20)


# ---------- B. 二次涨停 ----------
def detect_double_lu(ctx, t):
    if t < 61 or not ctx.lu[t]:
        return None
    lim = limit_pct(ctx.code)
    for s in range(t - 2, max(0, t - P["dbl_window"]) - 1, -1):
        if not ctx.lu[s]:
            continue
        between = range(s + 1, t)
        if all(ctx.lu[k] for k in between):  # 连板不算洗盘
            return None
        if ctx.c[t] > ctx.c[s] * (1 + lim):  # 第二板收盘不得高于第一板 10%/20%
            return None
        sp = recent_single_peak(ctx, t, look=P["chip_lookback"] + (t - s))
        now = chip_ok_now(ctx, t)
        if not (sp or now):
            return None
        score = 65 + (15 if sp else 0) + (10 if now else 0) + (5 if ctx.v[t] > ctx.v[s] else 0)
        return _sig(ctx, t, "二次涨停", score, min(ctx.l[s], ctx.l[t]),
                    "次日高开不超过 5% 买入（平开、低开都可）；炸板/不涨停即卖，持股 ≤5 天",
                    ["第一板 %s，第二板 %s，中间洗盘 %d 天" % (ctx.dates[s], ctx.dates[t], t - s - 1),
                     "第二板收盘较第一板 %+.1f%%（上限 %d%%）" % ((ctx.c[t] / ctx.c[s] - 1) * 100, lim * 100),
                     ("此前筹码峰突破 %s" % sp) if sp else "当日筹码单峰密集"])
    return None


# ---------- C. 看涨吞没组合（阳包阴）----------
def detect_engulf(ctx, t):
    if t < 61:
        return None
    y, x = t, t - 1
    e = P["engulf_pct"]
    if not (ctx.pct[x] <= -e and ctx.c[x] < ctx.o[x]):
        return None
    if not (ctx.pct[y] >= e and ctx.c[y] > ctx.o[y]):
        return None
    if not (ctx.o[y] <= ctx.c[x] and ctx.c[y] >= ctx.o[x]):  # 阳线实体包住阴线实体
        return None
    if ctx.v[y] <= ctx.v[x]:
        return None
    sp = recent_single_peak(ctx, t)
    now = chip_ok_now(ctx, t)
    if not (sp or now):
        return None
    score = 65 + (15 if sp else 0) + (10 if now else 0) + (5 if ctx.lu[y] else 0)
    return _sig(ctx, t, "看涨吞没", score, min(ctx.o[y], ctx.c[x]),
                "阳线当日尾盘或次日买入；两根K线实体最低位为止损",
                ["阴线 %.1f%% + 阳线 %+.1f%%，阳线实体包住阴线" % (ctx.pct[x] * 100, ctx.pct[y] * 100),
                 "阳线量 / 阴线量 = %.1f" % (ctx.v[y] / ctx.v[x]),
                 ("此前筹码峰突破 %s" % sp) if sp else "当日筹码单峰密集"])


# ---------- D. 涨停换筹 ----------
def detect_yixiantian(ctx, t):
    if t < 61 or not ctx.lu[t] or t not in ctx.chip or t - 1 not in ctx.chip:
        return None
    vr = ctx.v[t] / ctx.vma5[t - 1] if ctx.vma5[t - 1] > 0 else 0
    if vr < P["yxt_vol"]:
        return None
    pk, pk0 = ctx.chip[t]["peak"], ctx.chip[t - 1]["peak"]
    tol = (ctx.h[t] - ctx.l[t]) * 0.05 + ctx.c[t] * 0.005
    if not (ctx.l[t] - tol <= pk <= ctx.h[t] + tol):  # 最长筹码线在涨停当天的价格区间
        return None
    if ctx.l[t] - tol <= pk0 <= ctx.h[t] + tol:  # 必须是当天“新出现”的
        return None
    score = 70 + min(20, (vr - 1.25) * 8) + (10 if ctx.h[t] == ctx.l[t] else 0)
    stop = ctx.ma[20][t] if not np.isnan(ctx.ma[20][t]) else ctx.l[t]
    return _sig(ctx, t, "涨停换筹", score, stop,
                "次日高开不超过 5% 买入（平开/低开更好，跌停也可）；哪天不涨停哪天卖，最多 3–4 天",
                ["涨停 %+.1f%%，成交量为前 5 日均量 %.1f 倍" % (ctx.pct[t] * 100, vr),
                 "新出现顶格筹码峰 %.2f（前一日峰 %.2f）" % (pk, pk0)])


# ---------- E. 假跌破回升 ----------
def podifan_setup(ctx, t):
    """在第 t 天检查“跌破前低后首次收盘翻回前低（颈线）”。返回形态要素或 None。"""
    if t < 80 or ctx.c[t] <= ctx.c[t - 1]:
        return None
    bl = np.minimum(ctx.o, ctx.c)  # K线实体最低（常见口径：不看下影线）
    bh = np.maximum(ctx.o, ctx.c)
    a = max(5, t - P["pdf_look"])
    for p in range(t - 4, a - 1, -1):
        neck = bl[p]
        if bl[p] != bl[max(0, p - P["pdf_base"]):p + 6].min():
            continue  # 前低 = 最近一段底部震荡区的最低K线实体（前 10 日、后 5 日内最低）
        hi_i = max(0, p - 250) + int(ctx.h[max(0, p - 250):p + 1].argmax())
        if ctx.c[t] <= neck * (1 + P["pdf_confirm"]) or ctx.c[t - 1] > neck:
            continue
        # 第一次收盘跌破颈线的日子 b，之后一直在颈线下方，直到 t 翻回
        below = np.nonzero(ctx.c[p + 1:t] < neck)[0]
        if len(below) == 0:
            continue
        b = p + 1 + below[0]
        if b - p < 3 or not np.all(ctx.c[b:t] <= neck):
            continue
        if bl[p + 1:b].min() < neck * 0.995:
            continue  # 前低之后到跌破之前，实体不能先跌穿前低
        if np.any((ctx.c[p + 1:b] > neck) & (np.r_[ctx.c[p:b - 1]] < neck)):
            continue  # 这条颈线之前已经“破了又翻”过一次，同一颈线只发一次信号
        if t - b > P["pdf_max_days"]:
            continue
        upper = bh[p:b].max()  # 上颈线：前低之后那次反弹的高点
        if upper < neck * (1 + P["pdf_rebound"]):
            continue  # 没有像样的反弹/震荡
        bottom = ctx.l[p:t + 1].min()
        prior_high = ctx.h[hi_i]
        dd = 1 - bottom / prior_high
        if dd < P["pdf_drawdown"]:
            continue
        return {"p": p, "b": b, "neck": float(neck), "upper": float(upper), "bottom": float(bottom),
                "unit": float(upper - bottom), "dd": float(dd), "days": int(t - b)}
    return None


def podifan_breakout(ctx, t):
    """第 t 天收盘首次突破上颈线，且之前 pdf_wait 天内出现过“假跌破回升”（翻回颈线）、期间收盘没有再跌破颈线。"""
    if t < 82 or ctx.c[t] <= ctx.c[t - 1]:
        return None
    memo = ctx.__dict__.setdefault("_pdf_memo", {})
    for t0 in range(t - 1, max(80, t - P["pdf_wait"]) - 1, -1):
        if t0 not in memo:
            memo[t0] = podifan_setup(ctx, t0)
        s = memo[t0]
        if not s:
            continue
        seg = ctx.c[t0:t]
        if seg.min() < s["neck"] or seg.max() > s["upper"]:
            continue      # 翻回后又跌破颈线（形态失败）或之前已经突破过
        if ctx.c[t] > s["upper"]:
            return dict(s, t0=t0, wait=int(t - t0))
    return None


def detect_podifan(ctx, t):
    breakout = P["pdf_mode"] == "breakout"
    s = podifan_breakout(ctx, t) if breakout else podifan_setup(ctx, t)
    if not s:
        return None
    fast = s["days"] <= 5
    chip_bonus = 10 if (t in ctx.chip and ctx.chip[t]["peaks"] == 1) else 0
    score = 60 + (15 if fast else max(0, 10 - s["days"] // 10)) + min(15, (s["dd"] - 0.3) * 50) + chip_bonus
    targets = [round(s["upper"] + k * s["unit"], 2) for k in range(1, 4)]
    if breakout:
        stop = s["upper"] * (1 - P["pdf_bk_stop"])
        rule = "突破上颈线 %.2f 当天收盘买入；收盘跌回 %.2f（上颈线下 %.0f%%）止损；按等幅目标分档止盈" % (
            s["upper"], stop, P["pdf_bk_stop"] * 100)
        first = "前低（颈线）%.2f @ %s，%s 跌破，%d 天后翻回（%s），再过 %d 天突破上颈线" % (
            s["neck"], ctx.dates[s["p"]], ctx.dates[s["b"]], s["days"], ctx.dates[s["t0"]], s["wait"])
    else:
        stop = s["neck"] if P["pdf_stop"] == "neck" else s["bottom"] * 0.99
        rule = "当天收盘翻回颈线即建仓 2 成；突破上颈线 %.2f 加仓 2 成；回踩不破上颈线再加 1 成" % s["upper"]
        first = "前低（颈线）%.2f @ %s，%s 跌破，%d 天后翻回" % (s["neck"], ctx.dates[s["p"]], ctx.dates[s["b"]], s["days"])
    sig = _sig(ctx, t, "假跌破回升", score, stop, rule,
               [first, "自前高回撤 %.0f%%，底部 %.2f" % (s["dd"] * 100, s["bottom"]),
                "上颈线 %.2f，等幅 %.2f，目标 %s" % (s["upper"], s["unit"], " / ".join("%.2f" % x for x in targets))])
    sig.update({"neck": round(s["neck"], 3), "upper": round(s["upper"], 3), "unit": round(s["unit"], 3),
                "targets": targets})
    return sig


def podifan_watch(ctx, t):
    """观察名单：近 pdf_wait 天内翻回颈线、还没突破上颈线也没再跌破颈线的股票（等突破再买）。"""
    for t0 in range(t, max(80, t - P["pdf_wait"]) - 1, -1):
        s = podifan_setup(ctx, t0)
        if not s:
            continue
        seg = ctx.c[t0:t + 1]
        if seg.min() >= s["neck"] and seg.max() <= s["upper"]:
            return dict(s, t0=t0)
        return None
    return None


# ---------- F. 箱体突破 ----------
def _touches(bh, c, lo_i, hi_i, ceiling, tol, pull):
    """平台上沿被“碰而不破”的次数：实体高点接近上沿的局部高点，相邻两次之间要有回落。"""
    idx = []
    for i in range(lo_i, hi_i):
        if bh[i] < ceiling * (1 - tol):
            continue
        if bh[i] < bh[max(lo_i, i - 2):min(hi_i, i + 3)].max():
            continue
        if idx and c[idx[-1]:i + 1].min() > bh[idx[-1]] * (1 - pull):
            if bh[i] > bh[idx[-1]]:
                idx[-1] = i  # 同一次冲高取更高那天
            continue
        idx.append(i)
    return idx


def detect_multi_bottom(ctx, t):
    if t < 70:
        return None
    bh = np.maximum(ctx.o, ctx.c)
    for W, tol, pull, rng, label in ((20, 0.03, 0.03, 0.25, "小周期20日"), (60, 0.04, 0.05, 0.35, "大周期60日")):
        a = t - W
        ceiling = bh[a:t].max()
        if not (ctx.c[t] > ceiling and ctx.c[t - 1] <= ceiling and ctx.c[t] > ctx.o[t]):
            continue
        if (ceiling - ctx.l[a:t].min()) / ceiling > rng:
            continue  # 必须是横盘震荡，不是单边下跌后的反抽
        tc = _touches(bh, ctx.c, a, t, ceiling, tol, pull)
        if len(tc) < 3:
            continue
        score = 65 + min(20, (len(tc) - 3) * 7) + (10 if W == 60 else 0) + (5 if chip_ok_now(ctx, t) else 0)
        sig = _sig(ctx, t, "箱体突破", score, ceiling * 0.97,
                   "突破当天收盘前买入；回踩不破平台上沿可继续持有/加仓",
                   ["%s：平台上沿 %.2f 被冲击 %d 次未破（%s）" % (label, ceiling, len(tc), "、".join(ctx.dates[i][5:] for i in tc)),
                    "今日收盘 %.2f 突破上沿，第 %d 次" % (ctx.c[t], len(tc) + 1)])
        sig["ceiling"] = round(float(ceiling), 3)
        return sig
    return None


# ---------- G. 三波下跌反弹（实验）----------
def _zigzag(c, a, b, th):
    """收盘价 zigzag 摆动点（回撤/反弹超过 th 才确认）：[(idx, 'H'/'L')]，最后一个为未确认的当前极值"""
    piv, trend, ext = [], 1, a
    for i in range(a + 1, b + 1):
        if trend > 0:
            if c[i] >= c[ext]:
                ext = i
            elif c[i] <= c[ext] * (1 - th):
                piv.append((ext, "H"))
                trend, ext = -1, i
        else:
            if c[i] <= c[ext]:
                ext = i
            elif c[i] >= c[ext] * (1 + th):
                piv.append((ext, "L"))
                trend, ext = 1, i
    piv.append((ext, "L" if trend < 0 else "H"))
    return piv


def detect_lingbo(ctx, t):
    if t < 160 or not (ctx.c[t] > ctx.o[t] and ctx.pct[t] >= 0.02):
        return None
    # 止跌企稳：t-1 或 t-2 是十字星/小实体，且是近 60 日最低附近
    star = None
    for k in (t - 1, t - 2):
        rngk = ctx.h[k] - ctx.l[k]
        if rngk > 0 and abs(ctx.c[k] - ctx.o[k]) <= 0.25 * rngk and ctx.l[k] <= ctx.l[t - 60:t + 1].min() * 1.02:
            star = k
            break
    if star is None or ctx.c[t] <= max(ctx.o[star], ctx.c[star]):
        return None
    piv = _zigzag(ctx.c, t - 150, star, 0.06)
    lows = [i for i, kind in piv if kind == "L"]
    highs = [i for i, kind in piv if kind == "H"]
    if len(lows) < 3 or not highs:
        return None
    l1, l2, l3 = lows[-3:]
    if not (ctx.c[l1] > ctx.c[l2] > ctx.c[l3]):
        return None  # 下跌三波：三个依次更低的低点
    h0 = [i for i in highs if i < l1]
    if not h0:
        return None
    start = h0[-1]
    plat = ctx.c[max(0, start - 40):start + 1]
    if not (ctx.c[l1] < plat.min()):
        return None  # 第一波就跌破了之前的平台底部
    bottom = ctx.l[l3:t + 1].min()
    sig = _sig(ctx, t, "三波下跌反弹", 60 + (10 if star == t - 1 else 5), bottom * 0.99,
               "企稳后的阳线当天买入；定位小波段反弹（+10% 左右止盈，跌破最低点止损）",
               ["跌破平台（%.2f）后三波下跌：%.2f → %.2f → %.2f" % (plat.min(), ctx.c[l1], ctx.c[l2], ctx.c[l3]),
                "%s 十字星企稳，今日阳线 %+.1f%%" % (ctx.dates[star][5:], ctx.pct[t] * 100)])
    return sig


# ---------- H. 底部三K反转 ----------
def detect_morning_star(ctx, t):
    if t < 62:
        return None
    a, b = t - 2, t - 1
    if not (ctx.pct[a] <= -P["ms_big"] and ctx.c[a] < ctx.o[a]):
        return None  # 中大阴线
    if not (ctx.o[b] < ctx.c[a] and abs(ctx.c[b] - ctx.o[b]) <= ctx.c[a] * P["ms_small"]):
        return None  # 跳空低开的小阴小阳/十字星
    if not (ctx.pct[t] >= P["ms_big"] and ctx.c[t] > ctx.o[t] and ctx.c[t] >= (ctx.o[a] + ctx.c[a]) / 2):
        return None  # 中大阳线，收复阴线实体一半以上
    if ctx.l[b] > ctx.l[t - 60:t + 1].min() * 1.03:
        return None  # 必须在最低位
    score = 65 + min(15, (ctx.pct[t] - P["ms_big"]) * 300) + (10 if ctx.v[t] > ctx.v[a] else 0)
    return _sig(ctx, t, "底部三K反转", score, ctx.l[b] * 0.99,
                "阳线当天尾盘或次日建仓；跌破星线最低点止损",
                ["阴线 %.1f%% → 跳空星线（%s）→ 阳线 %+.1f%%" % (ctx.pct[a] * 100, ctx.dates[b][5:], ctx.pct[t] * 100),
                 "星线最低 %.2f 为近 60 日最低" % ctx.l[b]])


DETECTORS = {"筹码峰突破": detect_single_peak, "二次涨停": detect_double_lu,
             "看涨吞没": detect_engulf, "涨停换筹": detect_yixiantian,
             "假跌破回升": detect_podifan, "箱体突破": detect_multi_bottom, "三波下跌反弹": detect_lingbo,
             "底部三K反转": detect_morning_star}
