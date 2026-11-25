# -*- coding: utf-8 -*-
"""内置同业分组（同一市场内），附行业名与新闻检索关键词。
未覆盖的股票请在页面“同业代码”中手动填写；新闻会改用代码/英文名与市场级政策检索。"""

# 每组：行业名、政策检索词（中文或英文）、成员 {代码: 名称}
GROUPS = {
    "A股": [
        {"ind": "白酒", "policy": "白酒 OR 酒业 政策 OR 监管 OR 消费税", "m": {"600519": "贵州茅台", "000858": "五粮液", "000568": "泸州老窖", "600809": "山西汾酒", "002304": "洋河股份"}},
        {"ind": "新能源车/动力电池", "policy": "新能源汽车 OR 动力电池 政策", "m": {"300750": "宁德时代", "002594": "比亚迪", "300014": "亿纬锂能", "002460": "赣锋锂业", "601633": "长城汽车", "002812": "恩捷股份"}},
        {"ind": "保险", "policy": "保险业 金融监管总局 政策", "m": {"601318": "中国平安", "601628": "中国人寿", "601601": "中国太保", "601336": "新华保险"}},
        {"ind": "银行", "policy": "银行业 金融监管总局 OR 央行 政策", "m": {"600036": "招商银行", "601166": "兴业银行", "000001": "平安银行", "601398": "工商银行", "601288": "农业银行", "601939": "建设银行"}},
        {"ind": "半导体", "policy": "半导体 OR 集成电路 政策", "m": {"688981": "中芯国际", "603501": "韦尔股份", "002371": "北方华创", "688012": "中微公司", "603986": "兆易创新"}},
        {"ind": "医药", "policy": "医药 OR 集采 OR 医保 政策", "m": {"600276": "恒瑞医药", "300760": "迈瑞医疗", "603259": "药明康德", "000538": "云南白药", "300015": "爱尔眼科"}},
        {"ind": "家电", "policy": "家电 以旧换新 政策", "m": {"000333": "美的集团", "000651": "格力电器", "600690": "海尔智家"}},
        {"ind": "电力", "policy": "电力 OR 电价 OR 能源局 政策", "m": {"600900": "长江电力", "601985": "中国核电", "600011": "华能国际", "003816": "中国广核"}},
        {"ind": "有色金属", "policy": "有色金属 OR 稀土 OR 铜 政策", "m": {"601899": "紫金矿业", "603993": "洛阳钼业", "600547": "山东黄金", "000878": "云南铜业"}},
        {"ind": "消费电子", "policy": "消费电子 OR 电子信息 政策", "m": {"002415": "海康威视", "000725": "京东方A", "002475": "立讯精密", "601138": "工业富联"}},
    ],
    "港股": [
        {"ind": "互联网平台", "policy": "平台经济 OR 互联网 监管 政策", "m": {"0700": "腾讯控股", "9988": "阿里巴巴", "3690": "美团", "1024": "快手", "9618": "京东集团", "9999": "网易", "1810": "小米集团"}},
        {"ind": "汽车", "policy": "新能源汽车 政策", "m": {"1211": "比亚迪股份", "2015": "理想汽车", "9868": "小鹏汽车", "9866": "蔚来", "2333": "长城汽车", "0175": "吉利汽车"}},
        {"ind": "银行", "policy": "银行业 监管 政策", "m": {"0005": "汇丰控股", "0939": "建设银行", "1398": "工商银行", "3988": "中国银行", "2388": "中银香港"}},
        {"ind": "保险", "policy": "保险业 监管 政策", "m": {"1299": "友邦保险", "2318": "中国平安", "2628": "中国人寿", "0966": "中国太平"}},
        {"ind": "交易所/金融科技", "policy": "港交所 OR 香港证监会 政策", "m": {"0388": "香港交易所", "6060": "众安在线"}},
        {"ind": "石油石化", "policy": "石油 OR 油气 政策", "m": {"0883": "中国海洋石油", "0857": "中国石油股份", "0386": "中国石油化工股份"}},
        {"ind": "电信", "policy": "电信 OR 通信 工信部 政策", "m": {"0941": "中国移动", "0762": "中国联通", "0728": "中国电信"}},
        {"ind": "医药", "policy": "创新药 OR 医保 政策", "m": {"2269": "药明生物", "1177": "中国生物制药", "1093": "石药集团", "6618": "京东健康"}},
    ],
    "US": [
        {"ind": "科技巨头", "policy": "big tech antitrust OR regulation", "m": {"AAPL": "Apple", "MSFT": "Microsoft", "GOOGL": "Alphabet", "AMZN": "Amazon", "META": "Meta Platforms"}},
        {"ind": "半导体", "policy": "semiconductor export controls OR chip policy", "m": {"NVDA": "Nvidia", "AMD": "AMD", "AVGO": "Broadcom", "INTC": "Intel", "QCOM": "Qualcomm", "TSM": "TSMC", "MU": "Micron"}},
        {"ind": "电动车", "policy": "EV tax credit OR electric vehicle policy", "m": {"TSLA": "Tesla", "RIVN": "Rivian", "LCID": "Lucid", "NIO": "NIO", "LI": "Li Auto", "XPEV": "XPeng", "GM": "General Motors", "F": "Ford"}},
        {"ind": "银行", "policy": "bank regulation Fed capital rules", "m": {"JPM": "JPMorgan", "BAC": "Bank of America", "WFC": "Wells Fargo", "C": "Citigroup", "GS": "Goldman Sachs", "MS": "Morgan Stanley"}},
        {"ind": "必需消费", "policy": "soda tax OR sugar tax OR food dye ban OR packaged food tariffs", "m": {"KO": "Coca-Cola", "PEP": "PepsiCo", "PG": "Procter & Gamble", "MCD": "McDonald's", "WMT": "Walmart", "COST": "Costco"}},
        {"ind": "医药", "policy": "drug pricing policy OR FDA regulation", "m": {"JNJ": "Johnson & Johnson", "PFE": "Pfizer", "MRK": "Merck", "LLY": "Eli Lilly", "ABBV": "AbbVie", "UNH": "UnitedHealth"}},
        {"ind": "能源", "policy": "oil gas energy policy", "m": {"XOM": "Exxon Mobil", "CVX": "Chevron", "COP": "ConocoPhillips"}},
        {"ind": "中概股", "policy": "China ADR delisting OR US China investment rules", "m": {"BABA": "Alibaba", "PDD": "PDD Holdings", "JD": "JD.com", "BIDU": "Baidu"}},
        {"ind": "支付", "policy": "payments regulation OR swipe fees", "m": {"V": "Visa", "MA": "Mastercard", "PYPL": "PayPal", "AXP": "American Express"}},
        {"ind": "工业", "policy": "industrial policy tariffs manufacturing", "m": {"BA": "Boeing", "CAT": "Caterpillar", "HON": "Honeywell", "GE": "GE Aerospace", "MMM": "3M"}},
        {"ind": "传媒娱乐", "policy": "streaming media regulation", "m": {"NFLX": "Netflix", "DIS": "Disney", "CMCSA": "Comcast"}},
        {"ind": "企业软件", "policy": "AI regulation enterprise software policy", "m": {"CRM": "Salesforce", "ORCL": "Oracle", "ADBE": "Adobe", "NOW": "ServiceNow", "IBM": "IBM"}},
    ],
}

