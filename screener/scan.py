# -*- coding: utf-8 -*-
"""每日选股：对全市场最新交易日（及最近几日）运行 8 种形态方法，叠加通用过滤，输出 cache/scan_latest.json。
用法：python3 scan.py [--no-update] [--days 3]"""
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

OUT = os.path.join(HERE, "cache", "scan_latest.json")
SUMMARY = os.path.join(HERE, "cache", "backtest_summary.json")


def risk_flags(ctx, t, q):
    """通用风控：上方套牢盘压力大、无量阴跌不碰、业绩排雷。返回 (扣分, [提示])"""
    pen, flags = 0, []
    s = ctx.chip.get(t)
    if s and s["peaks"] >= 2 and s["profit"] < 40:
        pen += 15
        flags.append("上方仍有套牢筹码峰（获利盘 %.0f%%），上方套牢盘压力大" % s["profit"])
    a = max(0, t - 9)
    if ctx.c[t] < ctx.c[a] and np.all(ctx.v[a:t + 1] < ctx.vma5[a:t + 1] * 1.2):
        to = q.get("turnover") if q else None
        if to is not None and to < 3:
            pen += 10
            flags.append("近两周缩量阴跌（换手 %.1f%%）" % to)
    if q and q.get("pe") is not None and q["pe"] < 0:
        flags.append("亏损股（市盈率为负），注意业绩暴雷风险")
    return pen, flags


def scan_one(args):
    code, name, fs, days, q = args
    rows = datastore.read(code)
    if len(rows) < 250:
        return [], []
    n = len(rows)
    look = max(days, 10)  # 共振：看最近 10 个交易日内命中了几种方法
    ts = list(range(n - look, n))
    try:
        ctx = engine.Ctx(code, q.get("name") or name if q else name, rows, fs, chip_days=range(n - look - 25, n))
    except Exception:  # noqa: BLE001
        return [], []
    if q and q.get("limit_up") and q.get("date") == rows[-1]["date"]:
        ctx.lu[-1] = ctx.c[-1] >= q["limit_up"] - 0.005  # 当日用交易所涨停价精确判定
    out = []
    for t in ts:
        for m, f in engine.DETECTORS.items():
            sig = f(ctx, t)
            if not sig:
                continue
            pen, flags = risk_flags(ctx, t, q)
            sig["score"] = max(0, sig["score"] - pen)
            sig["flags"] = flags
            sig["days_ago"] = n - 1 - t
            sig["last_close"] = round(float(ctx.c[-1]), 3)
            sig["chg_since"] = round((ctx.c[-1] / ctx.c[t] - 1) * 100, 2)
            sig["below_stop"] = bool(ctx.c[-1] < sig["stop"])
            if q:
                sig.update({"pe": q.get("pe"), "pb": q.get("pb"), "float_mv": q.get("float_mv"),
                            "turnover": q.get("turnover")})
            out.append(sig)
    for sig in out:
        others = sorted({o["method"] for o in out if o["method"] != sig["method"] and abs(o["t"] - sig["t"]) <= 10})
        sig["resonance"] = others
        if others:  # 回测显示“共振”并不提高收益，所以只提示、不加分
            sig["detail"] = sig["detail"] + ["共振：10 个交易日内还出现了 " + "、".join(others) + "（回测显示共振不提高胜率，仅供参考）"]
    out = [s for s in out if s["days_ago"] < days]
    for sig in out:
        sig.pop("t", None)
    # 假跌破观察名单：已翻回颈线、还没突破上颈线（突破那天才是买点）
    w = engine.podifan_watch(ctx, n - 1)
    watch = []
    if w:
        watch.append({"code": code, "name": ctx.name, "date": ctx.dates[w["t0"]], "neck": round(w["neck"], 3),
                      "upper": round(w["upper"], 3), "close": round(float(ctx.c[-1]), 3),
                      "to_upper": round((w["upper"] / ctx.c[-1] - 1) * 100, 2), "waited": int(n - 1 - w["t0"]),
                      "left": int(engine.P["pdf_wait"] - (n - 1 - w["t0"])), "dd": round(w["dd"] * 100, 1),
                      "pe": q.get("pe") if q else None})
    return out, watch


