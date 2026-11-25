# -*- coding: utf-8 -*-
"""保存每日筛选结果 + 比对（检验之前选出的股票后来涨了多少）。
比对口径：
  主力选股：信号价 = 信号日收盘价；T+n = 第 n 个交易日收盘相对信号价的涨跌（%）
  AI 盯盘：信号价 = 盘中触发价；r0 = 触发价→当日收盘；T+n 同上
  同期大盘：A股 沪深300，美股 标普500；超额 = 个股 − 大盘
  max5 / min5：T+1..T+5 的最高/最低价相对信号价；stop_hit：这 5 天内收盘跌破止损"""
import json
import os
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "screener"))
from journal import db  # noqa: E402

SCAN_OUT = os.path.join(BASE, "screener", "cache", "scan_latest.json")
BENCH = {"cn": ("fqkline", "sh000300"), "us": ("usfqkline", "us.INX")}
TRACK_DAYS = 10
UA = {"User-Agent": "Mozilla/5.0"}


def _get_json(url, tries=3):
    for _ in range(tries):
        try:
            return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=12).read())
        except Exception:  # noqa: BLE001
            continue
    return None


def klines(sym, market="cn", n=60):
    """腾讯前复权日K → [(date, open, close, high, low)] 升序。复权接口偶尔对本机返回 501，退回不复权接口。"""
    api = "usfqkline" if market == "us" else "fqkline"
    for url in ("https://web.ifzq.gtimg.cn/appstock/app/%s/get?param=%s,day,,,%d,qfq" % (api, sym, n),
                "https://web.ifzq.gtimg.cn/appstock/app/kline/kline?param=%s,day,,,%d" % (sym, n)):
        d = _get_json(url, tries=2)
        try:
            node = d["data"][sym]
        except (TypeError, KeyError):
            continue
        rs = node.get("qfqday") or node.get("day") or []
        if rs:
            return [(r[0], float(r[1]), float(r[2]), float(r[3]), float(r[4])) for r in rs if len(r) >= 5]
    return []


def _sym(code, market, detail):
    if market == "us":
        return detail.get("sym") or ("us" + code)
    return ("sh" if code.startswith(("6", "9")) else "sz") + code


def raw_closes(sym, n=60):
    """不复权日收盘 {date: close}：盯盘触发价是当时的真实价格，r0 要和当日真实收盘比（复权价在之后除权时会变）。"""
    d = _get_json("https://web.ifzq.gtimg.cn/appstock/app/kline/kline?param=%s,day,,,%d" % (sym, n), tries=2)
    try:
        return {r[0]: float(r[2]) for r in d["data"][sym]["day"]}
    except (TypeError, KeyError, ValueError, IndexError):
        return {}


def us_full_syms(codes):
    """美股日K接口要交易所后缀（usAAPL.OQ / usKO.N）：用 qt 报价第 3 个字段取。"""
    out = {}
    codes = sorted(set(codes))
    for i in range(0, len(codes), 60):
        try:
            txt = urllib.request.urlopen(urllib.request.Request(
                "https://qt.gtimg.cn/q=" + ",".join("us" + c for c in codes[i:i + 60]), headers=UA), timeout=10
            ).read().decode("gbk", "ignore")
        except Exception:  # noqa: BLE001
            continue
        for line in txt.split(";"):
            if '="' in line:
                f = line.split('"')[1].split("~")
                if len(f) > 2 and "." in f[2]:
                    out[f[2].split(".")[0]] = "us" + f[2]
    return out


# ---------------- 保存 ----------------

def save_screener(path=SCAN_OUT):
    """把最新一次主力选股扫描结果（近 N 日的全部信号）存进数据库。"""
    r = json.load(open(path, encoding="utf-8"))
    items = []
    for s in r.get("signals", []):
        items.append({"date": s["date"], "code": s["code"], "name": s["name"], "method": s["method"],
                      "score": s.get("score"), "price": s.get("close"), "stop": s.get("stop"),
                      "validated": s.get("validated"), "note": s.get("validation_note", ""),
                      "grade": "已验证" if s.get("validated") else "",
                      "detail": {k: s.get(k) for k in ("pct", "entry_rule", "flags", "targets", "resonance",
                                                          "pe", "turnover", "float_mv", "neck", "peak")}})
    n = db.save_picks(items, "screener", "cn", info="扫描 %s，数据日期 %s" % (r.get("generated"), r.get("data_date")))
    return {"saved": n, "dates": sorted({x["date"] for x in items})}


def monitor_items(replay_res, pool_label):
    """回放 / 实盘结果 → 数据库条目。全部信号都存（含被剔除的），方便比对“纪律分”到底有没有用。"""
    seen, items = set(), []
    for s in sorted(replay_res.get("signals", []), key=lambda x: x.get("t", 0)):
        key = (s["code"], s["strategy"])
        if key in seen:
            continue
        seen.add(key)
        items.append({"date": replay_res["date"], "time": s.get("time", ""), "code": s["code"], "name": s.get("name", ""),
                      "method": s.get("strategy_name") or s["strategy"], "grade": s.get("grade", ""),
                      "score": s.get("score"), "price": s.get("price"), "stop": s.get("stop"),
                      "validated": s.get("grade") in ("A", "B"), "note": s.get("reason", ""),
                      "detail": {"strategy": s["strategy"], "chg": s.get("chg"), "lb": s.get("lb"), "verdict": s.get("verdict"),
                                 "checks": [{"name": c["name"], "ok": c["ok"]} for c in s.get("checks", [])],
                                 "pool": pool_label}})
    return items


