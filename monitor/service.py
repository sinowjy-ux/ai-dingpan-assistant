# -*- coding: utf-8 -*-
"""回放与实时盯盘。两种模式共用 strategies.Stock，逐分钟推进。按 (市场, 只数) 区分数据集。"""
import os
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import strategies as engine  # noqa: E402
import feed  # noqa: E402

CN = timezone(timedelta(hours=8))   # 兼容旧代码


def tz(market):
    return ZoneInfo(engine.MARKETS[market]["tz"])


def now_local(market="cn"):
    """市场当地时间：A股北京时间，美股纽约时间（自动处理夏令时）。本机时区无关。"""
    return datetime.now(tz(market))


def now_cn():
    return now_local("cn")


# ---------------- 快照缓存 ----------------
_snaps = {}
_jobs = {}
_lock = threading.Lock()


def snapshot(market="cn", n=1500):
    p = feed.find_snapshot(market, n)
    if not p:
        return None
    cur = _snaps.get((market, n))
    if not cur or cur.path != p[0]:
        cur = feed.Snapshot(*p)
        _snaps[(market, n)] = cur
        _ctx_cache.clear()
        _replay_cache.clear()
    return cur


def job(market, n):
    return _jobs.setdefault((market, n), {"building": False, "log": [], "started": None})


def refresh_snapshot(market="cn", n=1500):
    j = job(market, n)
    with _lock:
        if j["building"]:
            return False
        j.update(building=True, log=[], started=time.time())

    def run():
        try:
            feed.build_snapshot(market, n, log=lambda s: j["log"].append(time.strftime("%H:%M:%S ") + s))
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            j["log"].append("失败：%s" % e)
        finally:
            j["building"] = False
    threading.Thread(target=run, daemon=True).start()
    return True


def datasets():
    """所有 (市场, 只数) 组合的状态：是否已下载、交易日、下载进度。"""
    out = []
    for m in ("cn", "us"):
        for n in feed.SIZES:
            s = snapshot(m, n)
            j = job(m, n)
            out.append({"market": m, "n": n, "label": feed.size_label(n),
                        "ready": s is not None, "dates": s.dates if s else [], "built": s.built if s else None,
                        "stocks": len(s.codes) - 1 if s else 0, "building": j["building"], "log": j["log"][-3:],
                        "est_min": feed.est_minutes(m, n)})
    return out


# ---------------- 回放 ----------------
_ctx_cache = {}
_replay_cache = {}


def contexts(snap, date):
    """D 日每只股票的日线背景（20 日线、20 日高点、近 5 日成交额）。只用 D 之前的数据。"""
    key = (snap.path, date)
    if key in _ctx_cache:
        return _ctx_cache[key]
    out = {}
    if date in snap.dates:
        cs = snap.meta["dsum"][date]["c"]
        cand = [c for i, c in enumerate(snap.codes) if i > 0 and cs[i]]
    else:
        cand = snap.codes[1:]
    for code in cand:
        daily = snap.daily_before(code, date)
        if len(daily) >= 6:
            out[code] = daily
    _ctx_cache[key] = out
    return out


def new_market(snap, date):
    return engine.Market(snap.index_daily_before(date), snap.market)


def replay(date, start=930, end=None, market="cn", n=1500, snap=None, cut=None, with_after=True, use_prec=True):
    """逐分钟回放 D 日。cut：只喂到这一分钟（用于无未来函数检验）。"""
    snap = snap or snapshot(market, n)
    if end is None:
        end = snap.minutes[-1]        # 默认到该市场收盘（A股 15:00，美股 16:00）
    ck = (snap.path, date, start, end, cut, with_after, use_prec)
    if ck in _replay_cache:
        return _replay_cache[ck]
    ctx = contexts(snap, date)
    mkt = new_market(snap, date)
    P, V, A = snap.matrices(date)
    mins = snap.minutes
    stocks, rows = [], []
    for code, daily in ctx.items():
        i = snap.row[code]
        pc = (snap.prev_close(code, date) if use_prec else None) or daily[-1]["close"]
        stocks.append(engine.Stock(code, snap.names.get(code, code), daily, pc, snap.market))
        rows.append((P[i].tolist(), V[i].tolist(), A[i].tolist()))
    ip = P[0].tolist()
    sigs = []
    for j, t in enumerate(mins):
        x = ip[j]
        if x != x:
            continue
        if cut is not None and t > cut:
            break
        mkt.update(t, x)
        for st, (pr, vr, ar) in zip(stocks, rows):
            p = pr[j]
            if p == p and vr[j] > 0:      # 还没有成交的分钟不算（与实时模式一致）
                for s in st.update(t, p, vr[j], ar[j], mkt):
                    if start <= t <= end:
                        sigs.append(s)
    if with_after:
        for s in sigs:
            s["after"] = after(snap.bars(s["code"], date), s)
    res = {"date": date, "market": snap.market, "n": snap.n, "start": start, "end": end, "count": len(stocks),
           "signals": sigs, "index": [[t, ip[j]] for j, t in enumerate(mins) if ip[j] == ip[j]],
           "index_prev": mkt.prev, "minutes": mins}
    _replay_cache[ck] = res
    if len(_replay_cache) > 24:
        _replay_cache.pop(next(iter(_replay_cache)))
    return res


