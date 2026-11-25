# -*- coding: utf-8 -*-
"""本地服务：python3 server.py 后打开 http://127.0.0.1:8765"""
import json
import os
import sys
import traceback
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if sys.stdout is None or sys.stderr is None:
    # Windows 用 pythonw 启动（无控制台）时没有标准输出，写访问日志会出错导致每个请求都断开；改写到 data/server.log
    os.makedirs(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"), exist_ok=True)
    _logf = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "server.log"), "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stdout or _logf
    sys.stderr = sys.stderr or _logf
import analysis  # noqa: E402
import demo_mask  # noqa: E402
import subprocess  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
SCAN_OUT = os.path.join(BASE, "screener", "cache", "scan_latest.json")
SCAN_LOG = os.path.join(BASE, "screener", "cache", "scan_run.log")
USER_FILE = os.path.join(BASE, "user_data.json")
_user_lock = threading.Lock()
_scan = {"proc": None, "started": None}


def load_user():
    try:
        with open(USER_FILE, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    d.setdefault("recent", [])
    d.setdefault("watchlist", [])
    return d


def save_user(d):
    tmp = USER_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, USER_FILE)


def same(a, b):
    return a.get("code", "").upper() == b.get("code", "").upper() and a.get("market") == b.get("market")
_scan_lock = threading.Lock()


def scan_status():
    p = _scan["proc"]
    running = p is not None and p.poll() is None
    log = ""
    try:
        log = open(SCAN_LOG, encoding="utf-8").read()[-1500:]
    except OSError:
        pass
    return {"running": running, "started": _scan["started"], "exit": None if (p is None or running) else p.returncode,
            "log": log}


def start_scan():
    with _scan_lock:
        if _scan["proc"] is not None and _scan["proc"].poll() is None:
            return False
        logf = open(SCAN_LOG, "w", encoding="utf-8")
        _scan["proc"] = subprocess.Popen([sys.executable, "-u", os.path.join(BASE, "screener", "scan.py")],
                                         stdout=logf, stderr=subprocess.STDOUT, cwd=os.path.join(BASE, "screener"))
        _scan["started"] = time.strftime("%H:%M:%S")
        return True

_review = {"running": False, "log": [], "started": None}
_eval = {"running": False}


def start_review():
    """后台生成当天复盘（约 1 分钟），完成后存进数据库。"""
    if _review["running"]:
        return False
    _review.update(running=True, log=[], started=time.strftime("%H:%M:%S"))

    def run():
        try:
            from journal import review
            review.build(log=lambda m: _review["log"].append(m))
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            _review["log"].append("复盘失败：%s" % e)
        finally:
            _review["running"] = False
    threading.Thread(target=run, daemon=True).start()
    return True


def run_eval():
    if _eval["running"]:
        return
    _eval["running"] = True
    try:
        from journal import tracker
        tracker.evaluate(log=lambda m: None)
    except Exception:  # noqa: BLE001
        traceback.print_exc()
    finally:
        _eval["running"] = False


def init_status():
    """首次使用：本地还没有历史日K时，返回提示（统计页显示）。"""
    kdir = os.path.join(BASE, "screener", "cache", "klines")
    n = len([f for f in os.listdir(kdir) if f.endswith(".csv")]) if os.path.isdir(kdir) else 0
    st = scan_status()
    return {"klines": n, "ready": n >= 3000, "scanning": st["running"], "log": st["log"][-400:]}