def save_monitor(date, market="cn", n=1500):
    from monitor import service as M
    res = M.replay(date, market=market, n=n, with_after=False)
    label = "全市场" if not n else str(n)
    items = monitor_items(res, label)
    saved = db.save_picks(items, "monitor", market, pool=label, info="回放保存")
    return {"saved": saved, "hits": sum(1 for x in items if x["validated"]), "date": date}


def save_live_hits(market, n, date, signals):
    label = "全市场" if not n else str(n)
    items = monitor_items({"date": date, "signals": signals}, label)
    return db.save_picks(items, "monitor", market, pool=label, info="实盘自动保存") if items else 0


# ---------------- 比对 ----------------

def evaluate(log=print):
    """给还没跟踪满 10 个交易日的条目补上后续表现。"""
    todo = db.rows("""SELECT p.id, p.source, p.market, p.date, p.code, p.price, p.stop, p.detail, f.r0, f.days
                      FROM picks p LEFT JOIN perf f ON f.pick_id=p.id
                      WHERE f.pick_id IS NULL OR f.days < ? OR f.r1 IS NULL""", (TRACK_DAYS,))
    if not todo:
        return {"updated": 0, "pending": 0}
    out = {"updated": 0, "pending": 0}
    for market in ("cn", "us"):
        items = [t for t in todo if t["market"] == market]
        if not items:
            continue
        api, bsym = BENCH[market]
        # 还没收盘的当天 K 线不参与比对（否则 T+1 会随盘中价格变动），收盘后下次比对再计入
        from datetime import datetime
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Asia/Shanghai" if market == "cn" else "America/New_York"))
        open_day = now.strftime("%Y-%m-%d") if now.weekday() < 5 and now.hour * 100 + now.minute < (1500 if market == "cn" else 1600) else None
        bench = {d: c for d, _, c, _, _ in klines(bsym, market, 400) if d != open_day}
        oldest = min(t["date"] for t in items)
        need = 30 + sum(1 for d in bench if d >= oldest)
        full = us_full_syms([t["code"] for t in items]) if market == "us" else {}
        syms = {}
        for t in items:
            s0 = full.get(t["code"]) or _sym(t["code"], market, json.loads(t["detail"] or "{}"))
            syms.setdefault(s0, []).append(t)
        last_trade = max(bench) if bench else ""

        def load(s):
            if market == "cn":   # 主力选股的本地日K（每次扫描都会补到当天）够新就直接用，省得逐只下载
                import datastore
                rs = datastore.read(s[2:])
                if rs and rs[-1]["date"] >= last_trade:
                    return [(r["date"], r["open"], r["close"], r["high"], r["low"]) for r in rs[-need:]]
            return klines(s, market, min(640, need))
        with ThreadPoolExecutor(16) as ex:
            data = dict(zip(syms, ex.map(load, syms)))
            need_raw = [x for x, ts in syms.items() if any(t["source"] == "monitor" and t["r0"] is None for t in ts)]
            raw = dict(zip(need_raw, ex.map(lambda x: raw_closes(x, min(640, need)), need_raw)))
        now = db.stamp()
        upd = []
        for s, ts in syms.items():
            bars = [b for b in (data.get(s) or []) if b[0] != open_day]
            idx = {b[0]: i for i, b in enumerate(bars)}
            for t in ts:
                i = idx.get(t["date"])
                if i is None:
                    out["pending"] += 1
                    continue
                base = bars[i][2]
                after = bars[i + 1:i + 1 + TRACK_DAYS]
                if t["source"] == "monitor":
                    if t["r0"] is not None:
                        r0 = t["r0"]
                    else:
                        rc = (raw.get(s) or {}).get(t["date"]) or base
                        r0 = round((rc / t["price"] - 1) * 100, 2) if t["price"] else 0.0
                    k = 1 + r0 / 100      # 触发价 → 当日收盘
                else:
                    r0, k = None, 1.0

                def rel(px):
                    return round((k * px / base - 1) * 100, 2)

                def ret(h):
                    return rel(after[h - 1][2]) if len(after) >= h else None

                def bret(h):
                    if len(after) < h or t["date"] not in bench or after[h - 1][0] not in bench:
                        return None
                    return round((bench[after[h - 1][0]] / bench[t["date"]] - 1) * 100, 2)
                w5 = after[:5]
                stop_ratio = (t["stop"] / t["price"]) if t["stop"] and t["price"] else None
                stop_hit = int(bool(stop_ratio and any(k * b[2] / base < stop_ratio for b in w5)))
                upd.append((t["id"], len(after), after[-1][0] if after else t["date"], r0,
                            ret(1), ret(3), ret(5), ret(10), bret(1), bret(3), bret(5), bret(10),
                            max((rel(b[3]) for b in w5), default=None), min((rel(b[4]) for b in w5), default=None),
                            stop_hit, now))
        db.execute("""INSERT OR REPLACE INTO perf(pick_id,days,last_date,r0,r1,r3,r5,r10,b1,b3,b5,b10,max5,min5,stop_hit,updated)
                      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", upd, many=True)
        out["updated"] += len(upd)
        log("比对 %s：更新 %d 条" % (market, len(upd)))
    return out


if __name__ == "__main__":
    if "--save" in sys.argv:
        print(save_screener())
    print(evaluate())