def after(day_bars, s):
    """事后表现（只用于回放复盘，不参与信号判断）：收盘涨跌、之后最大涨幅/回撤、是否打到止损。"""
    later = [b[1] for b in day_bars if b[0] > s["t"]]
    if not later:
        return None
    p = s["price"]
    return {"close": round((later[-1] / p - 1) * 100, 2), "max_up": round((max(later) / p - 1) * 100, 2),
            "max_dn": round((min(later) / p - 1) * 100, 2), "stopped": min(later) <= s["stop"]}


def series(date, code, market="cn", n=1500):
    snap = snapshot(market, n)
    if not snap or code not in snap.row or date not in snap.dates:
        return None
    bars = snap.bars(code, date)
    if not bars:
        return None
    pc = snap.prev_close(code, date)
    if not pc:
        ctx = contexts(snap, date).get(code)
        pc = ctx[-1]["close"] if ctx else None
    return _series_from(code, snap.names.get(code, code), pc, bars)


def _series_from(code, name, pc, bars):
    T, P, V = [], [], []
    mult = None
    for t, p, v, a in bars:
        if mult is None and v > 0 and a > 0:
            mult = 100 if a / v / p > 20 else 1
        T.append(t); P.append(p); V.append(round(a / (v * mult), 3) if (mult and v > 0) else p)
    return {"code": code, "name": name, "pc": pc, "t": T, "p": P, "v": V}


# ---------------- 实时盯盘 ----------------
def trading_phase(dt=None, market="cn"):
    dt = dt or now_local(market)
    t = dt.hour * 100 + dt.minute
    if dt.weekday() >= 5:
        return "closed"
    if market == "us":
        if 930 <= t <= 1600:
            return "open"
        return "pre" if t < 930 else "closed"
    if 915 <= t < 930:
        return "pre"
    if 930 <= t <= 1130 or 1300 <= t <= 1500:
        return "open"
    if 1130 < t < 1300:
        return "lunch"
    return "pre" if t < 915 else "closed"


def clamp_t(t, market="cn"):
    if t < 930:
        return None
    if market == "us":
        return min(t, 1600)
    if 1130 < t < 1300:
        return 1130
    return min(t, 1500)


