# -*- coding: utf-8 -*-
"""演示打码：录制宣传视频时隐藏具体股票（DEMO_MASK=1 启动服务即生效）。
· 有 code + name 的对象（个股）：代码 600519 → 60****，美股 AAPL → A***，名称 → “股票·XX”（同一只股票始终同一个化名）
· 文本里出现的 A 股股票名称（复盘原因、快讯标题、摘要等）同样替换
· 指数、板块、商品、外围市场不打码"""
import hashlib
import json
import os
import re

BASE = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
_names = {}
_rx = None
STOCK_CODE = re.compile(r"^(?:(?:sh|sz|bj)?\d{6}|[A-Z]{1,5}(?:\.[A-Z]{1,2})?)$")


def alias(name):
    h = int(hashlib.md5(name.encode("utf-8")).hexdigest(), 16)
    a = "ABCDEFGHJKLMNPQRSTUVWXYZ"
    return "股票·" + a[h % 24] + a[(h // 24) % 24]


_codes, _back = {}, {}


def mask_code(c):
    """唯一化名代码（可还原）：600519 → 60**QK，AAPL → A**QK。"""
    if c in _codes:
        return _codes[c]
    if c in _back:          # 已经是化名
        return c
    m = re.match(r"^(sh|sz|bj)?(\d{6})$", c)
    head = ((m.group(1) or "") + m.group(2)[:2]) if m else c[:1]
    a = "ABCDEFGHJKLMNPQRSTUVWXYZ"
    h = int(hashlib.md5(c.encode()).hexdigest(), 16)
    k = 2
    while True:
        tail = "".join(a[(h // 24 ** i) % 24] for i in range(k))
        x = head + "**" + tail
        if x not in _back:
            break
        k += 1
    _codes[c], _back[x] = x, c
    return x


def unmask_code(x):
    return _back.get(x, x)


def _load():
    global _rx
    if _rx is not None:
        return
    for p in ("screener/cache/universe.json", "screener/cache/quotes.json"):
        try:
            d = json.load(open(os.path.join(BASE, p), encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        for x in (d if isinstance(d, list) else d.values()):
            n = (x.get("name") or "").strip()
            if len(n) >= 2:
                _names[n] = alias(n)
    _build()


def _build():
    global _rx
    ks = sorted(_names, key=len, reverse=True)
    _rx = re.compile("|".join(map(re.escape, ks))) if ks else re.compile(r"(?!x)x")


def _collect(o):
    """先扫一遍对象，把 code+name 成对出现的个股名字加入替换表（覆盖 ST、新股、美股）。"""
    added = False
    if isinstance(o, dict):
        c, n = o.get("code"), o.get("name")
        if isinstance(c, str) and isinstance(n, str) and STOCK_CODE.match(c) and len(n) >= 2 and n not in _names:
            if re.match(r"^\d|^(sh|sz|bj)\d", c):      # A 股名字也替换文本里的出现；美股只替换配对字段
                _names[n] = alias(n)
                added = True
        for v in o.values():
            added |= _collect(v)
    elif isinstance(o, list):
        for v in o:
            added |= _collect(v)
    return added


def _walk(o):
    if isinstance(o, dict):
        out = {}
        c = o.get("code")
        is_stock = isinstance(c, str) and STOCK_CODE.match(c) and isinstance(o.get("name"), str)
        for k, v in o.items():
            if is_stock and k == "code":
                out[k] = mask_code(v)
            elif is_stock and k == "name":
                out[k] = _names.get(v) or alias(v)
            else:
                out[k] = _walk(v)
        return out
    if isinstance(o, list):
        return [_walk(v) for v in o]
    if isinstance(o, str) and len(o) >= 2:
        o = o.replace(HOME, "~")
        return _rx.sub(lambda m: _names[m.group(0)], o)
    return o


def mask(obj):
    _load()
    if _collect(obj):
        _build()
    return _walk(obj)


def enabled():
    return os.environ.get("DEMO_MASK") == "1"