def run(update=True, days=3, exclude_loss=False, workers=None):
    t0 = time.time()
    uni = datastore.load_universe()
    if update:
        # 首次使用或首次下载中途被关闭：本地缺日K的股票先补齐近 5 年（已下载的不重下）
        missing = [u["code"] for u in uni if not os.path.exists(datastore.path(u["code"]))]
        if len(missing) > 50:
            print("本地缺少 %d 只股票的历史日K，开始下载近 5 年数据（首次约 10–25 分钟）…" % len(missing), flush=True)
            datastore.sync("update", codes=missing)
        # 本地日K只要缺了“上一个交易日”（哪怕只漏跑一天），就先补齐中间的日子；然后腾讯实时补当天
        sample = [datastore.read(u["code"]) for u in uni[:30] if os.path.exists(datastore.path(u["code"]))]
        last = max((r[-1]["date"] for r in sample if r), default="2000-01-01")
        try:
            tdays = datastore.trading_days()
        except Exception:  # noqa: BLE001
            tdays = []
        today = time.strftime("%Y-%m-%d", time.gmtime(time.time() + 8 * 3600))   # 北京时间，本机时区无关
        need = [d for d in tdays if d < today]
        prev = need[-1] if need else time.strftime("%Y-%m-%d", time.localtime(time.time() - 3 * 86400))
        if last < prev:
            print("本地日K停在 %s，上一个交易日是 %s，先补齐历史日K…" % (last, prev), flush=True)
            datastore.sync("update")
    quotes = datastore.topup_today([u["code"] for u in uni]) if update else datastore.load_quotes()
    jobs = [(u["code"], u["name"], u["float_shares"], days, quotes.get(u["code"])) for u in uni
            if os.path.exists(datastore.path(u["code"]))]
    sigs = []
    with Pool(workers or max(2, os.cpu_count() - 2)) as pool:
        watch = []
        for r, w in pool.imap_unordered(scan_one, jobs, chunksize=16):
            sigs += r
            watch += w
    watch.sort(key=lambda x: x["to_upper"])
    if exclude_loss:
        sigs = [s for s in sigs if not (s.get("pe") is not None and s["pe"] < 0)]
    # 大盘环境（沪深300ETF vs 20 日线）+ 每条信号是否属于“样本外检验通过”的组合
    import backtest
    reg = backtest.market_regime()
    rd = sorted(reg)
    regime = {"date": rd[-1], "above_ma20": reg[rd[-1]]}
    try:
        verdicts = {m: a.get("verdict") for m, a in json.load(open(SUMMARY, encoding="utf-8")).get("alpha", {}).items()}
    except Exception:  # noqa: BLE001
        verdicts = {}
    for s in sigs:
        v = verdicts.get(s["method"], "")
        on = reg.get(s["date"], False)
        if v.startswith("有效（需大盘"):
            s["validated"] = bool(on)
            s["validation_note"] = "大盘在20日线上，属于回测验证有效的组合" if on else "大盘在20日线下，该方法此时历史上跑输大盘"
        elif v == "有效":
            s["validated"], s["validation_note"] = True, "回测验证有效"
        else:
            s["validated"] = False
            s["validation_note"] = "该方法未通过样本外检验（%s），仅供参考" % (v or "无回测")
        if s["validated"]:
            s["score"] = min(100, s["score"] + 10)
    sigs.sort(key=lambda s: (s["days_ago"], not s["validated"], -s["score"]))
    latest = max((datastore.read(u["code"])[-1]["date"] for u in uni[:50]
                  if os.path.exists(datastore.path(u["code"]))), default="")
    try:
        bt = json.load(open(SUMMARY, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        bt = None
    qtime = max((x.get("date", "") + " " + x.get("time", "") for x in quotes.values()), default="")
    res = {"generated": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time() + 8 * 3600)), "data_date": latest,
           "quote_time": "%s %s:%s" % (qtime[:10], qtime[11:13], qtime[13:15]) if len(qtime) >= 15 else "", "days": days,
           "stocks": len(jobs), "count": len(sigs), "signals": sigs, "watch": watch, "regime": regime, "backtest": bt, "params": engine.P,
           "seconds": round(time.time() - t0)}
    json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    by = {}
    for s in sigs:
        if s["days_ago"] == 0:
            by[s["method"]] = by.get(s["method"], 0) + 1
    print("扫描完成：%d 只股票，数据日期 %s，近 %d 日信号 %d 个（当日 %s），用时 %ds"
          % (len(jobs), latest, days, len(sigs), by, res["seconds"]), flush=True)
    return res


if __name__ == "__main__":
    run(update="--no-update" not in sys.argv,
        days=int(sys.argv[sys.argv.index("--days") + 1]) if "--days" in sys.argv else 3)
    if "--no-save" not in sys.argv:   # 每次扫描完自动存进本地数据库，并更新之前选股的后续表现
        try:
            sys.path.insert(0, os.path.dirname(HERE))
            from journal import tracker
            r = tracker.save_screener(OUT)
            print("已存入数据库：%d 条（%s）" % (r["saved"], "、".join(r["dates"])), flush=True)
            tracker.evaluate(log=lambda m: print(m, flush=True))
        except Exception as e:  # noqa: BLE001
            print("存入数据库失败：%s" % e, flush=True)
