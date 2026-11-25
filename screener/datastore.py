# -*- coding: utf-8 -*-
"""A股全市场日K本地仓库。
首次：python3 datastore.py full    （约 15 分钟，5 年日K，复权；筹码计算需要长历史）
日常：python3 datastore.py update  （只拉近 1 个月并合并）
数据：Yahoo Finance；股票池与名称/流通市值来自 ~/stock_screener/universe.json（排除北交所、ST、退市）。"""
import csv
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import data  # noqa: E402

CACHE = os.path.join(HERE, "cache", "klines")
UNIVERSE_SRC = os.path.expanduser("~/stock_screener/universe.json")
UNIVERSE = os.path.join(HERE, "cache", "universe.json")
FIELDS = ["date", "open", "high", "low", "close", "volume"]


def load_universe():
    src = UNIVERSE if os.path.exists(UNIVERSE) else UNIVERSE_SRC
    uni = json.load(open(src, encoding="utf-8"))
    out = []
    for u in uni:
        c, name = u["code"], u.get("name", "")
        if c[:1] not in "036" or c.startswith("92"):
            continue  # 北交所等
        if "ST" in name.upper().replace(" ", "") or "退" in name:
            continue
        def num(x):
            try:
                return float(x)
            except (TypeError, ValueError):
                return 0.0
        price = num(u.get("price"))
        out.append({"code": c, "name": name,
                    "float_shares": num(u.get("float_mv")) / price if price else None,
                    "total_mv": u.get("total_mv")})
    return out


def path(code):
    return os.path.join(CACHE, code + ".csv")


def read(code):
    p = path(code)
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        return [{"date": r["date"], **{k: float(r[k]) for k in FIELDS[1:]}} for r in csv.DictReader(f)]


def write(code, rows):
    tmp = path(code) + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: (round(r[k], 4) if k != "date" else r[k]) for k in FIELDS})
    os.replace(tmp, path(code))


def _fetch(code, rng):
    """日K：Yahoo 可用时用 Yahoo（与历史数据口径一致），连不上（国内常见）就用腾讯前复权日K。"""
    if not data.yahoo_ok():
        days = {"5y": 1250, "2y": 500, "1mo": 25}.get(rng, 1250)
        try:
            return [r for r in data._from_tencent(code, "A股", days)["rows"] if r["volume"] > 0]
        except Exception:  # noqa: BLE001
            pass
    res = data._from_yahoo(data.yahoo_symbol(code, "A股"), rng)
    return [r for r in res["rows"] if r["volume"] > 0]  # 去掉停牌日


def sync(mode="update", workers=None, codes=None):
    os.makedirs(CACHE, exist_ok=True)
    workers = workers or (8 if data.yahoo_ok() else 16)   # 腾讯每只要 2 次请求，并发高一点
    uni = load_universe()
    codes = codes or [u["code"] for u in uni]
    rng = "5y" if mode == "full" else "1mo"
    ok, fail, t0 = 0, [], time.time()

    def job(code):
        old = read(code)
        r = "5y" if (mode == "full" or len(old) < 250) else rng
        if mode == "full" and len(old) >= 1000 and time.time() - os.path.getmtime(path(code)) < 86400:
            return code, "skip"  # 断点续传：24 小时内已拉过
        new = _fetch(code, r)
        if r != "2y":
            # 复权因子可能变化：重叠区间收盘价偏差 >0.5% 时整体重拉
            om = {x["date"]: x["close"] for x in old}
            ov = [(om[x["date"]], x["close"]) for x in new if x["date"] in om]
            if ov and any(abs(a / b - 1) > 0.005 for a, b in ov if b):
                new, merged = _fetch(code, "5y"), None
            else:
                merged = {x["date"]: x for x in old}
                merged.update({x["date"]: x for x in new})
                new = [merged[k] for k in sorted(merged)][-1300:]
        write(code, new)
        return code, len(new)

    with ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(job, c): c for c in codes}
        for i, f in enumerate(as_completed(futs), 1):
            try:
                f.result()
                ok += 1
            except Exception as e:  # noqa: BLE001
                fail.append((futs[f], str(e)[:80]))
            if i % 250 == 0:
                print("%d/%d ok=%d fail=%d %.0fs" % (i, len(codes), ok, len(fail), time.time() - t0), flush=True)
    # 失败的慢速重试一次
    if fail:
        retry = [c for c, _ in fail]
        fail = []
        for c in retry:
            try:
                job(c)
                ok += 1
            except Exception as e:  # noqa: BLE001
                fail.append((c, str(e)[:80]))
            time.sleep(0.3)
    json.dump(uni, open(UNIVERSE, "w", encoding="utf-8"), ensure_ascii=False)
    print("完成 ok=%d fail=%d 用时 %.0fs" % (ok, len(fail), time.time() - t0), flush=True)
    if fail:
        print("失败样例:", fail[:10], flush=True)
    return ok, fail


QUOTES = os.path.join(HERE, "cache", "quotes.json")


