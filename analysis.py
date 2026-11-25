# -*- coding: utf-8 -*-
"""分析引擎：三种技术分析 + 区间 + 仓位 + 同业对比 + 对冲 + 扩展风险分析"""
import math
import random
from concurrent.futures import ThreadPoolExecutor

import indicators as I
from data import MARKETS, fetch_bench, fetch_history
import news
from peers import default_peers, news_profile

COST = 0.001  # 单边交易成本假设 0.1%


def _r(x, d=2):
    return None if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))) else round(x, d)


# ---------------- 回测 ----------------

def backtest(rows, entries, exits, stop_atr=None, atrs=None):
    """多头回测：第 i 根收盘出信号，第 i+1 根开盘成交。可选 ATR 止损。"""
    opens = [r["open"] for r in rows]
    lows = [r["low"] for r in rows]
    closes = [r["close"] for r in rows]
    pos, entry_px, stop, trades = False, 0.0, None, []
    equity, eq_curve = 1.0, []
    for i in range(len(rows) - 1):
        if pos and stop is not None and lows[i] <= stop:
            px = min(opens[i], stop) if opens[i] < stop else stop
            ret = px / entry_px * (1 - COST) ** 2 - 1
            trades.append(ret)
            equity *= 1 + ret
            pos = False
        if not pos and entries[i]:
            pos, entry_px = True, opens[i + 1]
            stop = entry_px - stop_atr * atrs[i] if stop_atr and atrs[i] else None
        elif pos and exits[i]:
            ret = opens[i + 1] / entry_px * (1 - COST) ** 2 - 1
            trades.append(ret)
            equity *= 1 + ret
            pos = False
        eq_curve.append(equity * (closes[i] / entry_px if pos else 1))
    if pos:  # 期末按收盘平仓计
        ret = closes[-1] / entry_px * (1 - COST) ** 2 - 1
        trades.append(ret)
        equity *= 1 + ret
    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t <= 0]
    bh = closes[-1] / closes[0] - 1
    mdd = I.max_drawdown(eq_curve) if eq_curve else 0
    avg_w = I.mean(wins) if wins else 0
    avg_l = abs(I.mean(losses)) if losses else 0
    wr = len(wins) / len(trades) if trades else 0
    payoff = avg_w / avg_l if avg_l else None
    kelly = (wr - (1 - wr) / payoff) if payoff else None
    return {"trades": len(trades), "win_rate": _r(wr * 100, 1), "total_return": _r((equity - 1) * 100, 1),
            "buy_hold": _r(bh * 100, 1), "max_dd": _r(mdd * 100, 1), "avg_win": _r(avg_w * 100, 2),
            "avg_loss": _r(-avg_l * 100, 2), "payoff": _r(payoff, 2), "kelly": _r(kelly, 3),
            "years": _r(len(rows) / 252, 1)}


# ---------------- 三种技术分析 ----------------