def scheduler():
    """App/服务开着时自动做的事（北京时间）：
    · 09:00–09:25 生成盘前复盘（外围市场）；15:35 以后生成收盘复盘（每个交易日各一次）
    · 收盘后、美股收盘后各做一次比对；AI 盯盘实盘运行时每分钟把信号存进数据库"""
    from journal import db
    done, saved = set(), {}
    last_init = 0.0
    while True:
        try:
            now = db.bj_now()
            hm, today = now.hour * 100 + now.minute, now.strftime("%Y-%m-%d")
            if now.weekday() < 5:
                rv = db.rows("SELECT kind FROM reviews WHERE date=?", (today,))
                kind = rv[0]["kind"] if rv else None
                if 900 <= hm < 925 and kind is None and ("pre", today) not in done:
                    done.add(("pre", today))
                    start_review()
                if hm >= 1535 and kind != "收盘" and ("close", today) not in done:
                    done.add(("close", today))
                    start_review()
            if hm >= 1540 and ("eval_cn", today) not in done:
                done.add(("eval_cn", today))
                threading.Thread(target=run_eval, daemon=True).start()
            if 530 <= hm < 600 and ("eval_us", today) not in done:
                done.add(("eval_us", today))
                threading.Thread(target=run_eval, daemon=True).start()
            # 首次使用（或首次下载被中断）：历史日K不全且没在下载，就自动开始；失败后每 10 分钟重试
            if time.time() - last_init > 600:
                st = init_status()
                if not st["ready"] and not st["scanning"]:
                    last_init = time.time()
                    start_scan()
            from monitor import service as M
            from journal import tracker
            for mk, live in M.LIVES.items():
                key = (mk, live.date, len(live.signals))
                if live.date and live.signals and saved.get(mk) != key:
                    tracker.save_live_hits(mk, live.n, live.date, list(live.signals))
                    saved[mk] = key
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        time.sleep(60)


STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
try:
    APP_VERSION = json.load(open(os.path.join(BASE, "VERSION.json"), encoding="utf-8"))
except (OSError, ValueError):
    APP_VERSION = {"version": "dev", "channel": "开发版", "build": "", "short": "开发版"}
