# -*- coding: utf-8 -*-
"""盯盘引擎：每只股票一个状态机，逐分钟喂入 (时间, 价格, 累计量, 累计额)，6 套战法各自判断是否触发。
只用“到当前这一分钟为止”的数据 ＋ 前一交易日及更早的日线，没有未来函数（validate_monitor.py 有逐分钟截断检验）。
同一只票同一战法一天只报一次。每条信号附：触发理由、止损、纪律分（7 项清单）。
支持 A股（cn，北京时间，有午休、有涨跌停）与美股（us，纽约时间，连续交易、无涨跌停）。"""

GRADES = [(75, "A", "可执行"), (60, "B", "观察"), (0, "C", "不建议")]

# ---------------- 市场 ----------------
MARKETS = {
    "cn": {"key": "cn", "name": "A股", "index": "sh000300", "index_name": "沪深300", "tz": "Asia/Shanghai",
           "sessions": [(930, 1130), (1300, 1500)], "time_ok": (945, 1445), "first": 935, "currency": "元",
           "order": ["orb", "high20", "vwap_pull", "surge", "limit", "gap_reverse"]},
    "us": {"key": "us", "name": "美股", "index": "us.INX", "index_name": "标普500", "tz": "America/New_York",
           "sessions": [(930, 1600)], "time_ok": (945, 1545), "first": 935, "currency": "美元",
           "order": ["orb", "high20", "vwap_pull", "surge", "momo", "gap_reverse"]},
}

STRATS = {
    "orb": "开盘区间突破",
    "high20": "放量突破20日新高",
    "vwap_pull": "均价线回踩企稳",
    "surge": "分时放量急拉",
    "limit": "冲击涨停",
    "momo": "强势再创新高",
    "gap_reverse": "低开翻红",
}

# 每个市场各战法的运行时段（当地时间）
WINDOWS = {
    "cn": {"orb": (1000, 1330), "high20": (935, 1500), "vwap_pull": (1000, 1430), "surge": (945, 1450),
           "limit": (945, 1430), "gap_reverse": (945, 1430)},
    "us": {"orb": (1000, 1400), "high20": (935, 1600), "vwap_pull": (1000, 1500), "surge": (945, 1550),
           "momo": (1030, 1500), "gap_reverse": (945, 1500)},
}

STRAT_DESC = {
    "orb": "放量（量比 ≥ 3）站上开盘 30 分钟最高价 0.5%，区间振幅 1%–5% 且高点在昨收上方，价在分时均价线上方。止损：开盘区间中点。",
    "high20": "盘中首次突破前 20 个交易日最高价，量比 ≥ 2。止损：20 日高点下方 3%。",
    "vwap_pull": "当天涨过 4% 且曾在均价线上方 1.5% 运行 ≥ 30 分钟，回踩均价线不破后重新拐头向上，量比 ≥ 2。止损：均价线下方 1.5%。",
    "surge": "5 分钟内涨 ≥ 3%，这 5 分钟成交额 ≥ 今日此前平均的 3 倍（A股另要求离涨停还有空间）。止损：急拉起点。",
    "limit": "首次逼近涨停（差 2% 以内），量比 ≥ 3。止损：分时均价线。追板风险高，纪律分通常不高。（仅 A股）",
    "momo": "当日已涨 ≥ 6%，10:30 后再创日内新高 0.3% 以上、价在均价线上方 0.5%，量比 ≥ 3。止损：分时均价线。（美股没有涨跌停，用它代替“冲击涨停”）",
    "gap_reverse": "低开 ≥ 3% 后放量（量比 ≥ 2）翻红 0.3% 以上（盘中假跌破回升）。止损：当日最低价下方 0.5%。",
}