def analyze_kline(rows, atrs):
    closes = [r["close"] for r in rows]
    highs = [r["high"] for r in rows]
    lows = [r["low"] for r in rows]
    ma5, ma20, ma60 = I.sma(closes, 5), I.sma(closes, 20), I.sma(closes, 60)
    ma120 = I.sma(closes, 120)
    c, a = closes[-1], atrs[-1]
    ph, pl = I.pivots(highs[-250:], lows[-250:], 5)
    # 去重：相距不足 0.5×ATR 的分形点视为同一价位
    def uniq(levels):
        out = []
        for p in levels:
            if not out or abs(p - out[-1]) >= 0.5 * a:
                out.append(p)
        return out
    supports = uniq(sorted([p for _, p in pl if p < c], reverse=True))
    resists = uniq(sorted([p for _, p in ph if p > c]))
    s1 = supports[0] if supports else min(lows[-60:])
    s2 = supports[1] if len(supports) > 1 else min(lows[-250:])
    r1 = resists[0] if resists else max(highs[-60:])
    r2 = resists[1] if len(resists) > 1 else max(highs[-250:])
    if r1 <= c:  # 处于新高附近，用 ATR 投射
        r1, r2 = c + 2 * a, c + 4 * a
    r2 = max(r2, r1 + a)
    s2 = min(s2, s1 - a)
    trend_up = ma20[-1] > ma60[-1] and c > ma60[-1]
    trend_dn = ma20[-1] < ma60[-1] and c < ma60[-1]
    if trend_up:
        buy = (max(s1, ma60[-1]) if max(s1, ma60[-1]) < c else s1, min(ma20[-1], c))
        trend = "多头排列（MA20 > MA60，价在 MA60 上方）"
        sig = "持有/逢回踩加仓"
    elif trend_dn:
        buy = (s2, s2 + 0.5 * a) if s2 < c else (c - a, c - 0.5 * a)
        trend = "空头排列（MA20 < MA60，价在 MA60 下方）"
        sig = "观望，等待止跌结构"
    else:
        buy = (s1, s1 + 0.5 * a)
        trend = "均线缠绕，方向未明"
        sig = "区间操作"
    if buy[0] > buy[1]:
        buy = (buy[1], buy[0])
    sell = (r1 - 0.5 * a, r1) if trend_dn else (r1, r2)
    # 回测：MA20 上穿 MA60 入场，下穿离场，2×ATR 止损
    ent = [False] * len(rows)
    ex = [False] * len(rows)
    for i in range(1, len(rows)):
        if None in (ma20[i], ma60[i], ma20[i - 1], ma60[i - 1]):
            continue
        ent[i] = ma20[i - 1] <= ma60[i - 1] and ma20[i] > ma60[i]
        ex[i] = ma20[i - 1] >= ma60[i - 1] and ma20[i] < ma60[i]
    bt = backtest(rows, ent, ex, 2.0, atrs)
    return {
        "key": "kline", "title": "K线 + 均线系统（MA5/20/60/120）+ 支撑阻力",
        "series": {"ma5": ma5, "ma20": ma20, "ma60": ma60, "ma120": ma120},
        "reading": [
            "趋势：" + trend,
            "MA5 %.2f / MA20 %.2f / MA60 %.2f / MA120 %s" % (ma5[-1], ma20[-1], ma60[-1],
                                                           "%.2f" % ma120[-1] if ma120[-1] else "—"),
            "最近支撑 %.2f、%.2f；最近阻力 %.2f、%.2f（250日分形高低点）" % (s1, s2, r1, r2),
        ],
        "signal": sig, "bias": 1 if trend_up else (-1 if trend_dn else 0),
        "buy_zone": [_r(buy[0]), _r(buy[1])], "sell_zone": [_r(sell[0]), _r(sell[1])],
        "levels": {"s1": _r(s1), "s2": _r(s2), "r1": _r(r1), "r2": _r(r2)},
        "pros": ["直观反映多空力量与价格行为（实体、影线、跳空）",
                 "均线识别中期趋势，趋势行情中胜率与盈亏比较好",
                 "分形高低点给出客观的支撑/阻力，便于设置止损"],
        "cons": ["均线是滞后指标，震荡市频繁假金叉/死叉",
                 "形态识别有主观性，不同周期结论可能相反",
                 "对突发消息（财报、政策）缺乏预判能力"],
        "rule": "MA20 上穿 MA60 买入、下穿卖出，2×ATR 止损",
        "backtest": bt,
    }


def analyze_boll(rows, atrs):
    closes = [r["close"] for r in rows]
    b = I.bollinger(closes, 20, 2.0)
    c = closes[-1]
    up, mid, lo, pb = b["upper"][-1], b["mid"][-1], b["lower"][-1], b["pctb"][-1]
    bws = [x for x in b["bandwidth"][-250:] if x is not None]
    bw = b["bandwidth"][-1]
    bw_pct = sum(1 for x in bws if x <= bw) / len(bws) * 100 if bws else None
    buy = (lo, lo + 0.25 * (mid - lo))
    sell = (up - 0.25 * (up - mid), up)
    if pb is None:
        sig = "数据不足"
    elif pb < 0:
        sig = "跌破下轨：超卖，留意均值回归反弹（强空头中可能沿下轨下行）"
    elif pb < 0.2:
        sig = "接近下轨：低吸区"
    elif pb > 1:
        sig = "突破上轨：强势或过热，追高风险大"
    elif pb > 0.8:
        sig = "接近上轨：分批止盈区"
    else:
        sig = "通道中部：中性"
    squeeze = bw_pct is not None and bw_pct < 20
    ent = [False] * len(rows)
    ex = [False] * len(rows)
    for i in range(len(rows)):
        if b["lower"][i] is None:
            continue
        ent[i] = closes[i] < b["lower"][i]
        ex[i] = closes[i] > b["mid"][i]
    bt = backtest(rows, ent, ex, 2.0, atrs)
    return {
        "key": "boll", "title": "布林线 Bollinger Bands（20日, 2σ）",
        "series": b,
        "reading": [
            "上轨 %.2f / 中轨 %.2f / 下轨 %.2f；%%B = %.2f" % (up, mid, lo, pb if pb is not None else float("nan")),
            "带宽 %.1f%%，处于近一年 %.0f%% 分位%s" % (bw * 100, bw_pct or 0, "（收口：变盘在即）" if squeeze else ""),
        ],
        "signal": sig, "bias": 1 if (pb is not None and pb < 0.2) else (-1 if (pb is not None and pb > 0.8) else 0),
        "buy_zone": [_r(buy[0]), _r(buy[1])], "sell_zone": [_r(sell[0]), _r(sell[1])],
        "pros": ["以波动率自适应地给出相对高低位，量化“贵/便宜”",
                 "震荡市中下轨低吸、上轨止盈效果好",
                 "带宽收口可提前提示大行情（波动率均值回归）"],
        "cons": ["单边趋势中价格可沿轨道运行，逆势摸顶抄底易被套",
                 "假设收益近似正态，肥尾行情下 2σ 被频繁击穿",
                 "参数（20, 2）对不同波动率股票并非最优"],
        "rule": "收盘跌破下轨买入、回到中轨卖出，2×ATR 止损",
        "backtest": bt,
    }