class Live:
    """实时盯盘。盘前启动：开盘后直接用上一份快照做日线背景，从第一分钟开始跟；
    盘中启动：先下载当天已走过的分时补算（时长见界面估计），然后每 20 秒批量拉一次全部报价、逐只更新。"""

    def __init__(self, market="cn", quote_fn=None, interval=20):
        self.market = market
        self.quote_fn = quote_fn or (lambda codes: feed.live_quotes(codes, market, workers=12))
        self.interval = interval
        self.lock = threading.Lock()
        self.thread = None
        self.stop_flag = threading.Event()
        self.notify = True
        self.min_notify = "B"     # 命中（A、B）都弹通知
        self.n = 1500
        self.reset()

    def reset(self):
        self.date = None
        self.stocks, self.mkt, self.signals = {}, None, []
        self.status, self.last_poll, self.polls, self.log = "idle", None, 0, []

    def _log(self, s):
        self.log = (self.log + [now_local(self.market).strftime("%H:%M:%S ") + s])[-30:]

    # ---- 初始化当天状态 ----
    def setup(self, date, snap, quotes):
        ctx = contexts(snap, date)
        self.mkt = new_market(snap, date)
        self.stocks = {}
        for code, daily in ctx.items():
            q = quotes.get(code)
            pc = q[3] if q else daily[-1]["close"]
            self.stocks[code] = engine.Stock(code, snap.names.get(code, code), daily, pc, self.market)
        self.date = date

    def backfill(self, snap, date):
        """把快照里 D 日已走过的分钟按顺序喂一遍（盘中才启动盯盘时用）。"""
        if date not in snap.dates:
            return 0
        P, V, A = snap.matrices(date)
        ip = P[0].tolist()
        rows = {c: (P[snap.row[c]].tolist(), V[snap.row[c]].tolist(), A[snap.row[c]].tolist()) for c in self.stocks}
        n = 0
        for j, t in enumerate(snap.minutes):
            if ip[j] != ip[j]:
                continue
            self.mkt.update(t, ip[j])
            for code, st in self.stocks.items():
                pr, vr, ar = rows[code]
                if pr[j] == pr[j] and vr[j] > 0:
                    for s in st.update(t, pr[j], vr[j], ar[j], self.mkt):
                        s["backfill"] = True
                        self.signals.append(s)
                        n += 1
        return n

    # ---- 处理一批报价（线程与测试共用） ----
    def process(self, quotes):
        new = []
        idx = feed.index_code(self.market)
        iq = quotes.get(idx)
        if iq and iq[1] == self.date and clamp_t(iq[0], self.market):
            self.mkt.update(clamp_t(iq[0], self.market), iq[2])
        if not self.mkt.P:
            return new
        for code, st in self.stocks.items():
            q = quotes.get(code)
            if not q or q[1] != self.date:
                continue
            t = clamp_t(q[0], self.market)
            if not t or q[5] <= 0:
                continue
            new += st.update(t, q[2], q[5], q[6], self.mkt)
        with self.lock:
            self.signals += new
        self.polls += 1
        self.last_poll = now_local(self.market).strftime("%H:%M:%S")
        return new

    def _notify(self, sigs):
        if not self.notify:
            return
        good = [s for s in sigs if s["grade"] <= self.min_notify]
        if not good:
            return
        s = max(good, key=lambda x: x["score"])
        more = "（另有 %d 条命中）" % (len(good) - 1) if len(good) > 1 else ""
        title = "★ 命中 %s %s" % (s["name"], s["strategy_name"])
        body = "%s %.2f · 纪律分 %d %s%s" % (s["time"], s["price"], s["score"], s["verdict"], more)
        osa = 'display notification "%s" with title "AI盯盘 · %s" subtitle "%s" sound name "Glass"' % (
            body.replace('"', "'"), engine.MARKETS[self.market]["name"], title.replace('"', "'"))
        try:
            subprocess.Popen(["osascript", "-e", osa], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass

    # ---- 线程 ----
    def start(self, n=None):
        if self.thread and self.thread.is_alive():
            return False
        self.reset()
        if n is not None:
            self.n = n
        self.stop_flag.clear()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        return True

    def stop(self):
        self.stop_flag.set()
        self.status = "stopped"
        self._log("已停止")

    def _prepare(self):
        """开盘时准备当天状态。返回 True 表示就绪。"""
        mk = self.market
        today = now_local(mk).strftime("%Y-%m-%d")
        t = now_local(mk).hour * 100 + now_local(mk).minute
        snap = snapshot(mk, self.n)
        fresh_open = t <= 935
        if snap and fresh_open and snap.dates[-1] < today:
            self._log("开盘：用 %s 的快照做日线背景，从第一分钟开始跟" % snap.dates[-1])
        else:
            self.status = "loading"
            self._log("下载 %s %s 当天已走过的分时用于补算（约 %d 分钟）…" % (
                engine.MARKETS[mk]["name"], feed.size_label(self.n), feed.est_minutes(mk, self.n)))
            feed.build_snapshot(mk, self.n, log=self._log)
            snap = snapshot(mk, self.n)
        q = self.quote_fn(snap.codes)
        self.setup(today, snap, q)
        n = self.backfill(snap, today)
        self._log("就绪：%d 只，开盘以来已触发 %d 条（标“补算”）。每 %d 秒刷新" % (len(self.stocks), n, self.interval))
        return True

    def _run(self):
        try:
            while not self.stop_flag.is_set():
                ph = trading_phase(market=self.market)
                if ph in ("closed", "pre") and self.date is None:
                    self.status = "waiting"
                    if not self.log or "等待开盘" not in self.log[-1]:
                        self._log("当前不在交易时段，等待开盘（当地时间 09:30）。收盘后可以用回放复盘。")
                    self.stop_flag.wait(30)
                    continue
                if self.date is None:
                    self._prepare()
                if ph == "closed":
                    self.process(self.quote_fn(list(self.stocks) + [feed.index_code(self.market)]))
                    self.status = "done"
                    self._log("已收盘，今日共 %d 条信号" % len(self.signals))
                    return
                self.status = "running" if ph == "open" else "lunch"
                if ph == "open":
                    t0 = time.time()
                    new = self.process(self.quote_fn(list(self.stocks) + [feed.index_code(self.market)]))
                    if new:
                        hits = sum(1 for s in new if s["grade"] != "C")
                        self._log("新信号 %d 条，其中命中 %d（刷新 %.1fs）" % (len(new), hits, time.time() - t0))
                        self._notify(new)
                self.stop_flag.wait(self.interval)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self.status = "error"
            self._log("出错：%s" % e)

    def state(self, since=0):
        with self.lock:
            sigs = self.signals[since:]
        loc = now_local(self.market)
        return {"market": self.market, "n": self.n, "status": self.status, "date": self.date, "count": len(self.stocks),
                "polls": self.polls, "last_poll": self.last_poll, "log": self.log[-8:], "total": len(self.signals),
                "signals": sigs, "notify": self.notify, "phase": trading_phase(market=self.market),
                "index_price": self.mkt.price if self.mkt else None,
                "index_prev": self.mkt.prev if self.mkt else None,
                "cn_time": loc.strftime("%H:%M:%S"), "local_time": loc.strftime("%H:%M:%S"),
                "local_date": loc.strftime("%Y-%m-%d")}

    def series(self, code):
        st = self.stocks.get(code)
        if not st:
            return None
        return {"code": code, "name": st.name, "pc": st.pc, "t": st.T, "p": st.P, "v": [round(v, 3) for v in st.V]}


LIVES = {"cn": Live("cn"), "us": Live("us")}
LIVE = LIVES["cn"]   # 兼容旧代码
