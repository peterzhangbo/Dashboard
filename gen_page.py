#!/usr/bin/env python3
"""
Dashboard Generator — All-in-one script.

功能:
1. 拉取四所 ticker（容错）
2. 更新 exchange-pairs-snapshot.json
3. 差集检测新币
4. 拉取 1h K线（新币优先 + 各所 Top N）
5. 拉取四所公告（OKX 英文标题翻译，市场类型自动判断）
6. 拉取 HN top + Cointelegraph RSS，翻译标题
7. 从 template.html 读模板，填入数据
8. 追加 JSONL 快照，清理 7 天前旧快照
9. 推送 GitHub
"""
import json, urllib.request, urllib.parse, os, re, time, base64, threading, xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
SNAP_FILE = os.path.join(DATA_DIR, "exchange-pairs-snapshot.json")
NEW_FILE = os.path.join(DATA_DIR, "new-listings.json")
OUT_FILE = os.path.join(DATA_DIR, "betanews.html")
TPL_FILE = os.path.join(DATA_DIR, "template.html")
SNAPL_FILE = os.path.join(DATA_DIR, "dashboard-snapshots.jsonl")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
SNAP_RETAIN_HOURS = 168  # 7 天

# 从 config.json 读取 GitHub 配置
_cfg = {}
if os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE) as _f:
        _cfg = json.load(_f)
GITHUB_TOKEN = _cfg.get("github_token", "")
GITHUB_REPO = _cfg.get("github_repo", "peterzhangbo/Dashboard")

EXCLUDE = {
    "BTC","ETH","SOL","BNB","XRP","ADA","DOGE","AVAX","DOT","LINK","MATIC","POL",
    "UNI","AAVE","LTC","BCH","ATOM","NEAR","FIL","APT","ARB","OP","SUI","SEI",
    "TIA","INJ","FET","RENDER","RNDR","IMX","MKR","PEPE","SHIB","WIF","BONK",
    "FLOKI","TRUMP","HYPE",
    "USDC","USDT","BUSD","FDUSD","TUSD","DAI","USD1","USDD","FRAX","GUSD",
    "PYUSD","USDG","USDS","PAX","BETH","BCC","BCHABC","BCHSV",
}
FIAT = {"AUD","GBP","EUR","BRL","JPY","TRY","IDR","RUB","UAH","ZAR","PLN","NGN","ARS","COP","BIDR","BVND","BKRW"}
LEV_RE = re.compile(r'(UP|DOWN|BULL|BEAR)(USDT|BTC|ETH|BNB)$', re.IGNORECASE)

# ──────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────

def fetch_json(url, timeout=5):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def base_of(s):
    s2 = s.replace("-", "")
    for q in ["USDT", "USDC", "USD", "BUSD", "FDUSD"]:
        if s2.endswith(q) and len(s2) > len(q):
            return s2[:-len(q)]
    return s2


def skip(sym):
    b = base_of(sym).upper()
    return b in EXCLUDE or b in FIAT or bool(LEV_RE.search(sym.upper()))


def fmt(v):
    if v >= 1e6:
        return "${:,.2f}M".format(v / 1e6)
    if v >= 1e3:
        return "${:,.2f}K".format(v / 1e3)
    return "${:,.2f}".format(v)


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def get_listing_time(ex_code, symbol, market):
    """查询币对在指定交易所的上线时间（秒时间戳），失败返回 0。"""
    is_fut = market == "fut"
    esym = urllib.parse.quote(symbol)  # URL 编码
    try:
        if ex_code == "bn":
            base_url = "https://fapi.binance.com/fapi/v1/klines" if is_fut \
                else "https://api.binance.com/api/v3/klines"
            data = fetch_json(f"{base_url}?symbol={esym}&interval=1d&startTime=0&limit=1", timeout=8)
            return int(data[0][0]) // 1000

        if ex_code == "okx":
            inst_type = "SWAP" if is_fut else "SPOT"
            data = fetch_json(
                f"https://www.okx.com/api/v5/public/instruments?instType={inst_type}&instId={esym}",
                timeout=8)
            return int(data["data"][0]["listTime"]) // 1000

        if ex_code == "bg":
            if is_fut:
                data = fetch_json(
                    f"https://api.bitget.com/api/v2/mix/market/contracts?productType=USDT-FUTURES&symbol={esym}",
                    timeout=8)
                return int(data["data"][0]["openTime"]) // 1000
            else:
                data = fetch_json("https://api.bitget.com/api/v2/spot/public/symbols", timeout=8)
                for s in data.get("data", []):
                    if s.get("symbol") == symbol:  # 未编码，用于比较
                        return int(s.get("openTime", 0)) // 1000
                return 0

        if ex_code == "bb":
            if is_fut:
                data = fetch_json(
                    f"https://api.bybit.com/v5/market/instruments-info?category=linear&symbol={esym}",
                    timeout=8)
                return int(data["result"]["list"][0]["launchTime"]) // 1000
            else:
                data = fetch_json(
                    f"https://api.bybit.com/v5/market/kline?category=spot&symbol={esym}"
                    f"&start=1500000000000&interval=D&limit=1",
                    timeout=8)
                return int(data["result"]["list"][0][0]) // 1000
    except Exception:
        return 0
    return 0