def analyze_macd_rsi(rows, atrs):
    closes = [r["close"] for r in rows]
    m = I.macd(closes)
    rs, ag, al = I.rsi_state(closes, 14)
    c = closes[-1]
    dif, dea, hist = m["dif"][-1], m["dea"][-1], m["hist"][-1]
    r = rs[-1]
    p30 = I.price_for_rsi(c, ag, al, 30)
    p40 = I.price_for_rsi(c, ag, al, 40)
    p65 = I.price_for_rsi(c, ag, al, 65)
    p70 = I.price_for_rsi(c, ag, al, 70)
    a3 = 3 * atrs[-1]  # 单日反推价可能远离现价，限制在 ±3×ATR 以内
    buy = (max(min(p30, c), c - a3), max(min(p40, c), c - a3 * 0.6)) if r > 30 else (c - 0.5 * atrs[-1], c)
    sell = (min(max(p65, c), c + a3 * 0.6), min(max(p70, c), c + a3)) if r < 70 else (c, c + 0.5 * atrs[-1])
    golden = m["dif"][-2] <= m["dea"][-2] and dif > dea
    dead = m["dif"][-2] >= m["dea"][-2] and dif < dea
    # 背离：近20日价格创新低但 DIF 未创新低
    w = 20
    bull_div = c <= min(closes[-w:]) * 1.01 and dif > min(m["dif"][-w:]) + 1e-9
    bear_div = c >= max(closes[-w:]) * 0.99 and dif < max(m["dif"][-w:]) - 1e-9
    parts = []
    parts.append("MACD " + ("金叉" if golden else "死叉" if dead else ("DIF 在 DEA 上方" if dif > dea else "DIF 在 DEA 下方")))
    parts.append("零轴" + ("上方（多头区域）" if dif > 0 else "下方（空头区域）"))
    if bull_div:
        parts.append("疑似底背离")
    if bear_div:
        parts.append("疑似顶背离")
    zone = "超卖" if r < 30 else "超买" if r > 70 else "中性"
    ent = [False] * len(rows)
    ex = [False] * len(rows)
    for i in range(1, len(rows)):
        ent[i] = m["dif"][i - 1] <= m["dea"][i - 1] and m["dif"][i] > m["dea"][i] and (rs[i] or 50) < 65
        ex[i] = m["dif"][i - 1] >= m["dea"][i - 1] and m["dif"][i] < m["dea"][i]
    bt = backtest(rows, ent, ex, 2.0, atrs)
    bias = (1 if dif > dea else -1) + (1 if r < 35 else -1 if r > 65 else 0)
    return {
        "key": "macd", "title": "MACD（12, 26, 9）+ RSI（14）动量体系",
        "series": {"dif": m["dif"], "dea": m["dea"], "hist": m["hist"], "rsi": rs},
        "reading": [
            "DIF %.3f / DEA %.3f / 柱 %.3f：%s" % (dif, dea, hist, "，".join(parts)),
            "RSI(14) = %.1f（%s）" % (r, zone),
            "RSI 反推价：RSI=30 → %.2f，RSI=40 → %.2f，RSI=65 → %.2f，RSI=70 → %.2f（下一交易日收盘）" % (p30, p40, p65, p70),
        ],
        "signal": ("动量转强" if dif > dea else "动量转弱") + "，RSI " + zone,
        "bias": max(-1, min(1, bias)),
        "buy_zone": [_r(buy[0]), _r(buy[1])], "sell_zone": [_r(sell[0]), _r(sell[1])],
        "pros": ["MACD 兼顾趋势与动量，金叉/死叉信号明确、易于程序化",
                 "RSI 量化超买超卖，可反推出具体价位（本平台已实现）",
                 "背离信号对趋势衰竭有较好的预警作用"],
        "cons": ["两者均基于价格衍生，信号仍滞后于价格本身",
                 "强趋势中 RSI 可长期钝化在超买/超卖区",
                 "震荡市金叉死叉频繁，交易成本侵蚀收益"],
        "rule": "MACD 金叉且 RSI<65 买入、死叉卖出，2×ATR 止损",
        "backtest": bt,
    }