def tencent_quotes(codes, batch=60):
    """腾讯实时行情（批量）。返回 {code: {...}}；成交量单位换算为“股”，与 Yahoo 一致。"""
    import urllib.request
    out = {}
    syms = [("sh" if c.startswith("6") else "sz") + c for c in codes]

    def one(i):
        url = "https://qt.gtimg.cn/q=" + ",".join(syms[i:i + batch])
        for attempt in range(3):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                txt = urllib.request.urlopen(req, timeout=10).read().decode("gbk", "ignore")
                break
            except Exception:  # noqa: BLE001
                time.sleep(1 + attempt)
        else:
            return {}
        res = {}
        for line in txt.split(";"):
            if '="' not in line:
                continue
            f = line.split('"')[1].split("~")
            if len(f) < 49 or not f[3] or float(f[3] or 0) <= 0:
                continue

            def num(k):
                try:
                    return float(f[k])
                except (ValueError, IndexError):
                    return None
            ts = f[30]
            # 成交量单位：沪深主板/创业板为“手”，科创板为“股”。用 成交额(万元) ÷ (量 × 价) 自动判定，避免差 100 倍
            vol_raw, amt, px = num(6) or 0, num(37) or 0, num(3) or 0
            mult = 100
            if vol_raw > 0 and px > 0 and amt > 0:
                mult = 1 if abs(amt * 1e4 / (vol_raw * px) - 1) < 0.5 else 100
            res[f[2]] = {"name": f[1], "price": num(3), "prev_close": num(4), "open": num(5),
                         "volume": vol_raw * mult, "high": num(33), "low": num(34),
                         "date": "%s-%s-%s" % (ts[:4], ts[4:6], ts[6:8]), "time": ts[8:12],
                         "turnover": num(38), "pe": num(39), "pb": num(46),
                         "float_mv": (num(44) or 0) * 1e8, "total_mv": (num(45) or 0) * 1e8,
                         "limit_up": num(47), "limit_down": num(48)}
        return res
    with ThreadPoolExecutor(8) as ex:
        for r in ex.map(one, range(0, len(syms), batch)):
            out.update(r)
    return out


def trading_days(n=10):
    """最近 n 个交易日（以沪深300 日K为准，含今天盘中）。复权接口偶尔返回 501，退回普通日K接口。"""
    import urllib.request
    last = None
    for url in ("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh000300,day,,,%d,qfq" % n,
                "https://web.ifzq.gtimg.cn/appstock/app/kline/kline?param=sh000300,day,,,%d" % n):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            d = json.loads(urllib.request.urlopen(req, timeout=15).read())
            return [r[0] for r in d["data"]["sh000300"]["day"]]
        except Exception as e:  # noqa: BLE001
            last = e
    raise last


def topup_today(codes=None):
    """用腾讯实时行情补上 Yahoo 还没有的最新交易日（盘中运行则为当日实时K线）。
    只在本地最后一根正好是“上一个交易日”时才追加今天、才做除权判断；中间缺了交易日的（例如有一天没运行）
    跳过不动，由 scan.py 先用 Yahoo 补齐历史。以前这里会把缺口误判成除权、错误地缩放整段历史。"""
    codes = codes or [u["code"] for u in load_universe()]
    t0 = time.time()
    q = tencent_quotes(codes)
    try:
        days = trading_days()
    except Exception:  # noqa: BLE001
        days = []
    added = refreshed = rescaled = gaps = 0
    for code, x in q.items():
        rows = read(code)
        if not rows or x["open"] is None or x["volume"] <= 0:
            continue
        bar = {"date": x["date"], "open": x["open"], "high": x["high"], "low": x["low"],
               "close": x["price"], "volume": x["volume"]}
        prev = days[days.index(x["date"]) - 1] if x["date"] in days and days.index(x["date"]) > 0 else None
        if rows[-1]["date"] == x["date"]:
            rows[-1] = bar
            refreshed += 1
        elif rows[-1]["date"] < x["date"] and prev and rows[-1]["date"] < prev:
            gaps += 1          # 中间缺交易日（或长期停牌后复牌）：不追加、不缩放
            continue
        elif rows[-1]["date"] < x["date"]:
            # 除权除息：昨日收盘与缓存不一致时，按比例重算历史（前复权）
            if x["prev_close"] and abs(rows[-1]["close"] / x["prev_close"] - 1) > 0.003:
                f = x["prev_close"] / rows[-1]["close"]
                for r in rows:
                    for k in ("open", "high", "low", "close"):
                        r[k] *= f
                rescaled += 1
            rows.append(bar)
            added += 1
        else:
            continue
        write(code, rows)
    json.dump(q, open(QUOTES, "w", encoding="utf-8"), ensure_ascii=False)
    print("实时补齐：报价 %d 只，新增当日K线 %d，刷新当日K线 %d，复权重算 %d，缺交易日跳过 %d，用时 %.0fs"
          % (len(q), added, refreshed, rescaled, gaps, time.time() - t0),
          flush=True)
    return q


def load_quotes():
    try:
        return json.load(open(QUOTES, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "update"
    if mode == "today":
        topup_today()
    else:
        sync(mode)
        topup_today()
