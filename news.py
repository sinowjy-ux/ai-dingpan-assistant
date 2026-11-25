# -*- coding: utf-8 -*-
"""新闻：Google News RSS（仅取标题、来源、时间与链接）。公司新闻近 30 天，行业政策近 60 天，各最多 3 条。"""
import email.utils
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

LANG = {"zh": "hl=zh-CN&gl=CN&ceid=CN:zh-Hans", "en": "hl=en-US&gl=US&ceid=US:en"}
# 行情页、股吧页等非新闻条目
NOISE = re.compile(r"股价行情|股票股价|Stock Price Today|Quote|Quotes & News|股吧|行情走势|实时行情|Stock Price &|stock price, news", re.I)
POLICY_WORDS = re.compile(
    r"政策|监管|国务院|发改委|工信部|商务部|财政部|证监会|央行|金融监管|部门|规定|办法|意见|通知|补贴|关税|出口管制|新规|征求意见|"
    r"policy|regulat|rule|tariff|export control|FDA|SEC|Federal Reserve|bill|law|ban|antitrust|sanction", re.I)
_CACHE = {}


def _rss(query, lang):
    key = (query, lang)
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < 1800:
        return hit[1]
    url = "https://news.google.com/rss/search?q=%s&%s" % (urllib.parse.quote(query), LANG[lang])
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=12) as r:
        root = ET.fromstring(r.read())
    items = []
    for it in root.findall("./channel/item"):
        title = (it.findtext("title") or "").strip()
        src = (it.findtext("source") or "").strip()
        if src and title.endswith(" - " + src):
            title = title[: -len(src) - 3].strip()
        try:
            ts = email.utils.parsedate_to_datetime(it.findtext("pubDate")).timestamp()
        except Exception:  # noqa: BLE001
            ts = 0
        link = (it.findtext("link") or "").strip()
        if not link.startswith("https://"):
            link = ""
        items.append({"title": title, "source": src, "ts": ts, "link": link})
    _CACHE[key] = (time.time(), items)
    return items


def _dedupe(items):
    seen, out = [], []
    for it in items:
        k = re.sub(r"\W", "", it["title"])[:18]
        if k in seen:
            continue
        seen.append(k)
        out.append(it)
    return out


def _fmt(items):
    return [{"title": i["title"], "source": i["source"], "link": i["link"],
             "date": time.strftime("%Y-%m-%d", time.localtime(i["ts"])) if i["ts"] else ""} for i in items]


def company_news(name, code, lang, n=3):
    q = ('"%s" stock when:30d' % name) if lang == "en" else ("%s when:30d" % name)
    items = [i for i in _rss(q, lang) if not NOISE.search(i["title"])]
    # 标题须提到公司名或代码，避免泛泛的市场新闻
    keys = [k.lower() for k in (name, code) if k]
    rel = [i for i in items if any(k in i["title"].lower() for k in keys)] or items
    rel.sort(key=lambda i: -i["ts"])
    return _fmt(_dedupe(rel)[:n])


def policy_news(policy_query, lang, n=3):
    items = [i for i in _rss(policy_query + " when:60d", lang) if not NOISE.search(i["title"])]
    for i in items:
        i["hits"] = len(POLICY_WORDS.findall(i["title"]))
    # 先看政策相关度，再看时间；政策条目不足 3 条时用行业动态补足，并分别标注
    items.sort(key=lambda i: (-min(i["hits"], 2), -i["ts"]))
    out = _fmt(_dedupe(items)[:n])
    for o, i in zip(out, _dedupe(items)[:n]):
        o["kind"] = "政策" if i["hits"] else "行业动态"
    return out


def chinese_name(items, code):
    """从新闻标题中提取中文简称，如 “中国神华（601088）” → 中国神华"""
    pat = re.compile(r"([一-龥A-Za-z]{2,8})\s*[（(]\s*0*%s" % re.escape(code.lstrip("0")))
    for it in items:
        m = pat.search(it["title"])
        if m:
            return m.group(1)
    return None