# ---------------- 同业、对冲、扩展 ----------------

def perf_metrics(rows, bench_rows, rf):
    closes = [r["close"] for r in rows]
    last = closes[-1]

    def ret(n):
        return (last / closes[-n - 1] - 1) * 100 if len(closes) > n else None
    y = closes[-252:]
    a, b = I.align(rows[-252:], bench_rows)
    beta, corr = I.beta_corr(a, b)
    rsv = I.rsi(closes)[-1]
    ma60 = I.sma(closes, 60)[-1]
    return {"price": _r(last), "r1m": _r(ret(21), 1), "r3m": _r(ret(63), 1), "r6m": _r(ret(126), 1),
            "r1y": _r(ret(252), 1), "vol": _r(I.ann_vol(y) * 100, 1), "mdd": _r(I.max_drawdown(y) * 100, 1),
            "sharpe": _r(I.sharpe(y, rf), 2), "beta": _r(beta, 2), "corr_bench": _r(corr, 2),
            "off_high": _r((last / max(r["high"] for r in rows[-252:]) - 1) * 100, 1),
            "rsi": _r(rsv, 1), "above_ma60": bool(ma60 and last > ma60)}


def monte_carlo(closes, days=60, paths=2000, seed=42):
    lr = I.log_returns(closes[-252:])
    mu, sd = I.mean(lr) * 0.5, I.stdev(lr)  # 漂移项收缩 50%，避免外推过去
    rng = random.Random(seed)
    s0 = closes[-1]
    qs = [0.05, 0.25, 0.5, 0.75, 0.95]
    sims = [[0.0] * days for _ in range(paths)]
    for p in range(paths):
        s = s0
        for d in range(days):
            s *= math.exp(mu - sd * sd / 2 + sd * rng.gauss(0, 1))
            sims[p][d] = s
    bands = {str(q): [] for q in qs}
    for d in range(days):
        col = sorted(sims[p][d] for p in range(paths))
        for q in qs:
            bands[str(q)].append(_r(col[int(q * (paths - 1))]))
    final = [sims[p][-1] for p in range(paths)]
    return {"days": days, "bands": bands, "prob_up": _r(sum(1 for f in final if f > s0) / paths * 100, 1),
            "prob_dn10": _r(sum(1 for f in final if f < s0 * 0.9) / paths * 100, 1),
            "prob_up10": _r(sum(1 for f in final if f > s0 * 1.1) / paths * 100, 1)}


def seasonality(rows):
    by_month = {}
    month_close = {}
    for r in rows:
        month_close[r["date"][:7]] = r["close"]
    keys = sorted(month_close)
    for i in range(1, len(keys)):
        m = int(keys[i][5:7])
        by_month.setdefault(m, []).append(month_close[keys[i]] / month_close[keys[i - 1]] - 1)
    return [{"month": m, "avg": _r(I.mean(v) * 100, 2), "win": _r(sum(1 for x in v if x > 0) / len(v) * 100, 0),
             "n": len(v)} for m, v in sorted(by_month.items())]


SUMMARY_MAX = 200