_CARD = {
    "orb": {"char": "区", "en": "ORB", "tag": "定区间 · 等放量 · 出区间", "rule": "量比≥3 · 站上高点0.5%", "color": "#5B8DEF"},
    "high20": {"char": "新", "en": "NEW HIGH", "tag": "看左峰 · 放倍量 · 过新高", "rule": "量比≥2 · 首破20日高点", "color": "#E8607A"},
    "vwap_pull": {"char": "均", "en": "VWAP", "tag": "强势股 · 踩均线 · 再拐头", "rule": "日内涨过4% · 不破均价", "color": "#E8B931"},
    "surge": {"char": "拉", "en": "SURGE", "tag": "五分钟 · 三个点 · 三倍量", "rule": "5分钟+3% · 成交×3", "color": "#3CC48A"},
    "limit": {"char": "板", "en": "LIMIT", "tag": "逼涨停 · 看量能 · 防炸板", "rule": "距涨停≤2% · 量比≥3", "color": "#A178F0"},
    "momo": {"char": "势", "en": "MOMENTUM", "tag": "强势股 · 再新高 · 量跟上", "rule": "涨≥6% · 再创新高 · 量比≥3", "color": "#A178F0"},
    "gap_reverse": {"char": "翻", "en": "REVERSE", "tag": "低开 · 探底 · 翻红", "rule": "低开≥3% · 翻红0.3%", "color": "#F08A3C"},
}


def cards(market):
    return {k: dict(_CARD[k], window=list(WINDOWS[market][k])) for k in MARKETS[market]["order"]}


# 兼容旧接口（网页版、旧调用）：默认 A股
STRAT_CARD = cards("cn")


def minutes(market):
    out = []
    for a, b in MARKETS[market]["sessions"]:
        t = a
        while t <= b:
            out.append(t)
            t += 1 if t % 100 != 59 else 41
    return out


def elapsed(t, market="cn"):
    """开盘起的交易分钟数（A股午休不计）。A股 1–240，美股 1–390。"""
    h, m = divmod(t, 100)
    x = h * 60 + m
    if market == "us":
        return max(1, min(390, x - 570))
    e = x - 570 if t <= 1130 else 120 + x - 780
    return max(1, min(240, e))


def total_minutes(market):
    return 390 if market == "us" else 240


def limit_pct(code):
    return 0.2 if code.startswith(("688", "689", "300", "301")) else 0.1


class Market:
    """大盘指数：日线趋势（昨收 vs 20 日线）＋ 分时（现价 vs 当日分时均价）。"""

    def __init__(self, index_daily_before, market="cn"):
        self.market = market
        self.name = MARKETS[market]["index_name"]
        closes = [r["close"] for r in index_daily_before][-20:]
        self.ma20 = sum(closes) / len(closes) if closes else None
        self.prev = closes[-1] if closes else None
        self.trend_ok = bool(self.ma20 and self.prev > self.ma20)
        self.P, self.sum = [], 0.0
        self.t = None

    def update(self, t, p):
        if self.t == t and self.P:
            self.sum -= self.P.pop()
        self.P.append(p)
        self.sum += p
        self.t = t

    @property
    def price(self):
        return self.P[-1] if self.P else None

    @property
    def twap(self):
        return self.sum / len(self.P) if self.P else None

    @property
    def intraday_ok(self):
        return bool(self.P) and self.price >= self.twap


