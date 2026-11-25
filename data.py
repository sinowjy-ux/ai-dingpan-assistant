# -*- coding: utf-8 -*-
"""行情数据层：Yahoo Finance 日K为主，东方财富K线兜底。仅用标准库。"""
import json
import os
import time
import urllib.parse
import urllib.request

UA = {"User-Agent": "Mozilla/5.0"}

# 市场配置：Yahoo 基准指数、无风险利率假设、每手股数、币种提示
MARKETS = {
    "A股":    {"bench": "000300.SS", "bench_alt": ["510300.SS"], "bench_name": "沪深300", "rf": 0.016, "lot": 100, "ccy": "CNY"},
    "港股":   {"bench": "^HSI", "bench_alt": ["2800.HK"], "bench_name": "恒生指数", "rf": 0.035, "lot": 100, "ccy": "HKD"},
    "纳斯达克": {"bench": "^IXIC", "bench_alt": ["QQQ"], "bench_name": "纳斯达克综合指数", "rf": 0.040, "lot": 1, "ccy": "USD"},
    "道琼斯":  {"bench": "^DJI", "bench_alt": ["DIA"], "bench_name": "道琼斯工业指数", "rf": 0.040, "lot": 1, "ccy": "USD"},
    "纽交所":  {"bench": "^GSPC", "bench_alt": ["SPY"], "bench_name": "标普500", "rf": 0.040, "lot": 1, "ccy": "USD"},
}


def yahoo_symbol(code, market):
    code = code.strip().upper()
    if "." in code or code.startswith("^"):
        return code  # 已是 Yahoo 原生代码，如 0700.HK / BRK-B
    if market == "A股":
        if code.startswith(("6", "5", "9")):  # 沪市股票、沪市基金/ETF、沪市B股
            return code + ".SS"
        if code[:1] in "48" or code.startswith("92"):
            return code + ".BJ"
        return code + ".SZ"
    if market == "港股":
        return code.lstrip("0").zfill(4) + ".HK"
    return code.replace(".", "-")


