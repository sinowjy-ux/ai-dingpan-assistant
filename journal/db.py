# -*- coding: utf-8 -*-
"""本地数据库（SQLite，单文件 ~/stock_platform/data/journal.db）。
表：
  picks      每日筛选结果（主力选股 / AI 盯盘命中），一条 = 某天某只股票被某个方法选中
  perf       picks 的后续表现（比对）：T+1/T+3/T+5 收益、同期大盘、最大涨幅/回撤、是否破止损
  favorites  收藏
  reviews    每日复盘（JSON 全文 + 一段摘要）
  runs       每次保存的记录（来源、条数、时间）
所有日期都是交易所当地日期（A股=北京，美股=纽约）。"""
import json
import os
import sqlite3
import threading
import time
from datetime import date as Date, datetime, timedelta, timezone

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.environ.get("JOURNAL_DB") or os.path.join(BASE, "data", "journal.db")
_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS picks(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL,            -- screener | monitor
  market TEXT NOT NULL,            -- cn | us
  pool TEXT DEFAULT '',            -- 盯盘：1500/3000/全市场
  date TEXT NOT NULL,              -- 信号日
  time TEXT DEFAULT '',            -- 盯盘：触发时间 HH:MM
  code TEXT NOT NULL, name TEXT,
  method TEXT NOT NULL,            -- 选股方法 / 盯盘战法
  grade TEXT DEFAULT '', score REAL,
  price REAL,                      -- 信号价（选股=信号日收盘；盯盘=触发价）
  stop REAL, validated INTEGER DEFAULT 0, note TEXT DEFAULT '',
  detail TEXT DEFAULT '{}', saved_at TEXT,
  UNIQUE(source, market, date, code, method)
);
CREATE INDEX IF NOT EXISTS picks_date ON picks(date);
CREATE TABLE IF NOT EXISTS perf(
  pick_id INTEGER PRIMARY KEY REFERENCES picks(id) ON DELETE CASCADE,
  days INTEGER DEFAULT 0,          -- 已经过了几个交易日（最多跟踪 10 天）
  last_date TEXT,                  -- 最近一次比对用到的交易日
  r0 REAL,                         -- 盯盘：触发价 → 当日收盘
  r1 REAL, r3 REAL, r5 REAL, r10 REAL,  -- 信号价 → T+n 收盘（%）
  b1 REAL, b3 REAL, b5 REAL, b10 REAL,  -- 同期大盘（沪深300 / 标普500）
  max5 REAL, min5 REAL,            -- T+1..T+5 最高价/最低价相对信号价
  stop_hit INTEGER DEFAULT 0,      -- 5 天内收盘跌破止损
  updated TEXT
);
CREATE TABLE IF NOT EXISTS favorites(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT, market TEXT, date TEXT, code TEXT, name TEXT, method TEXT DEFAULT '',
  price REAL, note TEXT DEFAULT '', detail TEXT DEFAULT '{}', created TEXT,
  UNIQUE(source, market, date, code, method)
);
CREATE TABLE IF NOT EXISTS reviews(
  date TEXT PRIMARY KEY, kind TEXT, created TEXT, summary TEXT, data TEXT
);
CREATE TABLE IF NOT EXISTS analyses(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created TEXT, date TEXT,                 -- 研判时间（北京时间）
  code TEXT, market TEXT, name TEXT,
  price REAL, chg REAL, rating TEXT, score REAL,
  buy_lo REAL, buy_hi REAL, stop REAL, target REAL, rr REAL,
  summary TEXT, params TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS analyses_date ON analyses(date);
CREATE TABLE IF NOT EXISTS runs(
  id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT, market TEXT, pool TEXT, date TEXT,
  count INTEGER, created TEXT, info TEXT DEFAULT ''
);
"""


def bj_now():
    return datetime.now(timezone(timedelta(hours=8)))


def stamp():
    return bj_now().strftime("%Y-%m-%d %H:%M:%S")


def conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("PRAGMA journal_mode=WAL")
    c.executescript(SCHEMA)
    return c


def rows(sql, args=()):
    with _lock:
        c = conn()
        try:
            return [dict(r) for r in c.execute(sql, args).fetchall()]
        finally:
            c.close()


def execute(sql, args=(), many=False):
    with _lock:
        c = conn()
        try:
            cur = c.executemany(sql, args) if many else c.execute(sql, args)
            c.commit()
            return cur.rowcount
        finally:
            c.close()


# ---------------- 写入 ----------------

def save_picks(items, source, market, pool="", info=""):
    """items: [{date,time,code,name,method,grade,score,price,stop,validated,note,detail}]；同一天同股同方法覆盖更新。"""
    now = stamp()
    vals = [(source, market, str(pool), x["date"], x.get("time", ""), x["code"], x.get("name", ""), x["method"],
             x.get("grade", ""), x.get("score"), x.get("price"), x.get("stop"), int(bool(x.get("validated"))),
             x.get("note", ""), json.dumps(x.get("detail", {}), ensure_ascii=False), now) for x in items]
    with _lock:
        c = conn()
        try:
            c.executemany("""INSERT INTO picks(source,market,pool,date,time,code,name,method,grade,score,price,stop,
                             validated,note,detail,saved_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                             ON CONFLICT(source,market,date,code,method) DO UPDATE SET
                             pool=excluded.pool,time=excluded.time,name=excluded.name,grade=excluded.grade,
                             score=excluded.score,price=excluded.price,stop=excluded.stop,
                             validated=excluded.validated,note=excluded.note,detail=excluded.detail,
                             saved_at=excluded.saved_at""", vals)
            for d in sorted({x["date"] for x in items}):
                c.execute("INSERT INTO runs(source,market,pool,date,count,created,info) VALUES(?,?,?,?,?,?,?)",
                          (source, market, str(pool), d, sum(1 for x in items if x["date"] == d), now, info))
            c.commit()
        finally:
            c.close()
    return len(vals)


def set_favorite(item, on=True):
    key = (item.get("source", ""), item.get("market", "cn"), item.get("date", ""), item["code"], item.get("method", ""))
    if not on:
        return execute("DELETE FROM favorites WHERE source=? AND market=? AND date=? AND code=? AND method=?", key)
    return execute("""INSERT OR REPLACE INTO favorites(source,market,date,code,name,method,price,note,detail,created)
                      VALUES(?,?,?,?,?,?,?,?,?,?)""",
                   key[:4] + (item.get("name", ""), key[4], item.get("price"), item.get("note", ""),
                              json.dumps(item.get("detail", {}), ensure_ascii=False), stamp()))


def save_review(date, kind, summary, data):
    return execute("INSERT OR REPLACE INTO reviews(date,kind,created,summary,data) VALUES(?,?,?,?,?)",
                   (date, kind, stamp(), summary, json.dumps(data, ensure_ascii=False)))


def save_analysis(d, params):
    """个股研判成功后存一条记录（谁输入了什么、当时的结论）。"""
    m, c, z, sm = d.get("meta", {}), d.get("composite", {}), d.get("sizing", {}), d.get("summary", {})
    now = stamp()
    bz = c.get("buy_zone") or [None, None]
    return execute("""INSERT INTO analyses(created,date,code,market,name,price,chg,rating,score,buy_lo,buy_hi,stop,target,rr,summary,params)
                      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                   (now, now[:10], m.get("code"), m.get("market"), m.get("cn_name") or m.get("name"), m.get("price"), m.get("chg"),
                    c.get("rating"), c.get("score"), bz[0], bz[1], c.get("stop"), z.get("target"), z.get("rr"),
                    sm.get("text", ""), json.dumps(params, ensure_ascii=False)))


def analyses(limit=100, date=None, code=None):
    cond, args = ["1=1"], []
    if date:
        cond.append("date=?"); args.append(date)
    if code:
        cond.append("code=?"); args.append(code)
    return rows("SELECT * FROM analyses WHERE %s ORDER BY id DESC LIMIT %d" % (" AND ".join(cond), int(limit)), args)


def get_review(date=None):
    r = rows("SELECT * FROM reviews WHERE date=?", (date,)) if date else \
        rows("SELECT * FROM reviews ORDER BY date DESC LIMIT 1")
    if not r:
        return None
    r = r[0]
    r["data"] = json.loads(r["data"] or "{}")
    return r


# ---------------- 查询 ----------------

def _pick_out(r):
    r = dict(r)
    try:
        r["detail"] = json.loads(r.get("detail") or "{}")
    except ValueError:
        r["detail"] = {}
    r["validated"] = bool(r.get("validated"))
    return r


def day(date):
    picks = rows("""SELECT p.*, f.days, f.r0, f.r1, f.r3, f.r5, f.r10, f.b1, f.b3, f.b5, f.max5, f.min5, f.stop_hit,
                    f.last_date, (SELECT COUNT(*) FROM favorites v WHERE v.source=p.source AND v.market=p.market
                    AND v.date=p.date AND v.code=p.code AND v.method=p.method) AS fav
                    FROM picks p LEFT JOIN perf f ON f.pick_id=p.id WHERE p.date=?
                    ORDER BY p.source, p.validated DESC, p.score DESC""", (date,))
    rv = rows("SELECT date,kind,created,summary FROM reviews WHERE date=?", (date,))
    favs = rows("SELECT * FROM favorites WHERE date=? ORDER BY created DESC", (date,))
    return {"date": date, "picks": [_pick_out(p) for p in picks], "review": rv[0] if rv else None,
            "favorites": favs, "methods": method_stats(date, date), "analyses": analyses(200, date)}


def dates(limit=400):
    """每个有数据的日期及各类条数（统计页日历）。"""
    out = {}
    for r in rows("SELECT date, source, COUNT(*) n FROM picks GROUP BY date, source"):
        out.setdefault(r["date"], {"date": r["date"], "screener": 0, "monitor": 0, "review": False, "favorites": 0})[r["source"]] = r["n"]
    for r in rows("SELECT date, kind FROM reviews"):
        out.setdefault(r["date"], {"date": r["date"], "screener": 0, "monitor": 0, "review": False, "favorites": 0})["review"] = r["kind"]
    for r in rows("SELECT date, COUNT(*) n FROM favorites GROUP BY date"):
        out.setdefault(r["date"], {"date": r["date"], "screener": 0, "monitor": 0, "review": False, "favorites": 0})["favorites"] = r["n"]
    for r in rows("SELECT date, COUNT(*) n FROM analyses GROUP BY date"):
        out.setdefault(r["date"], {"date": r["date"], "screener": 0, "monitor": 0, "review": False, "favorites": 0})["stock"] = r["n"]
    for v in out.values():
        v.setdefault("stock", 0)
    return sorted(out.values(), key=lambda x: x["date"], reverse=True)[:limit]


def method_stats(d0=None, d1=None, source=None):
    """各方法的实盘跟踪统计（样本外）：平均收益、胜率、超额、破止损率。"""
    cond, args = ["1=1"], []
    if d0:
        cond.append("p.date>=?")
        args.append(d0)
    if d1:
        cond.append("p.date<=?")
        args.append(d1)
    if source:
        cond.append("p.source=?")
        args.append(source)
    rs = rows("""SELECT p.source, p.market, p.method, p.validated, p.grade, f.r0, f.r1, f.r3, f.r5, f.b1, f.b3, f.b5, f.stop_hit, f.days
                 FROM picks p LEFT JOIN perf f ON f.pick_id=p.id WHERE %s""" % " AND ".join(cond), args)
    groups = {}
    for r in rs:
        tier = (("命中" if r["validated"] else "剔除") if r["source"] == "monitor"
                else ("已验证" if r["validated"] else "未验证"))
        groups.setdefault((r["source"], r["market"], r["method"], tier), []).append(r)
    out = []
    for (src, mk, m, tier), g in groups.items():
        o = {"source": src, "market": mk, "method": m, "tier": tier, "n": len(g),
             "validated": sum(1 for x in g if x["validated"])}
        for h in ("1", "3", "5"):
            xs = [(x["r" + h], x["b" + h]) for x in g if x["r" + h] is not None]
            o["n" + h] = len(xs)
            if xs:
                o["r" + h] = round(sum(a for a, _ in xs) / len(xs), 2)
                srt = sorted(a for a, _ in xs)
                o["med" + h] = round(srt[len(srt) // 2] if len(srt) % 2 else (srt[len(srt) // 2 - 1] + srt[len(srt) // 2]) / 2, 2)
                o["win" + h] = round(100 * sum(1 for a, _ in xs if a > 0) / len(xs), 1)
                ex = [a - b for a, b in xs if b is not None]
                o["ex" + h] = round(sum(ex) / len(ex), 2) if ex else None
                o["beat" + h] = round(100 * sum(1 for e in ex if e > 0) / len(ex), 1) if ex else None
        r0 = [x["r0"] for x in g if x["r0"] is not None]
        if r0:
            o["r0"] = round(sum(r0) / len(r0), 2)
            o["win0"] = round(100 * sum(1 for a in r0 if a > 0) / len(r0), 1)
        done = [x for x in g if (x["days"] or 0) >= 5]
        o["stop_rate"] = round(100 * sum(1 for x in done if x["stop_hit"]) / len(done), 1) if done else None
        out.append(o)
    out.sort(key=lambda o: (o["source"] != "screener", o["market"], o["method"], o["tier"]))
    return out


def summary():
    c = {k: rows("SELECT COUNT(*) n FROM %s" % k)[0]["n"] for k in ("picks", "favorites", "reviews", "analyses")}
    span = rows("SELECT MIN(date) a, MAX(date) b, COUNT(DISTINCT date) d FROM picks")[0]
    tracked = rows("SELECT COUNT(*) n FROM perf WHERE r1 IS NOT NULL")[0]["n"]
    size = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
    favs = rows("""SELECT v.*, f.r1, f.r3, f.r5, f.days FROM favorites v LEFT JOIN picks p ON p.source=v.source AND
                   p.market=v.market AND p.date=v.date AND p.code=v.code AND p.method=v.method
                   LEFT JOIN perf f ON f.pick_id=p.id ORDER BY v.created DESC LIMIT 200""")
    return {"counts": c, "first": span["a"], "last": span["b"], "days": span["d"], "tracked": tracked,
            "db_path": DB_PATH, "db_size": size, "dates": dates(), "methods": method_stats(),
            "favorites": favs, "now": stamp()}


# ---------------- 删除 ----------------

def period(unit, value):
    """unit=day|week|month|year → (起, 止)。week 的 value 可以是该周任意一天；也支持 before=YYYY-MM-DD。"""
    if unit == "day":
        return value, value
    if unit == "week":
        d = Date.fromisoformat(value)
        a = d - timedelta(days=d.weekday())
        return a.isoformat(), (a + timedelta(days=6)).isoformat()
    if unit == "month":
        y, m = int(value[:4]), int(value[5:7])
        nxt = Date(y + (m == 12), m % 12 + 1, 1)
        return "%04d-%02d-01" % (y, m), (nxt - timedelta(days=1)).isoformat()
    if unit == "year":
        return value[:4] + "-01-01", value[:4] + "-12-31"
    if unit == "before":
        return "0000-01-01", (Date.fromisoformat(value) - timedelta(days=1)).isoformat()
    raise ValueError("unit 只能是 day/week/month/year/before")


TABLES = {"picks": "picks", "reviews": "reviews", "favorites": "favorites", "analyses": "analyses"}


def count_range(a, b, what=("picks", "reviews", "favorites", "analyses")):
    return {t: rows("SELECT COUNT(*) n FROM %s WHERE date BETWEEN ? AND ?" % TABLES[t], (a, b))[0]["n"] for t in what}


def delete_range(a, b, what=("picks", "reviews", "favorites", "analyses")):
    before = count_range(a, b, what)
    with _lock:
        c = conn()
        try:
            for t in what:
                if t == "picks":
                    c.execute("DELETE FROM perf WHERE pick_id IN (SELECT id FROM picks WHERE date BETWEEN ? AND ?)", (a, b))
                    c.execute("DELETE FROM runs WHERE date BETWEEN ? AND ?", (a, b))
                c.execute("DELETE FROM %s WHERE date BETWEEN ? AND ?" % TABLES[t], (a, b))
            c.commit()
            c.execute("VACUUM")
        finally:
            c.close()
    return before


if __name__ == "__main__":
    print(json.dumps({k: v for k, v in summary().items() if k != "dates"}, ensure_ascii=False, indent=1)[:2000])