class Stock:
    def __init__(self, code, name, daily, prev_close, market="cn"):
        self.code, self.name = code, name
        self.market = market
        self.mk = MARKETS[market]
        self.win = WINDOWS[market]
        self.order = self.mk["order"]
        self.total = total_minutes(market)
        self.pc = prev_close
        self.lim = limit_pct(code) if market == "cn" else None
        self.limit_up = round(prev_close * (1 + self.lim) + 1e-9, 2) if self.lim else None
        closes = [r["close"] for r in daily]
        self.ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else None
        ma20_old = sum(closes[-25:-5]) / 20 if len(closes) >= 25 else None
        self.trend_ok = bool(self.ma20 and closes[-1] > self.ma20 and (ma20_old is None or self.ma20 >= ma20_old))
        self.h20 = max(r["high"] for r in daily[-20:]) if len(daily) >= 20 else None
        amts = [r["amount"] for r in daily[-5:] if r["amount"] > 0]
        self.avg5 = sum(amts) / len(amts) if amts else None
        self.T, self.P, self.V, self.A = [], [], [], []
        self.mult = None
        self.fired = set()
        self.above = []      # 每分钟是否在均价线上方 1.5%（可撤销，便于实时模式同一分钟重复刷新）
        self.n_above = 0
        self.lo, self.hi = [], []   # 截至每分钟的最低/最高价

    def in_win(self, key, t):
        a, b = self.win[key]
        return a <= t <= b

    # ---------- 喂数据 ----------
    def update(self, t, p, cumvol, cumamt, mkt):
        if self.T and self.T[-1] == t:   # 实时模式：同一分钟再次刷新，先撤销上一笔
            self.T.pop(); self.P.pop(); self.V.pop(); self.A.pop(); self.lo.pop(); self.hi.pop()
            self.n_above -= self.above.pop()
        if self.T and t < self.T[-1]:
            return []
        if self.mult is None and cumvol > 0 and cumamt > 0:
            self.mult = 100 if cumamt / cumvol / p > 20 else 1
        vwap = cumamt / (cumvol * self.mult) if (self.mult and cumvol > 0) else p
        self.T.append(t); self.P.append(p); self.V.append(vwap); self.A.append(cumamt)
        self.lo.append(min(p, self.lo[-1]) if self.lo else p)
        self.hi.append(max(p, self.hi[-1]) if self.hi else p)
        a = 1 if p >= vwap * 1.015 else 0
        self.above.append(a)
        self.n_above += a
        if len(self.P) < 2 or not self.pc or t < self.mk["first"]:   # 开盘 5 分钟内不出信号
            return []
        out = []
        for key in self.order:
            if key in self.fired or not self.in_win(key, t):
                continue
            hit = getattr(self, "s_" + key)(t, p, vwap)
            if hit and hit[0] < p * 0.999:      # 止损必须在现价下方，否则这条信号没法执行
                stop, reason = hit
                self.fired.add(key)
                out.append(self._signal(key, t, p, vwap, stop, reason, mkt))
        return out

    # ---------- 指标 ----------
    def lb(self, t):
        """量比 = 今日开盘以来每分钟平均成交额 ÷ 近 5 日每分钟平均成交额（剔除第一分钟的集合竞价，避免开盘几分钟虚高）。"""
        if not self.avg5 or len(self.A) < 2:
            return 0.0
        return ((self.A[-1] - self.A[0]) / elapsed(t, self.market)) / (self.avg5 / self.total)

    def chg(self, p):
        return p / self.pc - 1

    # ---------- 战法：返回 (止损价, 触发理由) 或 None。运行时段已在 update 里检查 ----------
    def s_orb(self, t, p, vwap):
        n = sum(1 for x in self.T if x < 1000)
        if n < 20 or len(self.P) <= n:
            return None
        orh, orl = max(self.P[:n]), min(self.P[:n])
        if not 0.01 <= orh / orl - 1 <= 0.05 or orh < self.pc:
            return None
        if self.P[-2] <= orh * 1.005 < p and p > vwap * 1.005 and self.lb(t) >= 3:
            return (orh + orl) / 2, "放量站上开盘 30 分钟高点 %.2f（区间 %.2f–%.2f），量比 %.1f，价在均价线 %.2f 上方" % (
                orh, orl, orh, self.lb(t), vwap)
        return None

    def s_high20(self, t, p, vwap):
        if not self.h20 or self.pc >= self.h20:
            return None
        if self.lim and self.chg(p) > self.lim - 0.01:
            return None
        if max(self.P[:-1]) <= self.h20 * 1.002 < p and self.lb(t) >= 2:
            return self.h20 * 0.97, "首次突破前 20 日最高价 %.2f，量比 %.1f，当日涨 %.1f%%" % (
                self.h20, self.lb(t), self.chg(p) * 100)
        return None

    def s_vwap_pull(self, t, p, vwap):
        if len(self.P) < 25:
            return None
        if self.hi[-1] < self.pc * 1.04 or self.n_above - self.above[-1] < 30 or self.lb(t) < 2:
            return None
        w = range(len(self.P) - 6, len(self.P) - 1)
        touched = any(self.P[j] <= self.V[j] * 1.003 for j in w)
        broke = any(self.P[j] < self.V[j] * 0.99 for j in w)
        low5 = min(self.P[j] for j in w)
        if touched and not broke and p > vwap * 1.002 and p >= low5 * 1.006:
            return vwap * 0.985, "日内最高涨 %.1f%% 后回踩均价线 %.2f 不破，从 %.2f 拐头向上" % (
                (self.hi[-1] / self.pc - 1) * 100, vwap, low5)
        return None

    def s_surge(self, t, p, vwap):
        i = len(self.P) - 1
        if i < 6:
            return None
        base = self.P[i - 5]
        if p / base - 1 < 0.03 or (self.lim and self.chg(p) > self.lim - 0.02):
            return None
        amt5 = self.A[i] - self.A[i - 5]
        avg_before = self.A[i - 5] / (i - 5) * 5
        floor = (self.avg5 or 0) / self.total * 5 * 3
        if amt5 >= 3 * avg_before and amt5 >= floor:
            return base, "5 分钟从 %.2f 拉到 %.2f（+%.1f%%），这 5 分钟成交 %.0f 万%s，是此前平均的 %.1f 倍" % (
                base, p, (p / base - 1) * 100, amt5 / 1e4, "美元" if self.market == "us" else "",
                amt5 / max(avg_before, 1))
        return None

    def s_limit(self, t, p, vwap):
        th = self.limit_up * 0.98
        if max(self.P[:-1]) < th <= p and self.lb(t) >= 3:
            return vwap, "逼近涨停 %.2f（差 %.1f%%），量比 %.1f" % (
                self.limit_up, (self.limit_up / p - 1) * 100, self.lb(t))
        return None

    def s_momo(self, t, p, vwap):
        if self.chg(p) < 0.06 or len(self.P) < 61:
            return None
        prev_hi = self.hi[-2]
        if p > prev_hi * 1.003 and self.P[-2] <= prev_hi and p > vwap * 1.005 and self.lb(t) >= 3:
            return vwap, "当日已涨 %.1f%%，再创日内新高 %.2f（前高 %.2f），量比 %.1f" % (
                self.chg(p) * 100, p, prev_hi, self.lb(t))
        return None

    def s_gap_reverse(self, t, p, vwap):
        if self.P[0] > self.pc * 0.97:
            return None
        if self.P[-2] < self.pc * 1.003 <= p and self.lb(t) >= 2:
            return self.lo[-1] * 0.995, "低开 %.1f%% 后翻红，当日最低 %.2f，量比 %.1f" % (
                (self.P[0] / self.pc - 1) * 100, self.lo[-1], self.lb(t))
        return None

    # ---------- 纪律分 ----------
    def _signal(self, key, t, p, vwap, stop, reason, mkt):
        lb = self.lb(t)
        risk = (p - stop) / p
        chase = (0.12 if self.lim > 0.1 else 0.07) if self.lim else 0.10
        a, b = self.mk["time_ok"]
        iname = self.mk["index_name"]
        checks = [
            ("大盘环境", 20, mkt.trend_ok,
             "%s 昨收 %.0f %s 20 日线 %.0f" % (iname, mkt.prev or 0, "在" if mkt.trend_ok else "低于", mkt.ma20 or 0)
             + ("" if mkt.trend_ok else "（回测：大盘在 20 日线下时突破类方法普遍失效）")),
            ("大盘分时", 10, mkt.intraday_ok,
             "%s 现价 %.0f %s 当日分时均价 %.0f" % (iname, mkt.price or 0, "≥" if mkt.intraday_ok else "<", mkt.twap or 0)),
            ("个股日线", 20, self.trend_ok,
             "昨收%s 20 日线 %.2f%s" % ("在" if self.trend_ok else "不在", self.ma20 or 0,
                                     "且 20 日线向上" if self.trend_ok else "上方或 20 日线走平/向下")),
            ("量能确认", 15, lb >= 2, "量比 %.1f（要求 ≥ 2）" % lb),
            ("止损距离", 15, 0 < risk <= 0.04, "止损 %.2f，距现价 %.1f%%（要求 ≤ 4%%）" % (stop, risk * 100)),
            ("不追高", 10, self.chg(p) <= chase, "当日涨 %.1f%%（要求 ≤ %d%%）" % (self.chg(p) * 100, chase * 100)),
            ("时间纪律", 10, a <= t <= b, "%02d:%02d（避开开盘 15 分钟和尾盘 15 分钟）" % divmod(t, 100)),
        ]
        score = sum(pts for _, pts, ok, _ in checks if ok)
        grade, verdict = next((g, v) for th, g, v in GRADES if score >= th)
        return {"time": "%02d:%02d" % divmod(t, 100), "t": t, "code": self.code, "name": self.name,
                "market": self.market,
                "strategy": key, "strategy_name": STRATS[key], "price": round(p, 2),
                "chg": round(self.chg(p) * 100, 2), "lb": round(lb, 2), "vwap": round(vwap, 3),
                "stop": round(stop, 2), "risk": round(risk * 100, 2), "reason": reason,
                "score": score, "grade": grade, "verdict": verdict,
                "checks": [{"name": n, "pts": pts, "ok": bool(ok), "note": note} for n, pts, ok, note in checks]}