def _get_json(url, headers=None, timeout=15, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=headers or UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(0.5 * (i + 1))
    raise last


def _from_yahoo(sym, rng):
    url = "https://query1.finance.yahoo.com/v8/finance/chart/%s?range=%s&interval=1d" % (
        urllib.parse.quote(sym), rng)
    d = _get_json(url)["chart"]["result"][0]
    meta = d["meta"]
    q = d["indicators"]["quote"][0]
    adj = (d["indicators"].get("adjclose") or [{}])[0].get("adjclose")
    rows = []
    for i, ts in enumerate(d.get("timestamp") or []):
        o, h, l, c, v = q["open"][i], q["high"][i], q["low"][i], q["close"][i], q["volume"][i]
        if None in (o, h, l, c):
            continue
        # 用复权因子调整 OHLC，避免除权缺口污染指标
        f = (adj[i] / c) if adj and adj[i] and c else 1.0
        date = time.strftime("%Y-%m-%d", time.gmtime(ts + meta.get("gmtoffset", 0)))
        rows.append({"date": date, "open": o * f, "high": h * f, "low": l * f,
                     "close": c * f, "volume": float(v or 0)})
    # 去重同日
    dedup = {}
    for r in rows:
        dedup[r["date"]] = r
    rows = [dedup[k] for k in sorted(dedup)]
    return {"symbol": sym, "name": meta.get("longName") or meta.get("shortName") or sym,
            "currency": meta.get("currency", ""), "exchange": meta.get("fullExchangeName", ""),
            "high52": meta.get("fiftyTwoWeekHigh"), "low52": meta.get("fiftyTwoWeekLow"),
            "source": "Yahoo Finance", "rows": rows}


def _em_secids(code, market):
    raw = code.strip().upper()
    code = raw.split(".")[0]
    if raw.endswith(".SS"):
        return ["1." + code]  # 含指数，如 000300.SS → 1.000300
    if raw.endswith(".SZ"):
        return ["0." + code]
    if market == "A股":
        return [("1." if code.startswith("6") else "0.") + code]
    if market == "港股":
        return ["116." + code.lstrip("0").zfill(5)]
    return ["105." + code, "106." + code, "107." + code]


def _from_eastmoney(code, market, limit):
    hdr = {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"}
    for sid in _em_secids(code, market):
        url = ("https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=%s"
               "&fields1=f1,f2,f3&fields2=f51,f52,f53,f54,f55,f56&klt=101&fqt=1"
               "&end=20500101&lmt=%d") % (sid, limit)
        try:
            d = (_get_json(url, hdr) or {}).get("data") or {}
        except Exception:  # noqa: BLE001
            continue
        ks = d.get("klines") or []
        if not ks:
            continue
        rows = []
        for k in ks:
            p = k.split(",")
            rows.append({"date": p[0], "open": float(p[1]), "close": float(p[2]),
                         "high": float(p[3]), "low": float(p[4]), "volume": float(p[5])})
        return {"symbol": sid, "name": d.get("name", code), "currency": MARKETS.get(market, {}).get("ccy", ""),
                "exchange": "", "high52": None, "low52": None, "source": "东方财富", "rows": rows}
    raise RuntimeError("东方财富未找到 %s" % code)


_CACHE = {}
CACHE_TTL = 600  # 秒


def tencent_symbol(code, market):
    """腾讯行情代码：sh600519 / sz300750 / hk00700 / usNVDA；美股指数等不支持的返回 None"""
    raw = code.strip().upper()
    c = raw.split(".")[0]
    if raw.startswith("^"):
        return None
    if raw.endswith(".SS"):
        return "sh" + c
    if raw.endswith(".SZ"):
        return "sz" + c
    if raw.endswith(".HK") or market == "港股":
        return "hk" + c.lstrip("0").zfill(5)
    if market == "A股":
        if c[:1] in "48" or c.startswith("92"):
            return "bj" + c
        return ("sh" if c.startswith(("6", "5")) else "sz") + c
    return "us" + raw.replace("-", ".")


def tencent_quote(sym):
    """腾讯实时报价 → 当日K线 dict（成交量统一为“股”），失败返回 None"""
    try:
        req = urllib.request.Request("https://qt.gtimg.cn/q=" + sym, headers=UA)
        txt = urllib.request.urlopen(req, timeout=8).read().decode("gbk", "ignore")
        f = txt.split('"')[1].split("~")
        ts = f[30].replace("/", "-")
        date = ts[:10] if "-" in ts[:10] else "%s-%s-%s" % (ts[:4], ts[4:6], ts[6:8])
        mult = 1
        if sym[:2] in ("sh", "sz", "bj"):  # A股：主板/创业板单位“手”，科创板“股”；按成交额自动判定
            vol, amt, px = float(f[6] or 0), float(f[37] or 0), float(f[3] or 0)
            mult = 1 if (vol > 0 and px > 0 and amt > 0 and abs(amt * 1e4 / (vol * px) - 1) < 0.5) else 100
        bar = {"date": date, "open": float(f[5]), "high": float(f[33]), "low": float(f[34]),
               "close": float(f[3]), "volume": float(f[6]) * mult}
        if min(bar["open"], bar["high"], bar["low"], bar["close"]) <= 0:
            return None
        return {"bar": bar, "prev_close": float(f[4]), "name": f[1], "time": ts}
    except Exception:  # noqa: BLE001
        return None


def _topup_latest(res, code, market):
    """Yahoo 日K常滞后一个交易日：用腾讯实时报价补上/刷新最新一根K线。"""
    sym = tencent_symbol(code, market)
    q = tencent_quote(sym) if sym else None
    rows = res["rows"]
    if not q or not rows:
        res["latest_source"] = res.get("source")
        return res
    bar = q["bar"]
    if bar["date"] > rows[-1]["date"]:
        # 复权口径不一致（除权日）时按昨收比例整体缩放历史
        if q["prev_close"] > 0 and abs(rows[-1]["close"] / q["prev_close"] - 1) > 0.003:
            f = q["prev_close"] / rows[-1]["close"]
            for r in rows:
                for k in ("open", "high", "low", "close"):
                    r[k] *= f
        rows.append(bar)
    elif bar["date"] == rows[-1]["date"]:
        rows[-1] = bar
    res["latest_source"] = "腾讯实时行情 %s" % q["time"]
    res["cn_name"] = q["name"]
    return res


def fetch_history(code, market, rng="5y"):
    """返回 dict(symbol,name,currency,rows=[{date,open,high,low,close,volume}])，带 10 分钟内存缓存。
    最新一根K线来自腾讯实时行情（缓存 60 秒），保证是最新交易日/盘中数据。"""
    import copy
    key = (code.strip().upper(), market, rng)
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < CACHE_TTL:
        base = hit[1]
    else:
        base = _fetch_history(code, market, rng)
        _CACHE[key] = (time.time(), base)
    qkey = ("Q",) + key
    qhit = _CACHE.get(qkey)
    if qhit and time.time() - qhit[0] < 60:
        return qhit[1]
    res = _topup_latest(copy.deepcopy(base), code, market)
    _CACHE[qkey] = (time.time(), res)
    return res


def fetch_bench(market, rng="5y"):
    """基准指数；失败时依次尝试备用（指数 ETF，β≈1 已验证）"""
    cfg = MARKETS[market]
    errs = []
    for sym in [cfg["bench"]] + cfg.get("bench_alt", []):
        try:
            return fetch_history(sym, market, rng)
        except Exception as e:  # noqa: BLE001
            errs.append(str(e))
    raise RuntimeError("基准指数不可用：" + "；".join(errs))


_YAHOO = {}


def yahoo_ok():
    """Yahoo 在中国大陆经常连不上：启动后探测一次（6 秒超时），连不上就优先用腾讯。环境变量 KLINE_SOURCE=tencent/yahoo 可强制。"""
    force = os.environ.get("KLINE_SOURCE", "").lower()
    if force in ("tencent", "yahoo"):
        return force == "yahoo"
    if "ok" not in _YAHOO:
        try:
            req = urllib.request.Request("https://query1.finance.yahoo.com/v8/finance/chart/600519.SS?range=5d&interval=1d",
                                         headers=UA)
            urllib.request.urlopen(req, timeout=6).read()
            _YAHOO["ok"] = True
        except Exception:  # noqa: BLE001
            _YAHOO["ok"] = False
    return _YAHOO["ok"]


def _tencent_ashare_sym(code):
    if code.startswith(("sh", "sz", "bj")):
        return code
    if code.startswith(("6", "5", "9")):
        return "sh" + code
    if code.startswith(("4", "8")):
        return "bj" + code
    return "sz" + code


def _from_tencent(code, market, days=1250):
    """腾讯前复权日K（A股/ETF），每次最多约 640 根，向前分段拼接。成交量统一换算成“股”（科创板本来就是股，其余是手）。"""
    if market != "A股":
        raise RuntimeError("腾讯日K只用于 A 股")
    sym = _tencent_ashare_sym(code)
    mult = 1.0 if sym[2:].startswith(("688", "689")) else 100.0
    rows, end = {}, ""
    for _ in range(4):
        url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=%s,day,,%s,640,qfq" % (sym, end)
        try:
            node = _get_json(url, tries=2)["data"][sym]
        except Exception:  # noqa: BLE001
            node = _get_json("https://web.ifzq.gtimg.cn/appstock/app/kline/kline?param=%s,day,,%s,640" % (sym, end),
                             tries=2)["data"][sym]
        part = node.get("qfqday") or node.get("day") or []
        new = 0
        for r in part:
            if len(r) >= 6 and r[0] not in rows:
                rows[r[0]] = {"date": r[0], "open": float(r[1]), "close": float(r[2]), "high": float(r[3]),
                              "low": float(r[4]), "volume": float(r[5]) * mult}
                new += 1
        if not part or new == 0 or len(rows) >= days:
            break
        first = min(rows)
        end = time.strftime("%Y-%m-%d", time.gmtime(time.mktime(time.strptime(first, "%Y-%m-%d")) - 86400))
    out = [rows[k] for k in sorted(rows)][-days:]
    if not out:
        raise RuntimeError("腾讯无数据")
    return {"symbol": sym, "name": code, "currency": "CNY", "exchange": "", "source": "腾讯财经", "rows": out}


def _fetch_history(code, market, rng):
    sym = yahoo_symbol(code, market)
    errors = []
    if market == "A股" and not code.startswith("^") and not yahoo_ok():
        try:
            res = _from_tencent(code, market, 1250 if rng == "5y" else 500)
            if len(res["rows"]) >= 80:
                return res
        except Exception as e:  # noqa: BLE001
            errors.append("腾讯: %s" % e)
    try:
        res = _from_yahoo(sym, rng)
        if len(res["rows"]) >= 80:
            return res
        errors.append("Yahoo 数据不足")
    except Exception as e:  # noqa: BLE001
        errors.append("Yahoo: %s" % e)
    if not code.startswith("^"):
        try:
            return _from_eastmoney(code, market, 1250 if rng == "5y" else 500)
        except Exception as e:  # noqa: BLE001
            errors.append("东方财富: %s" % e)
    raise RuntimeError("无法获取 %s 行情（%s）" % (code, "；".join(errors)))