# ──────────────────────────────────────────────
# 1. 拉取 Ticker（容错）
# ──────────────────────────────────────────────
print("Fetching tickers...", flush=True)

bn_st = bn_ft = okx_st = okx_ft = bg_st = bg_ft = bb_st = bb_ft = []

def _fetch(label, url, postprocess=None):
    try:
        d = fetch_json(url)
        return postprocess(d) if postprocess else d
    except Exception as e:
        print(f"  {label} FAIL: {e}", flush=True)
        return []

bn_st = _fetch("Binance spot", "https://api.binance.com/api/v3/ticker/24hr")
bn_ft = _fetch("Binance fut", "https://fapi.binance.com/fapi/v1/ticker/24hr")
okx_st = _fetch("OKX spot", "https://www.okx.com/api/v5/market/tickers?instType=SPOT",
                lambda d: d.get("data", []))
okx_ft = _fetch("OKX fut", "https://www.okx.com/api/v5/market/tickers?instType=SWAP",
                lambda d: d.get("data", []))
bg_st = _fetch("Bitget spot", "https://api.bitget.com/api/v2/spot/market/tickers",
               lambda d: d.get("data", []))
bg_ft = _fetch("Bitget fut", "https://api.bitget.com/api/v2/mix/market/tickers?productType=USDT-FUTURES",
               lambda d: d.get("data", []))
bb_st = _fetch("Bybit spot", "https://api.bybit.com/v5/market/tickers?category=spot",
               lambda d: d.get("result", {}).get("list", []))
bb_ft = _fetch("Bybit fut", "https://api.bybit.com/v5/market/tickers?category=linear",
               lambda d: d.get("result", {}).get("list", []))

print(f"  Binance: spot={len(bn_st)} fut={len(bn_ft)}  "
      f"OKX: spot={len(okx_st)} fut={len(okx_ft)}  "
      f"Bitget: spot={len(bg_st)} fut={len(bg_ft)}  "
      f"Bybit: spot={len(bb_st)} fut={len(bb_ft)}", flush=True)


# ──────────────────────────────────────────────
# 2. 提取全部当前交易对（含新增市场类型识别）
# ──────────────────────────────────────────────

def _bn_set(data):
    return sorted({t["symbol"] for t in data if t.get("symbol", "").endswith("USDT") and not skip(t["symbol"])})


def _okx_set(data):
    spot, fut = [], []
    for t in data:
        inst = t.get("instId", "")
        base = inst.replace("-", "").replace("SWAP", "")
        if skip(base):
            continue
        if inst.endswith("-USDT"):
            spot.append(inst)
        elif inst.endswith("-USDT-SWAP"):
            fut.append(inst)
    return sorted(spot), sorted(fut)


def _bg_set(data):
    return sorted({t["symbol"] for t in data if t.get("symbol", "").endswith("USDT") and not skip(t["symbol"])})


def _bb_set(data):
    return sorted({t["symbol"] for t in data if t.get("symbol", "").endswith("USDT") and not skip(t["symbol"])})


okx_s_list, okx_f_list = _okx_set(okx_ft)
current = {
    "bn_spot": _bn_set(bn_st), "bn_fut": _bn_set(bn_ft),
    "okx_spot": okx_s_list,     "okx_fut": okx_f_list,
    "bg_spot": _bg_set(bg_st), "bg_fut": _bg_set(bg_ft),
    "bb_spot": _bb_set(bb_st), "bb_fut": _bb_set(bb_ft),
}

all_current = set()
for v in current.values():
    all_current.update(v)
print(f"Current universe: {len(all_current)} symbols", flush=True)


# ──────────────────────────────────────────────
# 3. 快照差集检测 → 新币
# ──────────────────────────────────────────────

old_snap = {}
if os.path.exists(SNAP_FILE):
    try:
        with open(SNAP_FILE) as f:
            old_snap = json.load(f)
    except Exception:
        pass

old_all = set()
for v in old_snap.values():
    old_all.update(v)

new_pairs = sorted(all_current - old_all)
print(f"New pairs detected: {len(new_pairs)}", flush=True)

# 写入快照
with open(SNAP_FILE, "w") as f:
    json.dump(current, f)
print("Snapshot updated", flush=True)


# ──────────────────────────────────────────────
# 4. Top N 符号（按 24h 成交额）
# ──────────────────────────────────────────────

def _rank(tickers, key_sym, key_vol, n):
    items = []
    for t in tickers:
        sym = t.get(key_sym, "")
        if skip(sym):
            continue
        vol = float(t.get(key_vol, 0) or 0)
        if vol > 0:
            items.append((sym, vol))
    items.sort(key=lambda x: -x[1])
    return [s for s, _ in items[:n]]