PORT = int(os.environ.get("PORT", 8765))


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=STATIC, **kw)

    def end_headers(self):
        # 页面和脚本每次都向后台确认是否有新版本（没变时返回 304，仍用缓存），升级后不会继续用旧脚本
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    def _json(self, code, obj):
        if demo_mask.enabled():
            obj = demo_mask.mask(obj)
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _unmask_path(self):
        """演示打码时，前端传回来的化名代码换回真实代码。"""
        if not demo_mask.enabled() or "?" not in self.path:
            return
        p, q = self.path.split("?", 1)
        qs = urllib.parse.parse_qsl(q, keep_blank_values=True)
        qs = [(k, demo_mask.unmask_code(v) if k == "code" else v) for k, v in qs]
        self.path = p + "?" + urllib.parse.urlencode(qs)

    def do_GET(self):
        self._unmask_path()
        u = urllib.parse.urlparse(self.path)
        if u.path == "/api/screener" and demo_mask.enabled():
            try:
                return self._json(200, json.load(open(SCAN_OUT, encoding="utf-8")))
            except OSError:
                return self._json(404, {"error": "还没有扫描结果，请点击“更新行情并扫描”"})
        if u.path == "/api/screener":
            try:
                with open(SCAN_OUT, "rb") as f:
                    body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except OSError:
                self._json(404, {"error": "还没有扫描结果，请点击“更新行情并扫描”"})
            return
        if u.path == "/api/screener/run":
            started = start_scan()
            return self._json(200, {"started": started, **scan_status()})
        if u.path == "/api/screener/status":
            return self._json(200, scan_status())
        if u.path == "/api/version":
            return self._json(200, APP_VERSION)
        if u.path.startswith("/api/monitor/"):
            return self._monitor(u)
        if u.path.startswith("/api/db/") or u.path.startswith("/api/review"):
            return self._journal(u, {})
        if u.path == "/api/user":
            return self._json(200, load_user())
        if u.path == "/api/quotes":
            import data as D
            q = urllib.parse.parse_qs(u.query).get("items", [""])[0]
            out = {}
            for it in [x for x in q.split(",") if ":" in x][:60]:
                code, market = it.split(":", 1)
                sym = D.tencent_symbol(code, market)
                r = D.tencent_quote(sym) if sym else None
                if r:
                    b = r["bar"]
                    out[it] = {"name": r["name"], "price": b["close"], "date": b["date"], "time": r["time"],
                               "chg": round((b["close"] / r["prev_close"] - 1) * 100, 2) if r["prev_close"] else None}
            return self._json(200, out)
        if u.path != "/api/analyze":
            return super().do_GET()
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        try:
            res = analysis.run(
                q.get("code", "").strip(), q.get("market", "A股"),
                capital=float(q.get("capital", 100000)), risk_pct=float(q.get("risk", 1)),
                max_pos_pct=float(q.get("maxpos", 20)), lot=q.get("lot") or None,
                peers_str=q.get("peers", ""), as_of=(q.get("asof") or "").strip() or None)
            try:     # 每次研判都存一条记录（统计页可按天查询、删除）
                from journal import db
                db.save_analysis(res, {k: q.get(k, "") for k in ("capital", "risk", "maxpos", "lot", "peers", "asof")})
            except Exception:  # noqa: BLE001
                traceback.print_exc()
            self._json(200, res)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self._json(400, {"error": str(e)})


    def _monitor(self, u):
        """AI 盯盘接口（网页版与 Mac App 共用）。market=cn|us，n=1500|3000|0(全市场)；不传则为 A股 1500。"""
        from monitor import service as M
        E = M.engine
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        name = u.path[len("/api/monitor/"):]
        mk = q.get("market", "cn") if q.get("market") in ("cn", "us") else "cn"
        n = int(q.get("n", 1500))
        live = M.LIVES[mk]
        try:
            if name == "meta":
                snap = M.snapshot(mk, n)
                ds = M.datasets()
                j = M.job(mk, n)
                markets = {m: {"name": E.MARKETS[m]["name"], "index_name": E.MARKETS[m]["index_name"],
                               "minutes": E.minutes(m), "order": E.MARKETS[m]["order"], "cards": E.cards(m),
                               "time_ok": E.MARKETS[m]["time_ok"], "currency": E.MARKETS[m]["currency"],
                               "phase": M.trading_phase(market=m),
                               "local_time": M.now_local(m).strftime("%Y-%m-%d %H:%M:%S")} for m in ("cn", "us")}
                return self._json(200, {
                    "market": mk, "n": n, "markets": markets, "datasets": ds, "sizes": [0 if x == 0 else x for x in (1500, 3000, 0)],
                    "dates": snap.dates if snap else [], "built": snap.built if snap else None,
                    "stocks": len(snap.codes) - 1 if snap else 0, "building": j["building"],
                    "build_log": j["log"][-5:], "strategies": E.STRATS, "desc": E.STRAT_DESC,
                    "cards": E.cards(mk), "order": E.MARKETS[mk]["order"],
                    "phase": M.trading_phase(market=mk), "cn_time": M.now_local(mk).strftime("%Y-%m-%d %H:%M:%S")})
            if name == "refresh":
                return self._json(200, {"started": M.refresh_snapshot(mk, n)})
            if name == "replay":
                if not M.snapshot(mk, n):
                    return self._json(404, {"error": "这个组合还没有分时数据，请先点“下载数据”"})
                end = int(q.get("end", 1600 if mk == "us" else 1500))
                return self._json(200, M.replay(q["date"], int(q.get("start", 930)), end, mk, n))
            if name == "series":
                r = live.series(q["code"]) if q.get("live") else M.series(q["date"], q["code"], mk, n)
                return self._json(200 if r else 404, r or {"error": "没有这只股票的分时"})
            if name == "live/start":
                return self._json(200, {"started": live.start(n), **live.state(10 ** 9)})
            if name == "live/stop":
                live.stop()
                return self._json(200, live.state(10 ** 9))
            if name == "live/notify":
                live.notify = q.get("on") == "1"
                return self._json(200, {"notify": live.notify})
            if name == "live":
                return self._json(200, live.state(int(q.get("since", 0))))
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            return self._json(400, {"error": str(e)})
        return self._json(404, {"error": "未知接口"})

    def _journal(self, u, body):
        """数据库 / 复盘 / 比对接口。GET 用查询参数，POST 用 JSON。"""
        from journal import db, tracker
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        q.update(body or {})
        name = u.path[len("/api/"):]
        try:
            if name == "db/summary":
                return self._json(200, dict(db.summary(), init=init_status(), app=APP_VERSION))
            if name == "db/day":
                return self._json(200, db.day(q["date"]))
            if name == "db/methods":
                return self._json(200, {"methods": db.method_stats(q.get("from"), q.get("to"), q.get("source"))})
            if name == "db/save_screener":
                r = tracker.save_screener()
                threading.Thread(target=run_eval, daemon=True).start()
                return self._json(200, r)
            if name == "db/save_monitor":
                mk = q.get("market", "cn")
                r = tracker.save_monitor(q["date"], mk, int(q.get("n", 1500)))
                threading.Thread(target=run_eval, daemon=True).start()
                return self._json(200, r)
            if name == "db/evaluate":
                from journal import tracker as T
                return self._json(200, T.evaluate(log=lambda m: None))
            if name == "db/favorite":
                item = body.get("item") or q
                db.set_favorite(item, on=str(q.get("on", "1")) not in ("0", "false", "False"))
                return self._json(200, {"ok": True})
            if name == "db/analyses":
                return self._json(200, {"analyses": db.analyses(int(q.get("limit", 100)), q.get("date"), q.get("code"))})
            if name == "db/favorites":
                return self._json(200, {"favorites": db.summary()["favorites"]})
            if name in ("db/delete_preview", "db/delete"):
                a, b = db.period(q["unit"], q["value"])
                what = [w for w in (q.get("what") or "picks,reviews,favorites,analyses").split(",") if w in db.TABLES]
                if name == "db/delete_preview":
                    return self._json(200, {"from": a, "to": b, "counts": db.count_range(a, b, what)})
                if u.path and self.command != "POST":
                    return self._json(405, {"error": "删除请用 POST"})
                return self._json(200, {"from": a, "to": b, "deleted": db.delete_range(a, b, what)})
            if name == "review":
                r = db.get_review(q.get("date"))
                return self._json(200 if r else 404, r or {"error": "还没有复盘，请点“生成今日复盘”"})
            if name == "review/build":
                ok = start_review()
                return self._json(200, {**_review, "accepted": ok})
            if name == "review/status":
                return self._json(200, _review)
        except KeyError as e:
            return self._json(400, {"error": "缺少参数 %s" % e})
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            return self._json(400, {"error": str(e)})
        return self._json(404, {"error": "未知接口"})

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return self._json(400, {"error": "请求格式错误"})
        if demo_mask.enabled() and isinstance(body.get("item"), dict) and "code" in body["item"]:
            body["item"]["code"] = demo_mask.unmask_code(body["item"]["code"])
        if u.path == "/api/shutdown":
            if self.client_address[0] not in ("127.0.0.1", "::1"):
                return self._json(403, {"error": "只允许本机"})
            self._json(200, {"ok": True})
            threading.Thread(target=lambda: (time.sleep(0.3), os._exit(0)), daemon=True).start()
            return
        if u.path.startswith("/api/db/") or u.path.startswith("/api/review"):
            return self._journal(u, body)
        if u.path == "/api/user/recent/clear":
            with _user_lock:
                d = load_user()
                d["recent"] = []
                save_user(d)
            return self._json(200, d)
        keep = ("code", "market", "name", "capital", "risk", "maxpos", "lot", "peers", "asof")
        item = {k: str(body.get(k, ""))[:80] for k in keep}
        if not item["code"] or not item["market"]:
            return self._json(400, {"error": "缺少代码或市场"})
        with _user_lock:
            d = load_user()
            if u.path == "/api/user/recent":
                item["time"] = time.strftime("%Y-%m-%d %H:%M")
                d["recent"] = [item] + [x for x in d["recent"] if not same(x, item)]
                d["recent"] = d["recent"][:12]
            elif u.path == "/api/user/watch":
                if body.get("action") == "remove":
                    d["watchlist"] = [x for x in d["watchlist"] if not same(x, item)]
                elif not any(same(x, item) for x in d["watchlist"]):
                    item["added"] = time.strftime("%Y-%m-%d")
                    d["watchlist"].append({k: item[k] for k in ("code", "market", "name", "added")})
            else:
                return self._json(404, {"error": "未知接口"})
            save_user(d)
        return self._json(200, d)


if __name__ == "__main__":
    print("AI 盯盘助手 %s（%s，build %s）已启动：http://127.0.0.1:%d" % (
        APP_VERSION["version"], APP_VERSION["channel"], APP_VERSION["build"], PORT), flush=True)
    if os.environ.get("NO_SCHEDULER") != "1":
        threading.Thread(target=scheduler, daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