def build_summary(name, price, rating, score, trend_sig, lo, hi, slo, shi, stop, s, rel3m, h, anomalies,
                  n_cnews, n_pnews, industry):
    """分析总结与建议：规则生成，按优先级拼句，超出 200 字时从低优先级句子开始删除。"""
    f = lambda x: ("%.2f" % x) if x < 1000 else ("%.0f" % x)  # noqa: E731
    head = "%s现价%s，综合评级「%s」（%d分），均线信号：%s。" % (name, f(price), rating, score, trend_sig)
    if s["shares"] == 0:
        act = "按当前资金买不足一手，建议观望或提高资金。"
    elif score <= -15:
        act = "建议观望、不新开仓；持仓者可在%s–%s减仓，跌破%s止损。" % (f(slo), f(shi), f(stop))
    elif s["rr"] is not None and s["rr"] < 2:
        act = "风险回报比仅%.2f，建议等回调至%s–%s再分批买入，止损%s。" % (s["rr"], f(lo), f(hi), f(stop))
    else:
        act = "建议在%s–%s分三笔买入共%d股，止损%s，于%s–%s分批止盈（风险回报比%.1f）。" % (
            f(lo), f(hi), s["shares"], f(stop), f(slo), f(shi), s["rr"] or 0)
    parts = [(0, head), (0, act)]
    if rel3m is not None:
        parts.append((2, "近3月%s%s同业中位数%.1f个百分点。" % ("跑赢" if rel3m >= 0 else "跑输", industry, abs(rel3m))))
    if h.get("r2") is not None and h["r2"] >= 30 and (h.get("beta") or 0) > 0.8:
        parts.append((1, "β为%.2f，大盘风险敞口高，可按市值×β做指数对冲。" % h["beta"]))
    else:
        parts.append((1, "个股特质风险为主，宜用保护性认沽或配对对冲。"))
    if n_cnews or n_pnews:
        parts.append((3, "请结合下方公司与行业政策新闻复核。"))
    if anomalies:
        parts.insert(1, (0, "注意：近期价格存在异常跳变，请先核对数据。"))
    # 从低优先级（数字大）开始删，直到满足字数
    while len("".join(p for _, p in parts)) > SUMMARY_MAX and any(k > 0 for k, _ in parts):
        worst = max(k for k, _ in parts)
        idx = max(i for i, (k, _) in enumerate(parts) if k == worst)
        parts.pop(idx)
    text = "".join(p for _, p in parts)
    if len(text) > SUMMARY_MAX:
        text = text[:SUMMARY_MAX - 1] + "…"
    return {"text": text, "chars": len(text)}


def _cut(d, as_of):
    """回看历史：把序列截到 as_of（含）为止，返回新 dict（不改缓存）"""
    if not as_of:
        return d
    rows = [r for r in d["rows"] if r["date"] <= as_of]
    return {**d, "rows": rows}