S = {
    "bn_s": _rank(bn_st, "symbol", "quoteVolume", 200),
    "bn_f": _rank(bn_ft, "symbol", "quoteVolume", 100),
    "okx_s": _rank(okx_st, "instId", "volCcy24h", 200),
    "okx_f": _rank(okx_ft, "instId", "volCcy24h", 100),
    "bg_s": _rank(bg_st, "symbol", "quoteVolume", 200),
    "bg_f": _rank(bg_ft, "symbol", "usdtVolume", 100),
    "bb_s": _rank(bb_st, "symbol", "turnover24h", 200),
    "bb_f": _rank(bb_ft, "symbol", "turnover24h", 100),
}


# ──────────────────────────────────────────────
# 5. K线拉取（新币优先 + Top N）
# ──────────────────────────────────────────────

def _ku_url(ex, sym):
    """返回各交易所 1h K线 URL。"""
    esym = urllib.parse.quote(sym)  # URL 编码，处理中文等特殊字符
    if ex == "bn_s":
        return f"https://api.binance.com/api/v3/klines?symbol={esym}&interval=1h&limit=2"
    if ex == "bn_f":
        return f"https://fapi.binance.com/fapi/v1/klines?symbol={esym}&interval=1h&limit=2"
    if ex == "okx_s":
        return f"https://www.okx.com/api/v5/market/candles?instId={esym}&bar=1H&limit=2"
    if ex == "okx_f":
        return f"https://www.okx.com/api/v5/market/candles?instId={esym}&bar=1H&limit=2"
    if ex == "bg_s":
        return f"https://api.bitget.com/api/v2/spot/market/candles?symbol={esym}&granularity=1h&limit=2"
    if ex == "bg_f":
        return f"https://api.bitget.com/api/v2/mix/market/candles?symbol={esym}&granularity=1H&productType=USDT-FUTURES&limit=2"
    if ex == "bb_s":
        return f"https://api.bybit.com/v5/market/kline?category=spot&symbol={esym}&interval=60&limit=2"
    if ex == "bb_f":
        return f"https://api.bybit.com/v5/market/kline?category=linear&symbol={esym}&interval=60&limit=2"
    return None


_kl_fail = {}  # 失败原因统计
_kl_ex = {}    # 各交易所失败数
_okx_sem = threading.Semaphore(10)  # OKX 限频 10/s

def _parse_kline(ex, sym):
    """拉取并解析单个 K线，返回 (pct_change, volume_usd) 或 None。"""
    url = _ku_url(ex, sym)
    if not url:
        return None
    is_okx = ex.startswith("okx")
    if is_okx:
        _okx_sem.acquire()
    try:
        d = fetch_json(url, timeout=5)
        if ex.startswith("okx"):
            kl = d.get("data", [])
        elif ex.startswith("bb"):
            kl = list(reversed(d.get("result", {}).get("list", [])))
        elif ex.startswith("bg"):
            kl = d.get("data", [])
        else:
            kl = d  # Binance 返回数组
        if len(kl) < 2:
            _kl_fail["empty"] = _kl_fail.get("empty", 0) + 1
            return None
        pc = float(kl[-2][4])
        cc = float(kl[-1][4])
        cv = float(kl[-1][5])
        cq = float(kl[-1][7]) if len(kl[-1]) > 7 else 0
        if pc <= 0:
            return None
        vol = cq if cq > 0 else cv * cc
        if vol <= 0:
            return None
        return (round((cc - pc) / pc * 100, 2), round(vol, 2))
    except urllib.error.HTTPError as e:
        _kl_fail[f"http_{e.code}"] = _kl_fail.get(f"http_{e.code}", 0) + 1
        _kl_ex[ex] = _kl_ex.get(ex, 0) + 1
        return None
    except TimeoutError:
        _kl_fail["timeout"] = _kl_fail.get("timeout", 0) + 1
        _kl_ex[ex] = _kl_ex.get(ex, 0) + 1
        return None
    except Exception as e:
        _kl_fail[type(e).__name__] = _kl_fail.get(type(e).__name__, 0) + 1
        _kl_ex[ex] = _kl_ex.get(ex, 0) + 1
        return None
    finally:
        if is_okx:
            _okx_sem.release()


# 构建任务列表：新币优先（确保全部拉取），再加各所 Top N
tasks = []
seen = set()

# 构建全量 ticker 映射（用于定位新币所在交易所+市场）
_EX_SYMS = {}
for sym in current.get("bn_spot", []):
    _EX_SYMS.setdefault(sym, []).append("bn_s")
for sym in current.get("bn_fut", []):
    _EX_SYMS.setdefault(sym, []).append("bn_f")
for sym in current.get("okx_spot", []):
    _EX_SYMS.setdefault(sym, []).append("okx_s")
for sym in current.get("okx_fut", []):
    _EX_SYMS.setdefault(sym, []).append("okx_f")
for sym in current.get("bg_spot", []):
    _EX_SYMS.setdefault(sym, []).append("bg_s")
for sym in current.get("bg_fut", []):
    _EX_SYMS.setdefault(sym, []).append("bg_f")
for sym in current.get("bb_spot", []):
    _EX_SYMS.setdefault(sym, []).append("bb_s")
for sym in current.get("bb_fut", []):
    _EX_SYMS.setdefault(sym, []).append("bb_f")

