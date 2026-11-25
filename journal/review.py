# -*- coding: utf-8 -*-
"""每日复盘。顺序：外围市场（隔夜美股、亚太、商品汇率）→ 外围对 A 股的预期影响（并用当天板块涨跌验证）
→ A 股指数 / 成交额 / 涨跌家数 / 涨停跌停 / 连板 → 资金流向（全市场、行业、概念）→ 领涨领跌板块及原因
→ 当天选股与昨日选股的表现 → 汇总与明日要点。
数据：腾讯行情（指数、美股、港股、期货、板块排行、主力资金）、新浪（汇率、日韩指数、A50）、东方财富 7×24 快讯。
只能生成“最近一个交易日”的复盘（外围快照与资金流无法回溯），生成后存进数据库，历史随时可查。"""
import json
import os
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "screener"))
from journal import db  # noqa: E402

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36"


def _get(url, enc="utf-8", referer=None, timeout=12, tries=3):
    h = {"User-Agent": UA}
    if referer:
        h["Referer"] = referer
    for k in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout).read().decode(enc, "ignore")
        except Exception:  # noqa: BLE001
            time.sleep(0.6 * (k + 1))
    return ""


def _f(x, d=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def pct(a, b):
    return round((a / b - 1) * 100, 2) if a and b else None


# ---------------- 外围 ----------------

US = [("usDJI", "道琼斯"), ("usIXIC", "纳斯达克"), ("usINX", "标普500"), ("usSOXX", "费城半导体ETF"),
      ("usHXC", "中概金龙指数"), ("usNVDA", "英伟达"), ("usAAPL", "苹果"), ("usTSLA", "特斯拉"),
      ("usBABA", "阿里巴巴"), ("usPDD", "拼多多")]
HK = [("hkHSI", "恒生指数"), ("hkHSTECH", "恒生科技")]
HF = [("hf_CL", "纽约原油"), ("hf_GC", "纽约黄金"), ("hf_SI", "纽约白银"), ("hf_HG", "美铜")]
SINA = [("hf_CHA50CFD", "富时A50期货", "hf"), ("b_NKY", "日经225", "b"), ("b_KOSPI", "韩国KOSPI", "b"),
        ("DINIW", "美元指数", "fx"), ("fx_susdcnh", "离岸人民币", "fx")]


def _us_close_before(code, date):
    """美股 code（如 .DJI / SOXX.OQ）在 date 之前最后一个完整交易日的收盘与涨跌（用日K，避免美股盘中/盘前取到当天未完成的数据）。"""
    sym = "us" + code
    t = _get("https://web.ifzq.gtimg.cn/appstock/app/kline/kline?param=%s,day,,,8" % sym)
    try:
        rows = [r for r in json.loads(t)["data"][sym]["day"] if r[0] < date]
    except (ValueError, KeyError, TypeError):
        return None
    if len(rows) < 2:
        return None
    c, pc = float(rows[-1][2]), float(rows[-2][2])
    return {"price": c, "chg": pct(c, pc), "time": rows[-1][0] + " 收盘"}


def external(date=None):
    out = {"us": [], "asia": [], "commodity": [], "fx": [], "us_date": ""}
    txt = _get("https://qt.gtimg.cn/q=" + ",".join(s for s, _ in US + HK + HF), enc="gbk")
    for line in txt.split(";"):
        if '="' not in line:
            continue
        key = line.split("=")[0].strip().replace("v_", "")
        body = line.split('"')[1]
        if key.startswith("hf_"):
            f = body.split(",")
            name = dict(HF).get(key, key)
            out["commodity"].append({"sym": key, "name": name, "price": _f(f[0]), "chg": pct(_f(f[0]), _f(f[7])),
                                     "time": "%s %s" % (f[12] if len(f) > 12 else "", f[6])})
            continue
        f = body.split("~")
        if len(f) < 33:
            continue
        price, prev = _f(f[3]), _f(f[4])
        item = {"sym": key, "name": dict(US + HK).get(key, f[1]), "price": price, "chg": pct(price, prev),
                "time": f[30]}
        if key.startswith("us"):
            # 复盘看的是“A 股这个交易日之前”最后一个完整的美股交易日；盘中/盘前生成时改用日K
            if date and f[30][:10] >= date:
                fix = _us_close_before(f[2], date)
                if fix:
                    item.update(fix)
            out["us"].append(item)
            out["us_date"] = max(out["us_date"], item["time"][:10])
        else:
            out["asia"].append(item)
    txt = _get("https://hq.sinajs.cn/list=" + ",".join(s for s, _, _ in SINA), enc="gbk", referer="https://finance.sina.com.cn")
    for line in txt.split(";"):
        m = re.search(r'hq_str_(\S+?)="(.*)"', line)
        if not m or not m.group(2):
            continue
        key, f = m.group(1), m.group(2).split(",")
        name, kind = {s: (n, k) for s, n, k in SINA}[key]
        if kind == "b":
            item = {"sym": key, "name": name, "price": _f(f[1]), "chg": _f(f[3]), "time": "%s %s" % (f[6], f[5])}
            out["asia"].append(item)
        elif kind == "hf":
            out["asia"].append({"sym": key, "name": name, "price": _f(f[0]), "chg": pct(_f(f[0]), _f(f[7])),
                                "time": "%s %s" % (f[12], f[6])})
        else:
            out["fx"].append({"sym": key, "name": name, "price": _f(f[1]), "chg": pct(_f(f[1]), _f(f[3])),
                              "time": "%s %s" % (f[-1], f[0])})
    return out


# 外围因素 → A 股板块（板块名关键词，匹配腾讯申万二级行业与概念板块）
IMPACT_RULES = [
    ("usSOXX", "费城半导体", 2.0, ["半导体", "芯片", "集成电路", "存储", "光刻", "算力", "CPO", "光模块", "元件"], "科技链"),
    ("usNVDA", "英伟达", 3.0, ["算力", "CPO", "光模块", "液冷", "服务器", "PCB", "人工智能", "AI"], "AI 算力链"),
    ("usIXIC", "纳斯达克", 1.0, ["软件", "计算机", "通信设备", "电子", "人工智能"], "成长股情绪"),
    ("usHXC", "中概金龙", 1.5, ["互联网", "传媒", "游戏", "电商", "软件开发"], "中概 / 互联网"),
    ("usTSLA", "特斯拉", 3.0, ["特斯拉", "汽车零部件", "机器人", "减速器", "一体化压铸"], "特斯拉链"),
    ("usAAPL", "苹果", 2.0, ["消费电子", "苹果", "无线耳机"], "果链"),
    ("hf_CL", "原油", 2.0, ["石油", "油气", "油服", "炼化"], "油气"),
    ("hf_GC", "黄金", 1.5, ["贵金属", "黄金"], "贵金属"),
    ("hf_HG", "铜", 1.5, ["工业金属", "铜", "有色"], "有色金属"),
]


def impacts(ext, boards):
    allq = {x["sym"]: x for k in ("us", "asia", "commodity", "fx") for x in ext[k]}
    pool = [b for b in boards.get("hy2", []) + boards.get("gn", [])]
    out = []
    for sym, label, th, kws, group in IMPACT_RULES:
        q = allq.get(sym)
        if not q or q["chg"] is None:
            continue
        c = q["chg"]
        hit = [b for b in pool if any(k in b["name"] for k in kws)]
        avg = round(sum(b["zdf"] for b in hit) / len(hit), 2) if hit else None
        strong = abs(c) >= th
        exp = ("利好" if c > 0 else "利空") if strong else "影响有限"
        verdict = ""
        if strong and avg is not None:
            verdict = "兑现" if (avg > 0) == (c > 0) and abs(avg) >= 0.5 else ("背离" if (avg > 0) != (c > 0) and abs(avg) >= 0.5 else "未明显体现")
        out.append({"factor": "%s %+.2f%%" % (label, c), "sym": sym, "chg": c, "group": group, "expect": exp,
                    "strong": strong, "sectors": [{"name": b["name"], "zdf": b["zdf"]} for b in sorted(hit, key=lambda b: b["zdf"])[:6]],
                    "actual": avg, "verdict": verdict})
    # 汇率与整体情绪：离岸人民币贬值（USD/CNH 上涨）通常对应外资流出压力
    cnh = allq.get("fx_susdcnh")
    if cnh and cnh["chg"] is not None:
        out.append({"factor": "离岸人民币 %s %.2f%%" % ("贬值" if cnh["chg"] > 0 else "升值", abs(cnh["chg"])), "sym": "fx_susdcnh",
                    "chg": cnh["chg"], "group": "外资 / 汇率", "expect": ("利空" if cnh["chg"] > 0 else "利好") if abs(cnh["chg"]) >= 0.3 else "影响有限",
                    "strong": abs(cnh["chg"]) >= 0.3, "sectors": [], "actual": None, "verdict": ""})
    return out


# ---------------- A 股 ----------------

INDICES = [("sh000001", "上证指数"), ("sz399001", "深证成指"), ("sz399006", "创业板指"), ("sh000688", "科创50"),
           ("sh000300", "沪深300"), ("sh000905", "中证500"), ("sh000852", "中证1000"), ("bj899050", "北证50")]


def indices():
    txt = _get("https://qt.gtimg.cn/q=" + ",".join(s for s, _ in INDICES), enc="gbk")
    out = []
    for line in txt.split(";"):
        if '="' not in line:
            continue
        f = line.split('"')[1].split("~")
        if len(f) < 38:
            continue
        key = line.split("=")[0].strip().replace("v_", "")
        out.append({"sym": key, "name": dict(INDICES).get(key, f[1]), "price": _f(f[3]), "chg": _f(f[32]),
                    "amount": round((_f(f[37], 0) or 0) / 1e4, 1), "time": f[30]})
    return out


def turnover():
    """沪深两市成交额（亿元），近 5 个交易日，来自指数分时最后一笔累计成交额。"""
    from monitor import feed
    days = {}
    for s in ("sh000001", "sz399001"):
        d = feed.fetch_5day(s, "cn") or {}
        for k, v in d.items():
            if isinstance(v, dict) and v.get("bars"):
                days.setdefault(k, {})[s] = v["bars"][-1][3] / 1e8
    hist = [(k, round(v.get("sh000001", 0), 0), round(v.get("sz399001", 0), 0)) for k, v in sorted(days.items())
            if len(v) == 2]
    if not hist:
        return {}
    d, sh, sz = hist[-1]
    prev = hist[-2] if len(hist) > 1 else None
    tot = sh + sz
    ptot = prev[1] + prev[2] if prev else None
    avg5 = sum(a + b for _, a, b in hist) / len(hist)
    return {"date": d, "sh": sh, "sz": sz, "total": tot, "prev": ptot,
            "change": round(tot - ptot) if ptot else None, "change_pct": pct(tot, ptot),
            "avg5": round(avg5), "vs_avg5": pct(tot, avg5),
            "history": [{"date": k, "total": a + b} for k, a, b in hist]}


def boards():
    """腾讯板块排行：申万一级 hy、申万二级 hy2、概念 gn。zljlr = 主力净流入（万元）。"""
    out = {}

    def fetch(bt):
        res, off = [], 0
        while True:
            t = _get("https://proxy.finance.qq.com/cgi/cgi-bin/rank/pt/getRank?board_type=%s&sort_type=price"
                     "&direct=down&offset=%d&count=200" % (bt, off))
            try:
                d = json.loads(t)["data"]
            except (ValueError, KeyError, TypeError):
                break
            res += d["rank_list"]
            off += 200
            if off >= int(d.get("total", 0)) or not d["rank_list"]:
                break
        items = []
        for x in res:
            if bt == "gn" and x.get("stock_type") != "BK-GN":
                continue   # 去掉“昨日涨停”这类风格板块
            up, tot = (x.get("zgb") or "0/0").split("/")
            lz = x.get("lzg") or {}
            items.append({"code": x["code"], "name": x["name"], "zdf": _f(x.get("zdf"), 0), "flow": round(_f(x.get("zljlr"), 0) / 1e4, 2),
                          "flow5": round(_f(x.get("zljlr_d5"), 0) / 1e4, 2), "flow20": round(_f(x.get("zljlr_d20"), 0) / 1e4, 2),
                          "turnover": round(_f(x.get("turnover"), 0) / 1e4, 1), "zdf5": _f(x.get("zdf_d5")), "zdf20": _f(x.get("zdf_d20")),
                          "up": int(up or 0), "total": int(tot or 0), "hsl": _f(x.get("hsl")),
                          "leader": {"code": lz.get("code", "")[2:], "name": lz.get("name", ""), "zdf": _f(lz.get("zdf"))}})
        return bt, items
    with ThreadPoolExecutor(3) as ex:
        for bt, items in ex.map(fetch, ("hy", "hy2", "gn")):
            out[bt] = items
    return out


def board_stocks(code, n=5, direct="down"):
    t = _get("https://proxy.finance.qq.com/cgi/cgi-bin/rank/hs/getBoardRankList?board_code=%s&sort_type=priceRatio"
             "&direct=%s&offset=0&count=%d" % (code, direct, n))
    try:
        L = json.loads(t)["data"]["rank_list"]
    except (ValueError, KeyError, TypeError):
        return []
    return [{"code": x["code"][2:], "name": x["name"], "zdf": _f(x.get("zdf")), "price": _f(x.get("zxj"))} for x in L]


def breadth():
    """涨跌家数、涨停跌停、炸板、连板梯队（沪深 A 股，不含北交所与 ST）。"""
    import datastore
    from monitor import strategies as S
    uni = datastore.load_universe()
    q = datastore.tencent_quotes([u["code"] for u in uni])
    chg, lu, ld, zb = [], [], [], []
    date = max((x["date"] for x in q.values()), default="")
    for c, x in q.items():
        if x["date"] != date or not x["prev_close"] or not x["price"] or (x["volume"] or 0) <= 0:
            continue
        r = (x["price"] / x["prev_close"] - 1) * 100
        chg.append(r)
        if x["limit_up"] and x["price"] >= x["limit_up"] - 0.005:
            lu.append((c, x))
        elif x["limit_down"] and x["price"] <= x["limit_down"] + 0.005:
            ld.append((c, x))
        if x["limit_up"] and x["high"] and x["high"] >= x["limit_up"] - 0.005 and x["price"] < x["limit_up"] - 0.005:
            zb.append((c, x))
    streak = {}
    for c, x in lu:
        rows = datastore.read(c)
        rows = [r for r in rows if r["date"] < date]
        lim = S.limit_pct(c)
        k = 1
        for a, b in zip(reversed(rows[:-1]), reversed(rows[1:])):
            if b["close"] / a["close"] - 1 >= lim - 0.006:
                k += 1
            else:
                break
        streak.setdefault(k, []).append({"code": c, "name": x["name"], "turnover": x.get("turnover")})
    chg.sort()
    buckets = [("≥9%", 9, 99), ("5~9%", 5, 9), ("2~5%", 2, 5), ("0~2%", 0.0001, 2), ("平", -0.0001, 0.0001),
               ("−2~0%", -2, -0.0001), ("−5~−2%", -5, -2), ("−9~−5%", -9, -5), ("≤−9%", -99, -9)]
    dist = [{"label": lb, "n": sum(1 for r in chg if lo <= r < hi or (hi == 0.0001 and lo <= r <= hi))} for lb, lo, hi in buckets]
    up = sum(1 for r in chg if r > 0)
    down = sum(1 for r in chg if r < 0)
    touched = len(lu) + len(zb)
    return {"date": date, "count": len(chg), "up": up, "down": down, "flat": len(chg) - up - down,
            "median": round(chg[len(chg) // 2], 2) if chg else None,
            "mean": round(sum(chg) / len(chg), 2) if chg else None,
            "limit_up": len(lu), "limit_down": len(ld), "zhaban": len(zb),
            "zhaban_rate": round(100 * len(zb) / touched, 1) if touched else None,
            "max_streak": max(streak) if streak else 0,
            "ladder": [{"n": k, "stocks": v[:12], "count": len(v)} for k, v in sorted(streak.items(), reverse=True)],
            "dist": dist,
            "limit_up_list": [{"code": c, "name": x["name"], "turnover": x.get("turnover")} for c, x in lu][:200],
            "limit_down_list": [{"code": c, "name": x["name"]} for c, x in ld][:100]}


def news(date):
    """东方财富 7×24 快讯：取当天（含前一晚 15:00 以后）的全部条目。"""
    items, seen = [], set()
    for p in range(1, 9):
        t = _get("https://newsapi.eastmoney.com/kuaixun/v1/getlist_102_ajaxResult_100_%d_.html" % p)
        try:
            L = json.loads(t[t.index("{"):])["LivesList"]
        except (ValueError, KeyError):
            break
        stop = False
        for x in L:
            if x["id"] in seen:
                continue
            seen.add(x["id"])
            st = x.get("showtime", "")
            if st[:10] < date and st[11:13] < "15":
                stop = True
                continue
            items.append({"time": st, "title": x.get("title", ""), "digest": (x.get("digest") or "")[:300],
                          "url": x.get("url_w", "")})
        if stop:
            break
    return items


def _kw(name):
    base = re.sub(r"(Ⅱ|Ⅲ|行业|概念|板块)$", "", name)
    ks = {base}
    if len(base) >= 4:
        ks.add(base[:2])
    return [k for k in ks if len(k) >= 2]


def reasons_for(b, stocks, nws, imp, flow_rank):
    """板块涨跌的主要原因：资金、龙头、外围联动、相关快讯（按关键词与龙头股名匹配）。"""
    rs = []
    if b["flow"]:
        rs.append("主力资金%s %.1f 亿（%s第 %d）" % ("净流入" if b["flow"] > 0 else "净流出", abs(b["flow"]),
                                            "流入" if b["flow"] > 0 else "流出", flow_rank))
    if b["total"]:
        rs.append("板块内 %d/%d 家上涨" % (b["up"], b["total"]))
    lead = [s for s in stocks if s["zdf"] is not None][:3]
    if lead:
        rs.append("领涨股：" + "、".join("%s %+.1f%%" % (s["name"], s["zdf"]) for s in lead) if b["zdf"] >= 0
                  else "成分股：" + "、".join("%s %+.1f%%" % (s["name"], s["zdf"]) for s in lead))
    rules = {r[0]: r[3] for r in IMPACT_RULES}
    for i in imp:
        if i["strong"] and any(k in b["name"] for k in rules.get(i["sym"], [])):
            rs.append("外围联动：%s（%s%s）" % (i["factor"], i["group"], i["expect"]))
            break
    kws = _kw(b["name"]) + [s["name"] for s in stocks[:5] if len(s["name"]) >= 2]
    hits = [n for n in nws if any(k in n["title"] for k in kws)][:3]
    if len(hits) < 3:
        hits += [n for n in nws if n not in hits and any(k in n["digest"] for k in kws)][:3 - len(hits)]
    return rs, [{"time": n["time"][11:16], "title": n["title"], "url": n["url"]} for n in hits]


def regime():
    import backtest
    reg = backtest.market_regime()
    d = sorted(reg)
    return {"date": d[-1], "above_ma20": reg[d[-1]], "recent": [{"date": x, "above": reg[x]} for x in d[-10:]]}


# ---------------- 汇总 ----------------

def phase_now():
    import datastore
    now = db.bj_now()
    today = now.strftime("%Y-%m-%d")
    try:
        days = datastore.trading_days(15)
    except Exception:  # noqa: BLE001
        days = []
    last = days[-1] if days else today
    hm = now.hour * 100 + now.minute
    if last == today and hm < 1500:
        kind = "盘中" if hm >= 930 else "盘前"
    elif last < today and now.weekday() < 5 and hm < 930:
        kind, last = "盘前", today
    else:
        kind = "收盘"
    prev = [d for d in days if d < last]
    return {"date": last, "kind": kind, "prev": prev[-1] if prev else None, "now": now.strftime("%Y-%m-%d %H:%M:%S")}


def fmt_yi(x):
    return ("%.2f 万亿" % (x / 1e4)) if abs(x) >= 1e4 else ("%.0f 亿" % x)


def compose(r):
    """把各部分拼成一段可读的复盘摘要（纯规则生成，可核对每个数字的出处）。"""
    P = []
    ext = r.get("external") or {}
    us = {x["sym"]: x for x in ext.get("us", [])}
    asia = {x["sym"]: x for x in ext.get("asia", [])}
    com = {x["sym"]: x for x in ext.get("commodity", []) + ext.get("fx", [])}

    def q(d, s, label=None):
        x = d.get(s)
        return "%s %+.2f%%" % (label or x["name"], x["chg"]) if x and x["chg"] is not None else None
    us_line = "、".join(filter(None, [q(us, "usDJI", "道指"), q(us, "usIXIC", "纳指"), q(us, "usINX", "标普"),
                                      q(us, "usSOXX", "费城半导体"), q(us, "usHXC", "中概金龙")]))
    if us_line:
        P.append("【外围】隔夜美股（%s）：%s。" % (ext.get("us_date", ""), us_line))
    as_line = "、".join(filter(None, [q(asia, "hkHSI"), q(asia, "hkHSTECH"), q(asia, "b_NKY"), q(asia, "b_KOSPI"),
                                      q(asia, "hf_CHA50CFD", "A50期货")]))
    if as_line:
        P.append("亚太：%s。" % as_line)
    c_line = "、".join(filter(None, [q(com, "hf_CL", "原油"), q(com, "hf_GC", "黄金"), q(com, "hf_HG", "铜"),
                                     q(com, "DINIW", "美元指数"), q(com, "fx_susdcnh", "美元/离岸人民币")]))
    if c_line:
        P.append("商品汇率：%s。" % c_line)
    strong = [i for i in r.get("impacts", []) if i["strong"]]
    if strong:
        P.append("外围影响：" + "；".join(
            "%s → %s%s%s" % (i["factor"], i["group"], i["expect"],
                             ("，实际相关板块平均 %+.2f%%（%s）" % (i["actual"], i["verdict"])) if i["actual"] is not None else "")
            for i in strong[:5]) + "。")
    idx = {x["sym"]: x for x in r.get("indices", [])}
    if idx:
        P.append("【A股】" + "，".join("%s %+.2f%%" % (idx[s]["name"], idx[s]["chg"]) for s in
                                    ("sh000001", "sz399001", "sz399006", "sh000688", "sh000300") if s in idx and idx[s]["chg"] is not None) + "。")
    t = r.get("turnover") or {}
    if t.get("total"):
        s = "两市成交 %s" % fmt_yi(t["total"])
        if t.get("prev"):
            s += "，较前一日%s %s（%+.1f%%）" % ("放量" if t["change"] > 0 else "缩量", fmt_yi(abs(t["change"])), t["change_pct"])
        if t.get("vs_avg5") is not None:
            s += "，%s 5 日均量 %.1f%%" % ("高于" if t["vs_avg5"] > 0 else "低于", abs(t["vs_avg5"]))
        P.append(s + "。")
    b = r.get("breadth") or {}
    if b.get("count"):
        P.append("上涨 %d 家、下跌 %d 家（中位数 %+.2f%%）；涨停 %d、跌停 %d，炸板 %d（炸板率 %s%%），最高 %d 连板。" % (
            b["up"], b["down"], b["median"], b["limit_up"], b["limit_down"], b["zhaban"],
            b["zhaban_rate"] if b["zhaban_rate"] is not None else "-", b["max_streak"]))
    f = r.get("flow") or {}
    if f.get("main") is not None:
        P.append("【资金】主力%s %.0f 亿；行业流入前三：%s；流出前三：%s。" % (
            "净流入" if f["main"] > 0 else "净流出", abs(f["main"]),
            "、".join("%s %+.1f亿" % (x["name"], x["flow"]) for x in f["in"][:3]),
            "、".join("%s %+.1f亿" % (x["name"], x["flow"]) for x in f["out"][:3])))
    sec = r.get("sectors") or {}
    if sec.get("top"):
        P.append("【板块】领涨：%s；领跌：%s。" % (
            "、".join("%s %+.2f%%" % (x["name"], x["zdf"]) for x in sec["top"][:4]),
            "、".join("%s %+.2f%%" % (x["name"], x["zdf"]) for x in sec["bottom"][:4])))
    rg = r.get("regime") or {}
    if rg:
        P.append("【环境】沪深300 %s（%s）。" % ("站上 20 日线" if rg["above_ma20"] else "位于 20 日线下方", rg["date"]) +
                 ("突破类方法（筹码峰突破、箱体突破）回测有效的环境。" if rg["above_ma20"]
                  else "回测显示此环境下突破类方法普遍跑输大盘，宜控制仓位、少追高。"))
    y = r.get("yesterday") or {}
    if y.get("methods"):
        ms = [m for m in y["methods"] if m.get("n1")]
        if ms:
            P.append("【昨日选股比对】%s 的选股今天表现：" % y["date"] + "；".join(
                "%s%s %d 只 平均 %+.2f%%（胜率 %.0f%%，超额 %+.2f%%）" % (
                    m["method"], "·" + m["tier"] if m["source"] == "monitor" else "", m["n1"], m["r1"], m["win1"],
                    m.get("ex1") or 0) for m in sorted(ms, key=lambda m: -m["n1"])[:5]) + "。")
    return "\n".join(P)


def outlook(r):
    tips = []
    rg = r.get("regime") or {}
    b = r.get("breadth") or {}
    t = r.get("turnover") or {}
    if rg and not rg.get("above_ma20"):
        tips.append("沪深300 在 20 日线下：轻仓，突破类信号只观察不追；等指数站回 20 日线再加大仓位。")
    elif rg:
        tips.append("沪深300 在 20 日线上：筹码峰突破、箱体突破属于回测验证有效的组合，可重点跟踪“已验证”信号。")
    if b.get("count") and b["down"] > b["up"] * 3:
        tips.append("下跌家数是上涨的 %.1f 倍，普跌行情，次日先看能否止跌，不急于抄底。" % (b["down"] / max(1, b["up"])))
    if b.get("zhaban_rate") and b["zhaban_rate"] >= 35:
        tips.append("炸板率 %.0f%% 偏高，打板/接力资金亏钱效应明显，短线降低追涨。" % b["zhaban_rate"])
    if t.get("change_pct") is not None and t["change_pct"] <= -10 and (r.get("indices") or [{}])[0].get("chg", 0) < 0:
        tips.append("缩量下跌：抛压未必集中释放，关注是否出现放量止跌信号。")
    elif t.get("change_pct") is not None and t["change_pct"] >= 15:
        tips.append("明显放量：留意资金主攻方向的持续性（看主力净流入前三板块次日是否继续强势）。")
    strong = [i for i in r.get("impacts", []) if i["strong"] and i["verdict"] == "兑现"]
    for i in strong[:2]:
        tips.append("外围 %s 已在 A 股 %s 兑现，次日继续看隔夜同一指标。" % (i["factor"], i["group"]))
    return tips


def build(log=print):
    t0 = time.time()
    ph = phase_now()
    r = {"date": ph["date"], "kind": ph["kind"], "generated": ph["now"], "prev_date": ph["prev"], "errors": []}

    def safe(name, fn, *a):
        try:
            return fn(*a)
        except Exception as e:  # noqa: BLE001
            r["errors"].append("%s：%s" % (name, e))
            log("复盘 %s 失败：%s" % (name, e))
            return None
    with ThreadPoolExecutor(6) as ex:
        fut = {k: ex.submit(safe, k, fn) for k, fn in
               (("external", lambda: external(ph["date"])), ("indices", indices), ("turnover", turnover), ("boards", boards),
                ("breadth", breadth), ("regime", regime))}
        fut["news"] = ex.submit(safe, "news", news, ph["date"])
        res = {k: f.result() for k, f in fut.items()}
    log("复盘数据抓取完成 %.0fs" % (time.time() - t0))
    bd = res["boards"] or {}
    nws = res["news"] or []
    r.update({k: res[k] for k in ("external", "indices", "turnover", "breadth", "regime")})
    r["impacts"] = impacts(res["external"] or {"us": [], "asia": [], "commodity": [], "fx": []}, bd)
    hy = bd.get("hy", [])
    if hy:
        main = round(sum(x["flow"] for x in hy), 1)
        by_flow = sorted(hy, key=lambda x: -x["flow"])
        gn = bd.get("gn", [])
        gflow = sorted(gn, key=lambda x: -x["flow"])
        r["flow"] = {"main": main, "main5": round(sum(x["flow5"] for x in hy), 1), "main20": round(sum(x["flow20"] for x in hy), 1),
                     "turnover": round(sum(x["turnover"] for x in hy), 1),
                     "in": by_flow[:10], "out": by_flow[::-1][:10], "industries": hy,
                     "concept_in": gflow[:10], "concept_out": gflow[::-1][:10]}
    if bd.get("hy2"):
        hy2 = sorted(bd["hy2"], key=lambda x: -x["zdf"])
        gn = sorted([g for g in bd.get("gn", []) if g["total"] >= 8], key=lambda x: -x["zdf"])
        rank = {x["code"]: i + 1 for i, x in enumerate(sorted(bd["hy2"] + bd.get("gn", []), key=lambda x: -x["flow"]))}
        rank_out = {x["code"]: i + 1 for i, x in enumerate(sorted(bd["hy2"] + bd.get("gn", []), key=lambda x: x["flow"]))}
        pick = [("top", hy2[:6]), ("bottom", hy2[::-1][:6]), ("concept_top", gn[:6]), ("concept_bottom", gn[::-1][:6])]
        sec = {}
        with ThreadPoolExecutor(8) as ex:
            stocks = dict(zip([b["code"] for _, bs in pick for b in bs],
                              ex.map(lambda b: board_stocks(b["code"], 5, "down" if b["zdf"] >= 0 else "up"),
                                     [b for _, bs in pick for b in bs])))
        for key, bs in pick:
            lst = []
            for b in bs:
                ss = stocks.get(b["code"]) or []
                rs, nn = reasons_for(b, ss, nws, r["impacts"],
                                     rank.get(b["code"], 0) if b["flow"] > 0 else rank_out.get(b["code"], 0))
                lst.append({**b, "stocks": ss, "reasons": rs, "news": nn})
            sec[key] = lst
        r["sectors"] = sec
    r["news"] = nws[:60]
    # 当天选股 + 昨日选股今天的表现（来自数据库）
    try:
        from journal import tracker
        tracker.evaluate(log)
    except Exception as e:  # noqa: BLE001
        r["errors"].append("比对：%s" % e)
    day = db.day(ph["date"])
    r["picks"] = {"screener": sum(1 for p in day["picks"] if p["source"] == "screener"),
                  "monitor": sum(1 for p in day["picks"] if p["source"] == "monitor"),
                  "validated": sum(1 for p in day["picks"] if p["validated"])}
    if ph["prev"]:
        r["yesterday"] = {"date": ph["prev"], "methods": db.method_stats(ph["prev"], ph["prev"])}
    r["summary"] = compose(r)
    r["outlook"] = outlook(r)
    r["seconds"] = round(time.time() - t0)
    db.save_review(ph["date"], ph["kind"], r["summary"], r)
    log("复盘完成：%s（%s），用时 %ds，错误 %d" % (ph["date"], ph["kind"], r["seconds"], len(r["errors"])))
    return r


if __name__ == "__main__":
    res = build()
    print(res["summary"])
    print("\n".join(res["outlook"]))
    print(res["errors"])
