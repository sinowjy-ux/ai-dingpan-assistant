# -*- coding: utf-8 -*-
"""盯盘数据：股票池（A股 / 美股，可选只数）、近 5 日分时（回放用）、实时快照（盯盘用）、日线背景。
数据源：腾讯 web.ifzq.gtimg.cn（A股 day/query、美股 dayus/query、日K）与 qt.gtimg.cn（实时报价）；
美股名单来自 Nasdaq 官网筛选器（含 NYSE/AMEX）。东方财富对本机限流，不用。

存储：每个 (市场, 只数) 一份快照 = 元数据 meta.json.gz（名单、名称、日线、每日昨收/收盘摘要）
      + 分时矩阵 npz（每个交易日 P/V/A 三个 [股票 × 分钟] 矩阵，缺失为 NaN）。
      全市场美股约 5000 只 × 391 分钟 × 5 天，用矩阵存放内存可控。"""
import gzip
import json
import math
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "screener"))
sys.path.insert(0, HERE)
import datastore  # noqa: E402
import strategies as S  # noqa: E402

CACHE = os.path.join(HERE, "cache")
os.makedirs(CACHE, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0"}
INDEX = S.MARKETS["cn"]["index"]          # 兼容旧代码
SIZES = [1500, 3000, 0]                   # 0 = 全市场


def index_code(market):
    return S.MARKETS[market]["index"]


def sym(code, market="cn"):
    if market == "us":
        return code if code.startswith("us") else "us" + code
    return code if code[:2] in ("sh", "sz") else ("sh" if code.startswith("6") else "sz") + code


def _get(url, timeout=15, tries=3, enc="utf-8"):
    for k in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read().decode(enc, "ignore")
        except Exception:  # noqa: BLE001
            time.sleep(0.8 * (k + 1))
    return None


def size_label(n):
    return "全市场" if not n else "%d 只" % n


def est_minutes(market, n):
    """下载耗时估计（分钟），供界面提示。实测：A股约 10 只/秒（全市场 470 秒）；美股要多拉一次日K，约 3 只/秒（全市场约 30 分钟）。"""
    full = 5030 if market == "cn" else 5040
    cnt = n or full
    return max(1, round(cnt / (10 if market == "cn" else 3) / 60))


# ---------------- 股票池 ----------------
def _num(x):
    try:
        return float(str(x).replace("$", "").replace(",", "").replace("%", ""))
    except (TypeError, ValueError):
        return 0.0


def us_list():
    """Nasdaq 官网全美股名单（NASDAQ/NYSE/AMEX），每天缓存一次。"""
    path = os.path.join(CACHE, "us_list_%s.json" % time.strftime("%Y%m%d"))
    if os.path.exists(path):
        return json.load(open(path, encoding="utf-8"))
    txt = _get("https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=10000&download=true", timeout=40)
    rows = json.loads(txt)["data"]["rows"]
    json.dump(rows, open(path, "w", encoding="utf-8"))
    return rows


def universe(market="cn", n=1500):
    """按成交额从大到小取前 n 只；n=0 为全市场。
    A股：本地日K近 20 日平均成交额（排除北交所、ST、退市）。
    美股：Nasdaq 名单的最近一日成交额（价×量），排除股价 < 1 美元、无市值、带 ^ / 的特殊证券。"""
    out = []
    if market == "cn":
        uni = datastore.load_universe()
        for u in uni:
            rows = datastore.read(u["code"])
            if len(rows) < 30:
                continue
            amt = sum(r["close"] * r["volume"] for r in rows[-20:]) / 20
            out.append((amt, u["code"], u["name"]))
        if len(out) < len(uni) * 0.6:
            # 首次使用、历史日K还没下载完：改用腾讯实时行情的成交额排序
            q = datastore.tencent_quotes([u["code"] for u in uni])
            out = [((x.get("price") or 0) * (x.get("volume") or 0), c, x.get("name") or c) for c, x in q.items()
                   if x.get("price") and x.get("volume")]
    else:
        for r in us_list():
            s, px = r["symbol"].strip(), _num(r["lastsale"])
            if not s or any(c in s for c in "^/ ") or px < 1 or _num(r["marketCap"]) <= 0:
                continue
            out.append((px * _num(r["volume"]), s, r["name"]))
    out.sort(reverse=True)
    out = out[:n] if n else out
    return [{"code": c, "name": nm, "amt": a} for a, c, nm in out]


# ---------------- 分时 ----------------
def _parse(lines):
    """A股 'hhmm 价 累计量 累计额'；美股 'hhmm 价 累计量'（成交额按 Δ量×价 累加）。"""
    out, amt, pv = [], 0.0, 0.0
    for s in lines:
        f = s.split()
        if len(f) < 3:
            continue
        t, p, v = int(f[0]), float(f[1]), float(f[2])
        if len(f) >= 4:
            a = float(f[3])
        else:
            amt += max(v - pv, 0) * p
            a = amt
        pv = v
        out.append((t, p, v, a))
    return out


def fetch_5day(code, market="cn"):
    """近 5 个交易日分时：{date: {"bars": [(t,p,cumvol,cumamt)], "prec": 昨收}}"""
    path = "day" if market == "cn" else "dayus"
    s = sym(code, market)
    txt = _get("https://web.ifzq.gtimg.cn/appstock/app/%s/query?code=%s" % (path, s))
    if not txt:
        return None
    try:
        d = json.loads(txt)["data"][s]
    except (ValueError, KeyError, TypeError):
        return None
    sess = S.minutes(market)
    lo, hi = sess[0], sess[-1]
    days = {}
    try:   # 美股日K接口需要交易所后缀（AAPL.OQ / KO.N），从分时自带的报价里取
        full = (d.get("qt") or {}).get(s, [None, None, None])[2]
    except (IndexError, TypeError, AttributeError):
        full = None
    for x in d.get("data") or []:
        bars = [b for b in _parse(x.get("data") or []) if lo <= b[0] <= hi]
        if bars:
            dd = "%s-%s-%s" % (x["date"][:4], x["date"][4:6], x["date"][6:])
            days[dd] = {"bars": bars, "prec": _num(x.get("prec")) or None}
    if days and full:
        days["_sym"] = full
    return days or None


def fetch_daily(code, market="cn", n=70):
    """日线 [date, high, close, amount]，只用于 20 日线 / 20 日高点 / 5 日均额。"""
    if market == "cn" and not code.startswith(("sh", "sz")):
        rows = datastore.read(code)[-80:]
        if len(rows) >= 30:
            return [[r["date"], r["high"], r["close"], r["close"] * r["volume"]] for r in rows]
        # 本地日K还没下载（首次使用）：直接从腾讯取，成交量“手”换算成“股”（科创板本来就是股）
    s = sym(code, market)
    url = ("https://web.ifzq.gtimg.cn/appstock/app/%s/get?param=%s,day,,,%d,qfq"
           % ("usfqkline" if market == "us" else "fqkline", s, n))
    txt = _get(url)
    if not txt:
        return []
    try:
        d = json.loads(txt)["data"][s]
    except (ValueError, KeyError, TypeError):
        return []
    rows = d.get("qfqday") or d.get("day") or []
    # 个股回退到腾讯时成交量单位是“手”（科创板是“股”）；指数保持原来的口径不换算
    mult = 100.0 if market == "cn" and not code.startswith(("sh", "sz")) and not code.startswith(("688", "689")) else 1.0
    # [date, open, close, high, low, vol, ...]
    return [[r[0], float(r[3]), float(r[2]), float(r[2]) * float(r[5]) * mult] for r in rows if len(r) >= 6]


def _names_from_qt(codes, market):
    """用腾讯报价取中文名（美股如“苹果”）；取不到就保留原名。"""
    out = {}
    syms = [sym(c, market) for c in codes]

    def one(i):
        txt = _get("https://qt.gtimg.cn/q=" + ",".join(syms[i:i + 60]), timeout=10, enc="gbk") or ""
        res = {}
        for line in txt.split(";"):
            if '="' not in line:
                continue
            key = line.split("=")[0].strip().replace("v_", "")
            f = line.split('"')[1].split("~")
            if len(f) > 2 and f[1]:
                res[key[2:] if market == "us" else key[2:]] = f[1]
        return res
    with ThreadPoolExecutor(8) as ex:
        for r in ex.map(one, range(0, len(syms), 60)):
            out.update(r)
    return out


def snap_paths(market, n, date):
    base = os.path.join(CACHE, "%s_%s_%s" % (market, n or "all", date))
    return base + ".meta.json.gz", base + ".npz"


def build_snapshot(market="cn", n=1500, workers=24, log=print):
    """下载股票池全部近 5 日分时（美股另加 70 日日K），存成矩阵快照。"""
    t0 = time.time()
    uni = universe(market, n)
    idx = index_code(market)
    codes = [idx] + [u["code"] for u in uni]
    log("%s %s：股票池 %d 只，开始下载分时%s" % (S.MARKETS[market]["name"], size_label(n), len(uni),
                                         "和日K" if market == "us" else ""))

    def task(c):
        m = fetch_5day(c, market)
        if not m:
            return None
        full = m.pop("_sym", None)
        if market == "us" and c != idx:
            dl = fetch_daily(full if full else c, market)
        else:
            dl = fetch_daily(c, market)
        return m, dl
    got, fail = {}, []
    with ThreadPoolExecutor(workers) as ex:
        for i, (c, r) in enumerate(zip(codes, ex.map(task, codes))):
            if r:
                got[c] = r
            else:
                fail.append(c)
            if (i + 1) % 250 == 0 or i + 1 == len(codes):
                log("分时下载 %d/%d（%.0fs）" % (i + 1, len(codes), time.time() - t0))
    if idx not in got:
        raise RuntimeError("%s 分时下载失败" % S.MARKETS[market]["index_name"])
    codes = [c for c in codes if c in got]
    dates = sorted(got[idx][0])
    names = {u["code"]: u["name"] for u in uni}
    if market == "us":
        names.update({k: v for k, v in _names_from_qt(codes[1:], market).items() if k in names})
    sess = S.minutes(market)
    col = {t: j for j, t in enumerate(sess)}
    N, Mn = len(codes), len(sess)
    arrays, dsum, prec = {}, {}, {}
    for d in dates:
        P = np.full((N, Mn), np.nan); V = np.full((N, Mn), np.nan); A = np.full((N, Mn), np.nan)
        pc = [None] * N
        for i, c in enumerate(codes):
            day = got[c][0].get(d)
            if not day:
                continue
            pc[i] = day["prec"]
            for t, p, v, a in day["bars"]:
                j = col.get(t)
                if j is not None and p > 0:
                    P[i, j], V[i, j], A[i, j] = p, v, a
        key = d.replace("-", "")
        arrays["P" + key], arrays["V" + key], arrays["A" + key] = P, V, A
        last = np.where(np.isnan(P), -1, np.arange(Mn)).max(axis=1)
        ok = last >= 0
        dsum[d] = {"c": [float(P[i, last[i]]) if ok[i] else None for i in range(N)],
                   "h": [float(np.nanmax(P[i])) if ok[i] else None for i in range(N)],
                   "a": [float(A[i, last[i]]) if ok[i] else None for i in range(N)]}
        prec[d] = pc
    meta = {"market": market, "n": n, "built": time.strftime("%Y-%m-%d %H:%M"), "dates": dates,
            "codes": codes, "names": names, "minutes": sess,
            "daily": {c: got[c][1] for c in codes}, "dsum": dsum, "prec": prec,
            "index_daily": [{"date": r[0], "high": r[1], "close": r[2]} for r in got[idx][1]]}
    mp, ap = snap_paths(market, n, dates[-1])
    np.savez_compressed(ap + ".tmp.npz", **arrays)
    os.replace(ap + ".tmp.npz", ap)
    with gzip.open(mp + ".tmp", "wt", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)
    os.replace(mp + ".tmp", mp)
    log("完成：%s %s（实得 %d 只），失败 %d，交易日 %s，用时 %.0fs" % (
        S.MARKETS[market]["name"], size_label(n), len(codes) - 1, len(fail), ",".join(dates), time.time() - t0))
    return Snapshot(mp, ap)


class Snapshot:
    """快照：元数据常驻内存，分时矩阵按交易日懒加载。"""

    def __init__(self, meta_path, npz_path):
        with gzip.open(meta_path, "rt", encoding="utf-8") as f:
            self.meta = json.load(f)
        self.npz_path = npz_path
        self.path = meta_path
        self._mat = {}
        m = self.meta
        self.market, self.n, self.dates, self.codes = m["market"], m["n"], m["dates"], m["codes"]
        self.names, self.built, self.minutes = m["names"], m["built"], m["minutes"]
        self.index = self.codes[0]
        self.row = {c: i for i, c in enumerate(self.codes)}

    def matrices(self, date):
        if date not in self._mat:
            z = np.load(self.npz_path)
            k = date.replace("-", "")
            self._mat = {date: (z["P" + k], z["V" + k], z["A" + k])}   # 只留一天，控制内存
        return self._mat[date]

    def bars(self, code, date):
        """[(t, p, v, a)]，跳过缺失分钟。"""
        P, V, A = self.matrices(date)
        i = self.row[code]
        return [(t, float(P[i, j]), float(V[i, j]), float(A[i, j]))
                for j, t in enumerate(self.minutes) if P[i, j] == P[i, j]]

    def prev_close(self, code, date):
        x = self.meta["prec"].get(date, [None] * len(self.codes))[self.row[code]]
        return x if x and x > 0 else None

    def daily_before(self, code, date):
        """D 之前的日线 [{date, high, close, amount}]，最多 60 根。
        下载的日K（前复权）＋分时合成的近几日（原始价）拼接；按重叠日收盘价把日K缩放到原始价口径。"""
        i = self.row[code]
        rows = self.meta["daily"].get(code) or []
        synth = {}
        for d, s in self.meta["dsum"].items():
            if d < date and s["c"][i]:
                synth[d] = {"date": d, "high": s["h"][i], "close": s["c"][i], "amount": s["a"][i] or 0}
        scale = 1.0
        for r in reversed(rows):
            if r[0] in synth and r[2] > 0:
                scale = synth[r[0]]["close"] / r[2]
                break
        out = [{"date": r[0], "high": r[1] * scale, "close": r[2] * scale, "amount": r[3]}
               for r in rows if r[0] < date and r[0] not in synth]
        out += [synth[d] for d in sorted(synth)]
        out.sort(key=lambda r: r["date"])
        return out[-60:]

    def index_daily_before(self, date):
        return [r for r in self.meta["index_daily"] if r["date"] < date]


def find_snapshot(market="cn", n=1500):
    """该 (市场, 只数) 最新的一份快照路径，没有则 None。"""
    pre = "%s_%s_" % (market, n or "all")
    fs = sorted(f for f in os.listdir(CACHE) if f.startswith(pre) and f.endswith(".meta.json.gz"))
    if not fs:
        return None
    mp = os.path.join(CACHE, fs[-1])
    ap = mp.replace(".meta.json.gz", ".npz")
    return (mp, ap) if os.path.exists(ap) else None


def list_snapshots():
    out = []
    for f in sorted(os.listdir(CACHE)):
        if f.endswith(".meta.json.gz"):
            m, n, d = f[:-len(".meta.json.gz")].split("_")
            out.append({"market": m, "n": 0 if n == "all" else int(n), "last": d})
    return out


# ---------------- 实时快照 ----------------
def live_quotes(codes, market="cn", batch=60, workers=8):
    """腾讯实时报价。返回 {code: (hhmm, date, price, prev_close, open, cumvol_shares, cumamt, name)}。
    A股：成交额字段单位万元，成交量手/股自动判定；美股：成交量为股，成交额为美元，时间为纽约时间。"""
    syms = [sym(c, market) for c in codes]
    idx = index_code(market)

    def one(i):
        txt = _get("https://qt.gtimg.cn/q=" + ",".join(syms[i:i + batch]), timeout=8, enc="gbk")
        res = {}
        for line in (txt or "").split(";"):
            if '="' not in line:
                continue
            key = line.split("=")[0].strip().replace("v_", "")
            f = line.split('"')[1].split("~")
            if len(f) < 49:
                continue
            try:
                px, pc, op = float(f[3]), float(f[4]), float(f[5] or 0)
                vol, amt = float(f[6] or 0), float(f[37] or 0)
            except ValueError:
                continue
            if px <= 0:
                continue
            ts = f[30]
            if market == "us":
                # '2026-11-24 16:00:02'
                hhmm, date = int(ts[11:13] + ts[14:16]), ts[:10]
                mult = 1
            else:
                amt *= 1e4
                mult = 1 if (vol > 0 and abs(amt / (vol * px) - 1) < 0.5) else 100
                hhmm, date = int(ts[8:12]), "%s-%s-%s" % (ts[:4], ts[4:6], ts[6:8])
            if key == idx:
                code = key
            else:
                code = key[2:]
            res[code] = (hhmm, date, px, pc, op, vol * mult, amt, f[1])
        return res
    out = {}
    with ThreadPoolExecutor(workers) as ex:
        for r in ex.map(one, range(0, len(syms), batch)):
            out.update(r)
    return out


if __name__ == "__main__":
    mk = sys.argv[1] if len(sys.argv) > 1 else "cn"
    nn = int(sys.argv[2]) if len(sys.argv) > 2 else 1500
    build_snapshot(mk, nn)