for sym in new_pairs:
    for ex_key in _EX_SYMS.get(sym, []):
        t = (ex_key, sym)
        if t not in seen:
            tasks.append(t)
            seen.add(t)

# 按交易所交叉排列，避免同一所被并发打爆
_ex_queues = {k: [] for k in ["bn_s", "bn_f", "okx_s", "okx_f", "bg_s", "bg_f", "bb_s", "bb_f"]}
for ex_key in _ex_queues:
    for sym in S[ex_key]:
        t = (ex_key, sym)
        if t not in seen:
            _ex_queues[ex_key].append(t)
            seen.add(t)

_max_q = max((len(q) for q in _ex_queues.values()), default=0)
for i in range(_max_q):
    for ex_key in _ex_queues:
        if i < len(_ex_queues[ex_key]):
            tasks.append(_ex_queues[ex_key][i])

print(f"Fetching {len(tasks)} klines ({len(new_pairs)} new + {len(tasks)-len(new_pairs)} top)...", flush=True)

R = {}
done = 0
with ThreadPoolExecutor(max_workers=120) as pool:
    futs = {pool.submit(_parse_kline, ex, s): (ex, s) for ex, s in tasks}
    for f in as_completed(futs):
        ex, s = futs[f]
        result = f.result()
        if result:
            R[(ex, s)] = result
        done += 1
        if done % 200 == 0:
            print(f"  Klines: {done}/{len(tasks)}", flush=True)

print(f"Klines done: {done} ({len(R)} valid)", flush=True)
if _kl_fail:
    print(f"  Fail reasons: {_kl_fail}", flush=True)
    print(f"  By exchange: {_kl_ex}", flush=True)


def _rk(ex, syms, by="vol", n=3):
    """返回指定交易所某类排名 Top N。"""
    items = []
    for s in syms:
        p, v = R.get((ex, s), (None, None))
        if v is None or p is None or v <= 0:
            continue
        items.append((s, p, v))
    if by == "vol":
        items.sort(key=lambda x: -x[2])
    elif by == "g":
        items.sort(key=lambda x: -x[1])
    elif by == "l":
        items.sort(key=lambda x: x[1])
    return items[:n]


# ──────────────────────────────────────────────
# 6. 交易所公告
# ──────────────────────────────────────────────
print("Fetching announcements...", flush=True)

all_ann = []

# Binance
try:
    bn_ann = fetch_json("https://www.binance.com/bapi/composite/v1/public/cms/article/list/query?type=1&catalogId=48&pageNo=1&pageSize=5")
    for a in bn_ann["data"]["catalogs"][0]["articles"][:5]:
        t = a["title"]
        # 跳过杠杆/保证金交易类公告
        if any(k in t for k in ["杠杆","Margin","借贷","借入","借出","Leverage"]):
            continue
        mkt = "合约" if any(k in t for k in ["合约","永续","Futures","Perpetual"]) else "现货"
        all_ann.append(("Binance", f"https://www.binance.com/zh-CN/support/announcement/{a['code']}", t, a["releaseDate"], mkt))
except Exception as e:
    print(f"  Binance FAIL: {e}", flush=True)

# OKX
try:
    okx_ann = fetch_json("https://www.okx.com/priapi/v1/assistant/service-center/home/featured-announcements?defi=false&locale=zh_CN")
    for a in okx_ann.get("data", {}).get("announcements", [])[:5]:
        t = a["title"]
        if any(k in t for k in ["杠杆","Margin","借贷","借入","借出","Leverage"]):
            continue
        mkt = "合约" if any(k in t for k in ["合约","永续","Perpetual","Futures","Swap"]) else "现货"
        all_ann.append(("OKX", f"https://www.okx.com{a['url']}", t, int(a["publishTime"]) * 1000, mkt))
except Exception as e:
    print(f"  OKX FAIL: {e}", flush=True)

# Bitget
try:
    bg_ann = fetch_json("https://api.bitget.com/api/v2/public/annoucements?language=zh_CN&annType=coin_listings&limit=5")
    for a in bg_ann.get("data", [])[:5]:
        t = a["annTitle"]
        if any(k in t for k in ["杠杆","Margin","借贷","借入","借出","Leverage"]):
            continue
        mkt = "合约" if any(k in t for k in ["合约","永续","Perpetual","Futures"]) else "现货"
        ts = int(a["cTime"]) if isinstance(a["cTime"], str) else a["cTime"]
        all_ann.append(("Bitget", a["annUrl"], t, ts, mkt))
except Exception as e:
    print(f"  Bitget FAIL: {e}", flush=True)

# Bybit（使用 en-US 获得英文标题，统一翻译）
try:
    bb_ann = fetch_json("https://api.bybit.com/v5/announcements/index?type=new_crypto&locale=en-US")
    for a in bb_ann["result"]["list"][:5]:
        t = a["title"]
        if any(k in t.lower() for k in ["margin","leverage","借贷","杠杆"]):
            continue
        mkt = "合约" if any(k in t for k in ["合约","永续","Perpetual","Futures","Contract"]) else "现货"
        all_ann.append(("Bybit", a["url"], t, a["publishTime"], mkt))