# 未覆盖股票的市场级政策检索
MARKET_POLICY = {
    "A股": ("A股市场", "证监会 资本市场 政策"),
    "港股": ("港股市场", "港股 OR 香港证监会 政策"),
    "US": ("美股市场", "SEC OR Federal Reserve policy stocks"),
}


def _norm(code, market):
    c = code.strip().upper().split(".")[0]
    return c.lstrip("0").zfill(4) if market == "港股" else c


def find_group(code, market):
    key = "US" if market not in ("A股", "港股") else market
    c = _norm(code, market)
    for g in GROUPS[key]:
        if c in g["m"]:
            return g, c
    return None, c


def default_peers(code, market):
    g, c = find_group(code, market)
    return [x for x in g["m"] if x != c] if g else []


def news_profile(code, market, fallback_name=""):
    """返回 (公司检索名, 行业名, 政策检索词, 语言)"""
    key = "US" if market not in ("A股", "港股") else market
    lang = "en" if key == "US" else "zh"
    g, c = find_group(code, market)
    if g:
        return g["m"][c], g["ind"], g["policy"], lang
    ind, pol = MARKET_POLICY[key]
    if key == "US":
        name = fallback_name
        for suf in (", Inc.", " Inc.", " Corporation", " Corp.", " Holdings", " Co.", " Ltd.", " plc", " Company", " Group"):
            name = name.replace(suf, "")
        return (name.strip() or c), ind, pol, lang
    return c, ind, pol, lang  # A股/港股未覆盖：按代码检索