def run(code, market, capital=100000.0, risk_pct=1.0, max_pos_pct=20.0, lot=None, peers_str="", as_of=None):
    if market not in MARKETS:
        raise ValueError("不支持的市场：%s" % market)
    cfg = MARKETS[market]
    lot = int(lot or cfg["lot"])
    peer_codes = [p.strip() for p in peers_str.replace("，", ",").split(",") if p.strip()] or default_peers(code, market)
    peer_codes = [p for p in peer_codes if p.upper() != code.strip().upper()][:6]

    with ThreadPoolExecutor(max_workers=8) as ex:
        f_main = ex.submit(fetch_history, code, market, "5y")
        f_bench = ex.submit(fetch_bench, market, "5y")
        f_peers = {p: ex.submit(fetch_history, p, market, "2y") for p in peer_codes}
        main = _cut(f_main.result(), as_of)
        if len(main["rows"]) < 130:
            raise ValueError("分析日期 %s 之前的历史数据不足（需要至少 130 个交易日）" % as_of)
        nm, ind, pol_q, lang = news_profile(code, market, main["name"])
        f_cnews = ex.submit(news.company_news, nm, code.strip().upper(), lang)
        f_pnews = ex.submit(news.policy_news, pol_q, lang)
        bench = _cut(f_bench.result(), as_of)
        news_err, cnews, pnews = [], [], []
        try:
            cnews = f_cnews.result()
        except Exception as e:  # noqa: BLE001  新闻失败不影响主分析
            news_err.append("公司新闻：%s" % e)
        try:
            pnews = f_pnews.result()
        except Exception as e:  # noqa: BLE001
            news_err.append("政策新闻：%s" % e)
        peer_data = {}
        peer_err = []
        for p, f in f_peers.items():
            try:
                peer_data[p] = _cut(f.result(), as_of)
            except Exception as e:  # noqa: BLE001
                peer_err.append("%s：%s" % (p, e))

    rows = main["rows"]
    closes = [r["close"] for r in rows]
    highs = [r["high"] for r in rows]
    lows = [r["low"] for r in rows]
    vols = [r["volume"] for r in rows]
    atrs = I.atr(highs, lows, closes, 14)
    c, a = closes[-1], atrs[-1]

    methods = [analyze_kline(rows, atrs), analyze_boll(rows, atrs), analyze_macd_rsi(rows, atrs)]

    # ---- 同业对比 ----
    me = perf_metrics(rows, bench["rows"], cfg["rf"])
    me.update({"code": code.upper(), "name": main["name"], "is_target": True})
    peer_rows = []
    for p, d in peer_data.items():
        if len(d["rows"]) < 130:
            continue
        m = perf_metrics(d["rows"], bench["rows"], cfg["rf"])
        x, y = I.align(rows[-252:], d["rows"])
        _, corr = I.beta_corr(x, y)
        m.update({"code": p.upper(), "name": d["name"], "corr_target": _r(corr, 2), "is_target": False})
        peer_rows.append(m)
    bm = perf_metrics(bench["rows"], bench["rows"], cfg["rf"])
    bm.update({"code": cfg["bench"], "name": cfg["bench_name"] + "（基准）", "is_bench": True})

    def median(xs):
        xs = sorted(x for x in xs if x is not None)
        return xs[len(xs) // 2] if xs else None
    peer_med = {k: median([p[k] for p in peer_rows]) for k in ("r3m", "r1y", "vol", "sharpe", "mdd")}
    rel3m = (me["r3m"] - peer_med["r3m"]) if peer_med["r3m"] is not None else None
    rel1y = (me["r1y"] - peer_med["r1y"]) if peer_med["r1y"] is not None and me["r1y"] is not None else None

    # ---- 综合区间（行业相对强弱调整）----
    lo = sum(m["buy_zone"][0] for m in methods) / 3
    hi = sum(m["buy_zone"][1] for m in methods) / 3
    slo = sum(m["sell_zone"][0] for m in methods) / 3
    shi = sum(m["sell_zone"][1] for m in methods) / 3
    tilt = 0.0
    tilt_note = "相对同业表现中性，不做调整"
    if rel3m is not None:
        if rel3m < -10:
            tilt = -0.5 * a
            tilt_note = "近3月跑输同业中位数 %.1f 个百分点：买入区下移 0.5×ATR，要求更高安全边际" % -rel3m
        elif rel3m > 10:
            tilt = 0.3 * a
            tilt_note = "近3月跑赢同业中位数 %.1f 个百分点：相对强势，买入区上移 0.3×ATR" % rel3m
    lo, hi = lo + tilt, hi + tilt
    if hi > c:  # 买入区不高于现价
        hi = c
    if lo > hi:
        lo = hi - 0.5 * a
    if slo < c:
        slo = c + 0.5 * a
    if shi <= slo:
        shi = slo + a
    entry = (lo + hi) / 2
    stop = lo - 1.0 * a
    target = (slo + shi) / 2
    rr = (target - entry) / (entry - stop) if entry > stop else None

    # 综合评分 -100 ~ 100
    score = sum(m["bias"] for m in methods) * 25
    if rel3m is not None:
        score += max(-25, min(25, rel3m))
    score = max(-100, min(100, score))
    rating = ("增持" if score >= 40 else "谨慎增持" if score >= 15 else "持有/观望" if score > -15
              else "谨慎减持" if score > -40 else "减持")

    # ---- 仓位 ----
    risk_amt = capital * risk_pct / 100
    per_share_risk = entry - stop
    by_risk = risk_amt / per_share_risk if per_share_risk > 0 else 0
    by_cap = capital * max_pos_pct / 100 / entry
    adv20 = I.mean([r["close"] * r["volume"] for r in rows[-20:]])
    by_liq = adv20 * 0.01 / entry if adv20 else by_cap  # 不超过日均成交额 1%
    raw = min(by_risk, by_cap, by_liq)
    shares = int(raw // lot) * lot
    binding = min((by_risk, "单笔风险预算"), (by_cap, "单票仓位上限"), (by_liq, "流动性（日均成交额1%）"))[1]
    kellys = [m["backtest"]["kelly"] for m in methods if m["backtest"]["kelly"] is not None]
    sizing = {
        "capital": capital, "risk_pct": risk_pct, "max_pos_pct": max_pos_pct, "lot": lot,
        "entry": _r(entry), "stop": _r(stop), "target": _r(target), "rr": _r(rr, 2),
        "shares": shares, "position_value": _r(shares * entry, 0),
        "position_pct": _r(shares * entry / capital * 100, 1) if capital else None,
        "max_loss": _r(shares * per_share_risk, 0), "binding": binding,
        "tranches": [{"price": _r(hi), "shares": int(shares * 0.3 // lot) * lot},
                     {"price": _r(entry), "shares": int(shares * 0.4 // lot) * lot},
                     {"price": _r(lo), "shares": shares - int(shares * 0.3 // lot) * lot - int(shares * 0.4 // lot) * lot}],
        "sell_plan": [{"price": _r(slo), "pct": 50}, {"price": _r(shi), "pct": 50}],
        "half_kelly": _r(max(0, I.mean(kellys)) / 2 * 100, 1) if kellys else None,
        "lot_note": "港股每手股数因股票而异，请按实际每手股数修改" if market == "港股" else "",
        "one_lot_value": _r(lot * entry, 0),
        "min_capital": _r(lot * entry / (max_pos_pct / 100), 0) if max_pos_pct else None,
    }
    if shares == 0:
        sizing["warning"] = ("按当前约束买不足 1 手（1 手≈%s %s）。受限于「%s」；按 %.0f%% 单票上限，至少需要资金约 %s。"
                             % (format(round(lot * entry), ","), cfg["ccy"], binding, max_pos_pct,
                                format(round(lot * entry / (max_pos_pct / 100)), ",")))

    # ---- 对冲 ----
    y_rows = rows[-252:]
    xa, xb = I.align(y_rows, bench["rows"])
    beta, corr = I.beta_corr(xa, xb)
    vol60 = I.ann_vol(closes[-61:])
    T, r_f = 0.25, cfg["rf"]
    pos_val = shares * c if shares else capital * max_pos_pct / 100
    n_sh = shares if shares else int(pos_val / c)
    k_put = 0.92 * c
    put = I.bs_put(c, k_put, T, r_f, vol60)
    k_call = 1.10 * c
    call = I.bs_call(c, k_call, T, r_f, vol60)
    best_pair = max(peer_rows, key=lambda p: p.get("corr_target") or -1) if peer_rows else None
    pair = None
    if best_pair and best_pair.get("corr_target") and best_pair["corr_target"] > 0.5:
        pd_rows = peer_data[next(k for k in peer_data if k.upper() == best_pair["code"])]["rows"]
        x, yv = I.align(y_rows, pd_rows)
        hb, _ = I.beta_corr(x, yv)
        pair = {"code": best_pair["code"], "name": best_pair["name"], "corr": best_pair["corr_target"],
                "hedge_ratio": _r(hb, 2), "notional": _r(pos_val * (hb or 0), 0)}
    instruments = {
        "A股": ["沪深300股指期货 IF / 中证500 IC / 中证1000 IM（空头）", "沪深300ETF（510300）融券或沪深300ETF认沽期权",
                "行业 ETF 融券做行业中性"],
        "港股": ["恒生指数期货 HSI / 小型恒指 MHI（空头）", "恒指反向 ETF 或个股认沽期权（如有）",
                 "恒生科技指数期货 HTI（科技股适用）"],
        "纳斯达克": ["纳指100 期货 NQ / 微型 MNQ（空头）", "QQQ 认沽期权或个股 Protective Put", "反向 ETF PSQ（短期）"],
        "道琼斯": ["道指期货 YM / 微型 MYM（空头）", "DIA 认沽期权或个股 Protective Put", "反向 ETF DOG（短期）"],
        "纽交所": ["标普500 期货 ES / 微型 MES（空头）", "SPY 认沽期权或个股 Protective Put", "反向 ETF SH（短期）"],
    }[market]
    hedge = {
        "beta": _r(beta, 2), "corr": _r(corr, 2), "bench": cfg["bench_name"],
        "position_value": _r(pos_val, 0), "hedge_notional": _r(pos_val * (beta or 0), 0),
        "r2": _r((corr or 0) ** 2 * 100, 0), "vol60": _r(vol60 * 100, 1),
        "put": {"strike": _r(k_put), "premium": _r(put, 3), "cost": _r(put * n_sh, 0),
                "cost_pct": _r(put / c * 100, 2), "floor_loss_pct": _r((k_put - c - put) / c * 100, 1)},
        "collar": {"put_strike": _r(k_put), "call_strike": _r(k_call), "net": _r(put - call, 3),
                   "net_cost": _r((put - call) * n_sh, 0)},
        "pair": pair, "instruments": instruments, "rf": r_f, "T_months": 3,
    }

    # ---- 扩展风险分析 ----
    y_closes = closes[-252:]
    sr = I.simple_returns(y_closes)
    var95 = -I.percentile(sr, 0.05)
    tail = [x for x in sr if x <= -var95]
    cvar95 = -I.mean(tail) if tail else None
    hh, ll = max(highs[-250:]), min(lows[-250:])
    fib = [{"level": lv, "price": _r(hh - (hh - ll) * lv)} for lv in (0, 0.236, 0.382, 0.5, 0.618, 0.786, 1)]
    ob = I.obv(closes, vols)
    obv_trend = "上升（资金流入）" if ob[-1] > ob[-21] else "下降（资金流出）"
    v5, v60 = I.mean(vols[-5:]), I.mean(vols[-60:])
    risk = {
        "var95_1d": _r(var95 * 100, 2), "cvar95_1d": _r((cvar95 or 0) * 100, 2),
        "var95_10d": _r(var95 * math.sqrt(10) * 100, 2),
        "var_amount": _r(var95 * pos_val, 0),
        "ann_vol": _r(I.ann_vol(y_closes) * 100, 1), "mdd_1y": _r(I.max_drawdown(y_closes) * 100, 1),
        "mdd_5y": _r(I.max_drawdown(closes) * 100, 1),
        "sharpe": _r(I.sharpe(y_closes, cfg["rf"]), 2), "sortino": _r(I.sortino(y_closes, cfg["rf"]), 2),
        "atr": _r(a, 3), "atr_pct": _r(a / c * 100, 2),
        "fib": fib, "fib_high": _r(hh), "fib_low": _r(ll),
        "obv_trend": obv_trend, "vol_ratio": _r(v5 / v60 if v60 else None, 2),
        "adv20": _r(adv20, 0), "pct_range_52w": _r((c - ll) / (hh - ll) * 100 if hh > ll else None, 0),
        "mc": monte_carlo(closes), "season": seasonality(rows),
    }

    # 数据质量：近 60 日单日涨跌幅超 20% 的交易日（可能是真实行情、拆股或数据源错误）
    anomalies = []
    for i in range(max(1, len(rows) - 60), len(rows)):
        ch = closes[i] / closes[i - 1] - 1
        if abs(ch) > 0.20:
            anomalies.append("%s %+.1f%%" % (rows[i]["date"], ch * 100))

    disp_name = nm
    if lang == "zh" and nm == code.strip().upper():  # 未覆盖的 A股/港股：从新闻标题提取中文简称
        disp_name = news.chinese_name(cnews, nm) or main["name"]
    summary = build_summary(disp_name,
                            c, rating, score, methods[0]["signal"], lo, hi, slo, shi, stop, sizing, rel3m,
                            hedge, anomalies, len(cnews), len(pnews), ind)

    view = 260  # 前端默认显示近一年+，全量可缩放
    return {
        "news": {"company": cnews, "policy": pnews, "industry": ind, "query_name": disp_name, "errors": news_err},
        "summary": summary,
        "meta": {"code": code.upper(), "market": market, "name": main["name"], "symbol": main["symbol"],
                 "cn_name": main.get("cn_name"), "as_of": as_of or "",
                 "latest_source": main.get("latest_source") if not as_of else main.get("source"),
                 "currency": main["currency"] or cfg["ccy"], "exchange": main["exchange"], "source": main["source"],
                 "last_date": rows[-1]["date"], "price": _r(c, 3), "bars": len(rows),
                 "chg": _r((c / closes[-2] - 1) * 100, 2), "bench": cfg["bench_name"], "view": view,
                 "peer_errors": peer_err, "anomalies": anomalies},
        "ohlc": [[r["date"], _r(r["open"], 3), _r(r["close"], 3), _r(r["low"], 3), _r(r["high"], 3), r["volume"]]
                 for r in rows],
        "methods": [{**m, "series": {k: [_r(v, 4) for v in s] for k, s in m["series"].items()}} for m in methods],
        "composite": {"buy_zone": [_r(lo), _r(hi)], "sell_zone": [_r(slo), _r(shi)], "stop": _r(stop),
                      "score": _r(score, 0), "rating": rating, "tilt_note": tilt_note,
                      "rel3m": _r(rel3m, 1), "rel1y": _r(rel1y, 1)},
        "sizing": sizing,
        "peers": {"target": me, "list": peer_rows, "bench": bm, "median": peer_med},
        "hedge": hedge, "risk": risk,
    }