except Exception as e:
    print(f"  Bybit FAIL: {e}", flush=True)

all_ann.sort(key=lambda x: -x[3])
all_ann = all_ann[:8]
print(f"  Total: {len(all_ann)}", flush=True)


# ──────────────────────────────────────────────
# 7. HN + Cointelegraph
# ──────────────────────────────────────────────
print("Fetching HN & CT...", flush=True)

def _fetch_hn_detail(sid):
    try:
        d = fetch_json(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json", timeout=4)
        return {
            "title": d.get("title", ""),
            "score": d.get("score", 0),
            "descendants": d.get("descendants", 0),
            "time": d.get("time", 0),
            "url": d.get("url", "") or f"https://news.ycombinator.com/item?id={sid}",
        }
    except Exception:
        return None


def _fetch_hn():
    try:
        ids = fetch_json("https://hacker-news.firebaseio.com/v0/topstories.json", timeout=5)
        with ThreadPoolExecutor(max_workers=10) as pool:
            results = [r for r in pool.map(_fetch_hn_detail, ids[:15]) if r and r["title"]]
        results.sort(key=lambda x: -x["score"])
        return results[:8]
    except Exception:
        return []


def _fetch_ct():
    try:
        req = urllib.request.Request("https://cointelegraph.com/rss", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            rss = r.read().decode("utf-8")
        root = ET.fromstring(rss)
        news = []
        for item in root.findall(".//item")[:15]:
            title = item.findtext("title", "")
            if len(title) < 10:
                continue
            link = item.findtext("link", "")
            pub_date = item.findtext("pubDate", "")
            cats = [c.text for c in item.findall("category") if c.text]
            news.append({"title": title, "url": link, "tag": cats[0] if cats else "Crypto",
                         "pub_date": pub_date})
        return news[:8]
    except Exception:
        return []


HN_STORIES = CT_NEWS = []
with ThreadPoolExecutor(max_workers=4) as pool:
    hn_fut = pool.submit(_fetch_hn)
    ct_fut = pool.submit(_fetch_ct)
    HN_STORIES = hn_fut.result()
    CT_NEWS = ct_fut.result()
print(f"  HN: {len(HN_STORIES)}, CT: {len(CT_NEWS)}", flush=True)


# ──────────────────────────────────────────────
# 8. 翻译
# ──────────────────────────────────────────────

def _translate_batch(texts):
    """批量翻译文本为中文（Google Translate，无 key）。"""
    if not texts:
        return texts
    SEP = " ||| "
    try:
        joined = SEP.join(texts)
        q = urllib.parse.quote(joined)
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=zh-CN&dt=t&q={q}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        full = "".join(seg[0] for seg in data[0] if seg[0])
        parts = [p.strip() for p in full.split("|||")]
        while len(parts) < len(texts):
            parts.append(texts[len(parts)])
        return parts[:len(texts)]
    except Exception:
        return texts


CT_TAG_MAP = {
    "Latest News": "最新", "Markets": "市场", "Policy": "政策",
    "DeFi": "DeFi", "Regulation": "监管", "Crypto": "加密",
    "Blockchain": "区块链", "Altcoin": "山寨币", "Bitcoin": "比特币",
    "Ethereum": "以太坊", "NFT": "NFT", "Stablecoin": "稳定币",
    "Business": "商业", "Technology": "科技", "World News": "国际",
}


print("Translating...", flush=True)

# HN + CT 标题翻译
all_titles = [s["title"] for s in HN_STORIES] + [n["title"] for n in CT_NEWS]
if all_titles:
    trans = _translate_batch(all_titles)
    for i, s in enumerate(HN_STORIES):
        if i < len(trans):
            s["title"] = trans[i]
    for i, n in enumerate(CT_NEWS):
        idx = len(HN_STORIES) + i
        if idx < len(trans):
            n["title"] = trans[idx]

for n in CT_NEWS:
    n["tag"] = CT_TAG_MAP.get(n.get("tag", ""), n.get("tag", ""))

# 公告翻译（仅英文标题）
eng_indices = [i for i, (_, _, title, _, _) in enumerate(all_ann) if title.isascii() and len(title) > 5]
if eng_indices:
    eng_titles = [all_ann[i][2] for i in eng_indices]
    trans_ann = _translate_batch(eng_titles)
    for j, ai in enumerate(eng_indices):
        if j < len(trans_ann):
            ex, url, _, ts, mkt = all_ann[ai]
            all_ann[ai] = (ex, url, trans_ann[j], ts, mkt)
    print(f"  Translated {len(eng_indices)} announcement titles", flush=True)

print("Translation done", flush=True)


# ──────────────────────────────────────────────
# 9. BTC 数据
# ──────────────────────────────────────────────

btc_p = btc_c = 0.0
for d in bn_st:
    if d.get("symbol") == "BTCUSDT":
        btc_p = float(d.get("lastPrice", 0))
        btc_c = float(d.get("priceChangePercent", 0))
        break

# 从 CoinGecko 获取准确流通量
try:
    cg = fetch_json("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd&include_market_cap=true", timeout=5)
    btc_mcap = cg.get("bitcoin", {}).get("usd_market_cap", 0)
    if btc_mcap > 0:
        btc_supply = btc_mcap / btc_p if btc_p > 0 else 19_870_000
    else:
        btc_supply = 19_870_000
except Exception:
    btc_supply = 19_870_000

btc_mcap = btc_p * btc_supply

now = datetime.now(timezone.utc)


def ft_ts(ts):
    ts = int(ts)
    if ts > 1e12:
        ts = ts // 1000
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%m-%d %H:%M")


# ──────────────────────────────────────────────
# 10. 构建 HTML
# ──────────────────────────────────────────────
print("Building HTML...", flush=True)


def turl(ex, sym, fut):
    b = base_of(sym)
    if ex in ("bn", "bn_s", "bn_f"):
        if fut:
            return f"https://www.binance.com/en/futures/{sym}"
        return f"https://www.binance.com/en/trade/{b}_USDT"
    if ex in ("okx", "okx_s", "okx_f"):
        if fut:
            return f"https://www.okx.com/trade-swap/{b.lower()}-usdt-swap"
        return f"https://www.okx.com/trade-spot/{b.lower()}-usdt"
    if ex in ("bg", "bg_s", "bg_f"):
        if fut:
            return f"https://www.bitget.com/futures/usdt/{sym}"
        return f"https://www.bitget.com/spot/{sym}"
    if ex in ("bb", "bb_s", "bb_f"):
        if fut:
            return f"https://www.bybit.com/trade/usdt/{sym}"
        return f"https://www.bybit.com/trade/spot/{b}/USDT"
    return "#"


# 公告 HTML
listing_html = ""
for i, (ex, url, title, ts, mkt) in enumerate(all_ann):
    tag_cls = {"Binance": "tag-ex", "OKX": "tag-crypto", "Bitget": "tag-defi", "Bybit": "tag-pol"}.get(ex, "tag-crypto")
    listing_html += (
        f'<div class="news-row"><span class="news-n">{i+1}</span>'
        f'<div class="news-body"><a class="news-t" href="{url}" target="_blank">{esc(title)}</a>'
        f'<div class="news-meta"><span class="tag {tag_cls}">{ex} {mkt}</span> {ft_ts(ts)}</div>'
        f'</div></div>\n'
    )

# 新币 HTML（按实际上线时间过滤 12h）
deduped = []
if os.path.exists(NEW_FILE):
    try:
        with open(NEW_FILE) as f:
            deduped = json.load(f)
    except Exception:
        pass

now_ts = int(now.timestamp())
cutoff = now_ts - 12 * 3600

# ── 第一步：清理旧条目（用 listing_time 判断，兼容旧 discovered）──
# 给缺少 listing_time 的旧条目补查上线时间
need_query = [p for p in deduped if "listing_time" not in p]
if need_query:
    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = {pool.submit(get_listing_time, p["exchange"], p["symbol"], p["market"]): p
                for p in need_query}
        for f in as_completed(futs):
            p = futs[f]
            lt = f.result()
            if lt > 0:
                p["listing_time"] = lt
            # 查不到则用 discovered 兜底
            p.setdefault("listing_time", p.get("discovered", 0))
deduped = [p for p in deduped
           if p.get("listing_time", p.get("discovered", 0)) > cutoff]

# ── 第二步：新币对逐个查上线时间，≤12h 才写入 ──
EX_NAME = {"bn": "Binance", "okx": "OKX", "bg": "Bitget", "bb": "Bybit"}

seen_new = {(p["exchange"], p["symbol"]) for p in deduped}

for sym in new_pairs:
    for ex_key in _EX_SYMS.get(sym, []):
        ex_code = ex_key[:2]
        if (ex_code, sym) in seen_new:
            continue
        is_fut = ex_key.endswith("_f")
        market = "fut" if is_fut else "spot"
        lt = get_listing_time(ex_code, sym, market)
        if lt == 0 or lt < cutoff:
            continue                     # 查不到或已超 12h → 跳过
        p, v = R.get((ex_key, sym), (0, 0))
        deduped.append({
            "exchange": ex_code, "symbol": sym, "market": market,
            "listing_time": lt, "change": p or 0, "volume": v or 0,
        })
        seen_new.add((ex_code, sym))

# 按上线时间降序
deduped.sort(key=lambda x: -x.get("listing_time", 0))

# 写回 new-listings.json
with open(NEW_FILE, "w") as f:
    json.dump(deduped, f, indent=2, ensure_ascii=False)

# 生成新币 HTML
nl_html = ""
for p in deduped[:10]:
    ex_code = p["exchange"]
    ex_name = EX_NAME.get(ex_code, ex_code)
    is_fut = p["market"] == "fut"
    sym = p["symbol"]
    url = turl(ex_code, sym, is_fut)
    chg = p.get("change", 0)
    vol = p.get("volume", 0)
    cls = "up" if chg >= 0 else "down"
    sg = "+" if chg >= 0 else ""
    lt = p.get("listing_time", p.get("discovered", 0))
    ts_str = datetime.fromtimestamp(lt, tz=timezone.utc).strftime("%m-%d %H:%M")
    mkt_label = "合约" if is_fut else "现货"
    nl_html += (
        f'<div class="nl-item" data-ts="{lt}">'
        f'<span class="nl-pair"><a href="{url}" target="_blank">{sym}</a></span>'
        f'<span class="nl-chg {cls}">{sg}{chg:.2f}%</span>'
        f'<span class="nl-vol">{fmt(vol)}</span>'
        f'<span class="nl-right"><span class="nl-ex">{ex_name}</span>'
        f'<span class="nl-type">{mkt_label}</span><span class="nl-time">{ts_str}</span></span></div>\n'
    )

if not nl_html:
    nl_html = '<div style="padding:8px;color:var(--t3);font-size:11px">12h 内暂无新增交易对</div>'

# HN HTML
hn_html = '<div class="tab-panel" id="tab-hn">\n  <div class="news-list" id="hn-list">\n'
for i, s in enumerate(HN_STORIES):
    hn_html += (
        f'    <div class="news-row" data-score="{s["score"]}" data-time="{s["time"]}" data-comments="{s["descendants"]}">'
        f'<span class="news-n">{i+1}</span>'
        f'<div class="news-body"><a class="news-t" href="{esc(s["url"])}" target="_blank">{esc(s["title"])}</a>'
        f'<div class="news-meta">↑{s["score"]} · \U0001f4ac{s["descendants"]} · {ft_ts(s["time"])}</div>'
        f'</div></div>\n'
    )
if not HN_STORIES:
    hn_html += '    <div style="padding:8px;color:var(--t3);font-size:11px">暂无数据</div>\n'
hn_html += '  </div>\n</div>'

# CT HTML
news_html = '<div class="tab-panel" id="tab-news">\n  <div class="news-list">\n'
for i, n in enumerate(CT_NEWS):
    time_str = ""
    pub = n.get("pub_date", "")
    if pub:
        try:
            dt = parsedate_to_datetime(pub)
            time_str = dt.strftime("%m-%d %H:%M")
        except Exception:
            pass
    meta_parts = ['<span class="tag tag-crypto">CoinTelegraph</span>']
    if time_str:
        meta_parts.append(time_str)
    meta = f'<div class="news-meta">{" ".join(meta_parts)}</div>'
    news_html += (
        f'    <div class="news-row"><span class="news-n">{i+1}</span>'
        f'<div class="news-body"><a class="news-t" href="{esc(n["url"])}" target="_blank">{esc(n["title"])}</a>{meta}</div></div>\n'
    )
if not CT_NEWS:
    news_html += '    <div style="padding:8px;color:var(--t3);font-size:11px">暂无数据</div>\n'
news_html += '  </div>\n</div>'


# ── 交易所面板 ──

def _ex_panel(cat, tid, active=False):
    """构建交易所监控面板。cat: vol/gain/loss。"""
    act = " active" if active else ""
    by_map = {"vol": "vol", "gain": "g", "loss": "l"}
    ex_names = [("bn", "Binance"), ("okx", "OKX"), ("bg", "Bitget"), ("bb", "Bybit")]
    ex_sfx = {"bn": ("bn_s", "bn_f"), "okx": ("okx_s", "okx_f"),
              "bg": ("bg_s", "bg_f"), "bb": ("bb_s", "bb_f")}

    h = f'  <div class="ex-panel{act}" id="{tid}">\n    <div class="ex-dual">\n'
    for market, label in [("spot", "现货"), ("fut", "永续合约")]:
        is_fut = market == "fut"
        h += f'      <div class="ex-side"><div class="ex-side-label">{label}</div>\n        <div class="ex-grid">\n'
        for ex_code, ex_name in ex_names:
            ex_s = ex_sfx[ex_code][1 if is_fut else 0]
            raw = _rk(ex_s, S[ex_s], by=by_map[cat], n=3)
            h += f'          <div class="ex-box"><div class="ex-box-name">{ex_name}</div>\n'
            for pair, pct, vol in raw:
                dp = pair if is_fut else f"{base_of(pair)}/USDT"
                if is_fut and ex_code == "okx":
                    dp = base_of(pair.replace("-USDT-SWAP", "")) + "USDT"
                url = turl(ex_code, pair, is_fut)
                c = "up" if pct >= 0 else "down"
                sg = "+" if pct >= 0 else ""
                if cat == "vol":
                    arrow = "▲" if pct >= 0 else "▼"
                    h += f'            <div class="ex-item"><div class="ex-item-pair"><a href="{url}" target="_blank">{dp}</a></div><div class="ex-item-data"><b>{fmt(vol)}</b> <span class="{c}" style="font-size:10px;opacity:.5">{arrow}</span></div></div>\n'
                else:
                    h += f'            <div class="ex-item"><div class="ex-item-pair"><a href="{url}" target="_blank">{dp}</a></div><div class="ex-item-data"><span class="{c}" style="font-weight:700;font-size:14px">{sg}{pct:.2f}%</span> <span style="font-size:10px;color:var(--t3)">{fmt(vol)}</span></div></div>\n'
            h += '          </div>\n'
        h += '        </div>\n      </div>\n'
    h += '    </div>\n  </div>\n'
    return h


btc_cls = "up" if btc_c >= 0 else "down"
btc_arrow = "▲" if btc_c >= 0 else "▼"
btc_mcap_t = f"{btc_mcap / 1e12:.2f}"

# 读取模板并填入数据
with open(TPL_FILE) as f:
    page = f.read()

page = page.replace("{{TIME}}", now.strftime("%Y-%m-%d %H:%M"))
page = page.replace("{{BTC_PRICE}}", f"{btc_p:,.0f}")
page = page.replace("{{BTC_CHG_CLS}}", btc_cls)
page = page.replace("{{BTC_ARROW}}", btc_arrow)
page = page.replace("{{BTC_CHG_VAL}}", f"{abs(btc_c):.2f}")
page = page.replace("{{BTC_MCAP}}", btc_mcap_t)
page = page.replace("{{NL_HTML}}", nl_html)
page = page.replace("{{LISTING_HTML}}", listing_html)
page = page.replace("{{HN_HTML}}", hn_html)
page = page.replace("{{NEWS_HTML}}", news_html)
page = page.replace("{{EX_VOL}}", _ex_panel("vol", "etab-vol", True))
page = page.replace("{{EX_GAIN}}", _ex_panel("gain", "etab-gain"))
page = page.replace("{{EX_LOSS}}", _ex_panel("loss", "etab-loss"))

with open(OUT_FILE, "w") as f:
    f.write(page)
print(f"HTML written: {len(page)} bytes → {OUT_FILE}", flush=True)


# ──────────────────────────────────────────────
# 11. 快照 + 清理
# ──────────────────────────────────────────────

hn_snap = [{"t": s["title"], "s": s["score"], "c": s["descendants"], "ts": s["time"]} for s in HN_STORIES]
crypto_snap = [{"t": n["title"], "tag": n.get("tag", "")} for n in CT_NEWS]
snap_line = json.dumps({
    "ts": now.isoformat(),
    "btc": {"price": btc_p, "change": btc_c, "mcap": btc_mcap},
    "hn": hn_snap,
    "crypto": crypto_snap,
}, ensure_ascii=False)

with open(SNAPL_FILE, "a") as f:
    f.write(snap_line + "\n")
print(f"Snapshot appended: BTC ${btc_p:,.0f} ({btc_c:+.2f}%)", flush=True)

# 清理超过 7 天的旧快照
try:
    lines = open(SNAPL_FILE).readlines()
    clean = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=SNAP_RETAIN_HOURS)
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            ts = obj.get("ts", "")
            if isinstance(ts, str) and ts:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if dt < cutoff:
                    continue
            elif isinstance(ts, (int, float)):
                dt = datetime.fromtimestamp(ts / 1000 if ts > 1e12 else ts, tz=timezone.utc)
                if dt < cutoff:
                    continue
            clean.append(line)
        except Exception:
            clean.append(line)
    if len(clean) < len(lines):
        with open(SNAPL_FILE, "w") as f:
            f.write("\n".join(clean) + "\n" if clean else "")
        print(f"Snapshot cleanup: {len(lines)} → {len(clean)} entries", flush=True)
except Exception:
    pass


# ──────────────────────────────────────────────
# 12. 推送 GitHub
# ──────────────────────────────────────────────
print("Pushing to GitHub...", flush=True)


def _gh_push(path, content, message):
    """通过 GitHub Contents API 更新文件。"""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "User-Agent": "Mozilla/5.0",
               "Accept": "application/vnd.github.v3+json"}

    # 获取当前 SHA
    sha = None
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as r:
            sha = json.loads(r.read()).get("sha")
    except Exception:
        pass

    body = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
    }
    if sha:
        body["sha"] = sha

    try:
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="PUT",
                                     headers={**headers, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            sha_out = json.loads(r.read()).get("content", {}).get("sha", "")[:8]
            print(f"  {path}: OK ({sha_out})", flush=True)
    except Exception as e:
        print(f"  {path}: FAIL - {e}", flush=True)


_gh_push("betanews.html", page, f"Dashboard update {now.strftime('%Y-%m-%d %H:%M')} UTC")
_gh_push("new-listings.json", json.dumps(deduped, indent=2, ensure_ascii=False),
         f"New listings {now.strftime('%Y-%m-%d %H:%M')} UTC")
_gh_push("dashboard-snapshots.jsonl", open(SNAPL_FILE).read(),
         f"Snapshot {now.strftime('%Y-%m-%d %H:%M')} UTC")
_gh_push("exchange-pairs-snapshot.json", json.dumps(current, indent=2),
         f"Pairs snapshot {now.strftime('%Y-%m-%d %H:%M')} UTC")

print("\n=== Done ===")
print(f"BTC: ${btc_p:,.0f} ({btc_c:+.2f}%)  Supply: {btc_supply:,.0f}")
print(f"Klines: {len(R)} valid  New: {len(new_pairs)}  Ann: {len(all_ann)}  HN: {len(HN_STORIES)}  CT: {len(CT_NEWS)}")
