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
import json, urllib.request, urllib.parse, os, re, time, base64, threading, html, ssl, xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

_SSL_CTX = ssl.create_default_context()

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
SNAP_FILE = os.path.join(DATA_DIR, "exchange-pairs-snapshot.json")
NEW_FILE = os.path.join(DATA_DIR, "new-listings.json")
OUT_FILE = os.path.join(DATA_DIR, "betanews.html")
TPL_FILE = os.path.join(DATA_DIR, "template.html")
SNAP_HTML_FILE = os.path.join(DATA_DIR, "snapshot.html")
SNAPL_FILE = os.path.join(DATA_DIR, "dashboard-snapshots.jsonl")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
ARTIFACT_FILE = os.path.join(DATA_DIR, "artifact-index.html")
SNAP_RETAIN_HOURS = 168  # 7 天

# 从 config.json 读取 GitHub 配置
_cfg = {}
if os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE) as _f:
        _cfg = json.load(_f)
GITHUB_REPO = _cfg.get("github_repo", "peterzhangbo/Dashboard")
GITHUB_TOKEN = _cfg.get("github_token", "")

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

def fetch_json(url, timeout=8, retries=2):
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as r:
                return json.loads(r.read())
        except Exception:
            if i == retries:
                raise
            time.sleep(1)


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
    return html.escape(s, quote=True)


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
                global _bg_sym_cache
                if _bg_sym_cache is None:
                    _bg_sym_cache = fetch_json("https://api.bitget.com/api/v2/spot/public/symbols", timeout=8)
                for s in _bg_sym_cache.get("data", []):
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


okx_s_list, okx_f_list = _okx_set(okx_st + okx_ft)
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

def _rank(tickers, key_sym, key_vol, n, allowed, offset=0):
    items = []
    for t in tickers:
        sym = t.get(key_sym, "")
        if sym not in allowed or skip(sym):
            continue
        vol = float(t.get(key_vol, 0) or 0)
        if vol > 0:
            items.append((sym, vol))
    items.sort(key=lambda x: -x[1])
    return [s for s, _ in items[offset:offset+n]]


# 用已过滤的 USDT 集合，确保 _rank 只处理 USDT 对
S_USDT = {
    "bn_s": set(_bn_set(bn_st)), "bn_f": set(_bn_set(bn_ft)),
    "okx_s": set(okx_s_list),    "okx_f": set(okx_f_list),
    "bg_s": set(_bg_set(bg_st)), "bg_f": set(_bg_set(bg_ft)),
    "bb_s": set(_bb_set(bb_st)), "bb_f": set(_bb_set(bb_ft)),
}

S = {
    "bn_s": _rank(bn_st, "symbol", "quoteVolume", 140, S_USDT["bn_s"]),
    "bn_f": _rank(bn_ft, "symbol", "quoteVolume", 70, S_USDT["bn_f"]),
    "okx_s": _rank(okx_st, "instId", "volCcy24h", 140, S_USDT["okx_s"]),
    "okx_f": _rank(okx_ft, "instId", "volCcy24h", 70, S_USDT["okx_f"]),
    "bg_s": _rank(bg_st, "symbol", "quoteVolume", 140, S_USDT["bg_s"]),
    "bg_f": _rank(bg_ft, "symbol", "usdtVolume", 70, S_USDT["bg_f"]),
    "bb_s": _rank(bb_st, "symbol", "turnover24h", 140, S_USDT["bb_s"]),
    "bb_f": _rank(bb_ft, "symbol", "turnover24h", 70, S_USDT["bb_f"]),
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
_bg_sym_cache = None  # Bitget 现货全量 symbols 缓存（避免重复拉取）

def _parse_kline(ex, sym):
    """拉取并解析 1h K线，返回 (pct_change, volume_usd) 或 None。

    取最近 2 根 1H K线，使用倒数第二根（最近已收盘）K线：
    - pct_change = (close - open) / open × 100%（单根 K线内涨跌幅）
    - volume = quote volume（USDT 计价成交额）
    """
    url = _ku_url(ex, sym)
    if not url:
        return None
    is_okx = ex.startswith("okx")
    if is_okx:
        _okx_sem.acquire()
    try:
        d = fetch_json(url, timeout=8)
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
        # 取最近已收盘 K线（倒数第二根）的所有字段
        prev = kl[-2]
        p_open = float(prev[1])
        p_close = float(prev[4])
        cq = float(prev[7]) if len(prev) > 7 else 0
        cv = float(prev[5])
        if p_open <= 0:
            return None
        # pct_change: 单根 K线内 (close - open) / open
        pct = round((p_close - p_open) / p_open * 100, 2)
        # volume: quote volume (USDT)，fallback 为 base_vol × close
        vol = cq if cq > 0 else cv * p_close
        if vol <= 0:
            return None
        return (pct, round(vol, 2))
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


# ──────────────────────────────────────────────
# 5b. 补偿：如果有效数据不足 100 个，追加拉取
# ──────────────────────────────────────────────

# ticker 数据源映射
_TICKERS = {
    "bn_s": bn_st, "bn_f": bn_ft,
    "okx_s": okx_st, "okx_f": okx_ft,
    "bg_s": bg_st, "bg_f": bg_ft,
    "bb_s": bb_st, "bb_f": bb_ft,
}
_TICK_KEY = {
    "bn_s": ("symbol", "quoteVolume"), "bn_f": ("symbol", "quoteVolume"),
    "okx_s": ("instId", "volCcy24h"),  "okx_f": ("instId", "volCcy24h"),
    "bg_s": ("symbol", "quoteVolume"), "bg_f": ("symbol", "usdtVolume"),
    "bb_s": ("symbol", "turnover24h"), "bb_f": ("symbol", "turnover24h"),
}

retry_round = 0
for ex_key in list(S.keys()):
    valid_count = sum(1 for s in S[ex_key] if (ex_key, s) in R)
    threshold = 100 if ex_key.endswith("_s") else 60
    if valid_count >= threshold:
        continue
    n_target = 140 if ex_key.endswith("_s") else 70
    retry_round = 0
    while valid_count < n_target and retry_round < 8:
        retry_round += 1
        offset = len(S[ex_key])
        new_syms = _rank(_TICKERS[ex_key], *_TICK_KEY[ex_key], n_target, S_USDT[ex_key], offset=offset)
        if not new_syms:
            break
        S[ex_key].extend(new_syms)
        # 拉取新批次的 kline
        new_tasks = [(ex_key, s) for s in new_syms if (ex_key, s) not in R and (ex_key, s) not in seen]
        for t in new_tasks:
            seen.add(t)
        if new_tasks:
            with ThreadPoolExecutor(max_workers=40) as pool:
                futs2 = {pool.submit(_parse_kline, ek, sm): (ek, sm) for ek, sm in new_tasks}
                for f in as_completed(futs2):
                    ek, sm = futs2[f]
                    result = f.result()
                    if result:
                        R[(ek, sm)] = result
        valid_count = sum(1 for s in S[ex_key] if (ex_key, s) in R)
        print(f"  补偿 {ex_key}: 第{retry_round}轮, 新增{len(new_syms)}, 有效{valid_count}/{n_target}", flush=True)


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
        with urllib.request.urlopen(req, timeout=8, context=_SSL_CTX) as r:
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
HN_ALL = HN_STORIES[:]


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
        with urllib.request.urlopen(req, timeout=5, context=_SSL_CTX) as r:
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
    display = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%m-%d %H:%M")
    return f'<time data-epoch="{ts}">{display}</time>'


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


# 公告 HTML（新卡片行结构）
listing_html = ""
for i, (ex, url, title, ts, mkt) in enumerate(all_ann):
    listing_html += (
        f'<a class="news-row" href="{esc(url)}" target="_blank" rel="noopener">'
        f'<span class="news-row__title">{esc(title)}</span>'
        f'<span class="news-row__meta"><span class="src">{ex} {mkt}</span><span class="mono">{ft_ts(ts)}</span></span>'
        f'</a>\n'
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

# 生成新币 HTML（pill 卡片结构）
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
    ts_str = f'<time data-epoch="{lt}">{datetime.fromtimestamp(lt, tz=timezone.utc).strftime("%m-%d %H:%M")}</time>'
    mkt_label = "永续" if is_fut else "现货"
    mkt_cls = "is-perp" if is_fut else "is-spot"
    chg_html = f'<span class="{cls} mono">{sg}{chg:.2f}%</span><span class="lst__vol mono">{fmt(vol)}</span>' if vol else '<span style="color:var(--fg-4);font-style:italic">暂无 1h 数据</span>'
    nl_html += (
        f'<a class="list-pill" href="{url}" target="_blank" data-ts="{lt}">'
        f'<span class="lst__main"><span class="lst__pair">{sym}<span class="q">/USDT</span></span>'
        f'<span class="lst__1h">{chg_html}</span></span>'
        f'<span class="lst__aside"><span class="lst__ex">{ex_name}<span class="lst__mkt {mkt_cls}">{mkt_label}</span></span>'
        f'<span class="lst__time mono">{ts_str}</span></span></a>\n'
    )

if not nl_html:
    nl_html = '<div style="padding:8px;color:var(--fg-3);font-size:11px">12h 内暂无新增交易对</div>'

# ── 生成 Cowork artifact（直接用 betanews.html） ──
try:
    with open(OUT_FILE, encoding="utf-8") as _f:
        _betanews = _f.read()
    _art_json = json.dumps({
        "name": "Tech Crypto Dashboard",
        "schemaVersion": 1,
        "description": f"科技与加密货币仪表盘 · BTC ${btc_p:,.0f}（{btc_c:+.2f}%）· HN {len(HN_STORIES)} 条 · CT {len(CT_NEWS)} 条",
        "mcpTools": ["mcp__workspace__web_fetch"],
        "mcpServerNames": ["workspace"]
    }, ensure_ascii=False)
    _art = f'<!DOCTYPE html>\n<script type="application/json" id="cowork-artifact-meta">\n{_art_json}\n</script>\n{_betanews}'
    with open(ARTIFACT_FILE, "w", encoding="utf-8") as _f:
        _f.write(_art)
    print(f"Artifact HTML written: {len(_art)} bytes → {ARTIFACT_FILE}", flush=True)
except Exception as e:
    print(f"Artifact generation FAIL: {e}", flush=True)

# HN HTML（仅行数据，外层卡片由 template 提供）
hn_html = ""
for i, s in enumerate(HN_STORIES):
    hn_html += (
        f'<a class="news-row" href="{esc(s["url"])}" target="_blank" rel="noopener" data-score="{s["score"]}" data-time="{s["time"]}" data-comments="{s["descendants"]}">'
        f'<span class="news-row__title">{esc(s["title"])}</span>'
        f'<span class="news-row__meta"><span class="stat up"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5"></path><path d="m5 12 7-7 7 7"></path></svg>{s["score"]}</span><span class="stat"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>{s["descendants"]}</span><span class="mono">{ft_ts(s["time"])}</span></span>'
        f'</a>\n'
    )
if not HN_STORIES:
    hn_html = '<div style="padding:12px;color:var(--fg-3);font-size:11px">暂无数据</div>\n'

# CT HTML（仅行数据，外层卡片由 template 提供）
news_html = ""
for i, n in enumerate(CT_NEWS):
    time_str = ""
    pub = n.get("pub_date", "")
    if pub:
        try:
            dt = parsedate_to_datetime(pub)
            epoch = int(dt.timestamp())
            time_str = f'<time data-epoch="{epoch}">{dt.strftime("%m-%d %H:%M")}</time>'
        except Exception:
            pass
    meta_parts = ['<span class="src">CoinTelegraph</span>']
    if time_str:
        meta_parts.append(f'<span class="mono">{time_str}</span>')
    meta = "".join(meta_parts)
    news_html += (
        f'<a class="news-row" href="{esc(n["url"])}" target="_blank" rel="noopener">'
        f'<span class="news-row__title">{esc(n["title"])}</span>'
        f'<span class="news-row__meta">{meta}</span>'
        f'</a>\n'
    )
if not CT_NEWS:
    news_html = '<div style="padding:12px;color:var(--fg-3);font-size:11px">暂无数据</div>\n'


# ── 交易所面板 ──

def _ex_panel(cat, tid, active=False, streaks=None):
    """构建交易所监控面板。cat: vol/gain/loss。永续在上，现货在下。"""
    act = " is-active" if active else ""
    by_map = {"vol": "vol", "gain": "g", "loss": "l"}
    ex_names = [("bn", "Binance"), ("okx", "OKX"), ("bg", "Bitget"), ("bb", "Bybit")]
    ex_sfx = {"bn": ("bn_s", "bn_f"), "okx": ("okx_s", "okx_f"),
              "bg": ("bg_s", "bg_f"), "bb": ("bb_s", "bb_f")}
    # 各所 SVG 图标
    ex_svg = {
        "bn": '<svg viewBox="0 0 20 20" fill="none"><path d="M10 2L5.5 6.5 7.9 8.9 10 6.8l2.1 2.1 2.4-2.4z" fill="#000"/><path d="M5.5 6.5L10 2l4.5 4.5-4.4 4.4z" fill="#fff" opacity=".25"/><path d="M10 18l4.5-4.5-2.4-2.4-2.1 2.1-2.1-2.1-2.4 2.4z" fill="#000" opacity=".9"/><path d="M13.5 13.5L10 18l-4.5-4.5 2.4-2.4 2.1 2.1 2.1-2.1z" fill="#fff" opacity=".15"/></svg>',
        "okx": '<svg viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="7" stroke="#fff" stroke-width="2" stroke-dasharray="11 4" stroke-linecap="round"/><circle cx="10" cy="10" r="2.5" fill="#fff"/></svg>',
        "bg": '<svg viewBox="0 0 20 20" fill="none"><path d="M5 5h10v2H5zM5 9h7v2H5zM5 13h10v2H5z" fill="#fff" opacity=".9"/><rect x="13" y="9" width="2" height="2" rx="1" fill="#fff"/></svg>',
        "bb": '<svg viewBox="0 0 20 20" fill="none"><path d="M10 3l7 14H3z" fill="none" stroke="#fff" stroke-width="1.8" stroke-linejoin="round"/><path d="M7 12l3-5 3 5" stroke="#fff" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    }
    if streaks is None:
        streaks = {}

    # 火焰 SVG（streak 徽标）— stroke 风格
    _fire_svg = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 18h20l-2-9-5 4-3-7-3 7-5-4z" fill="currentColor" stroke="none"></path></svg>'

    h = f'  <div class="ex-panel{act}" id="{tid}">\n'
    for market, label, mkt_cls in [("fut", "永续合约", "is-perp"), ("spot", "现货", "is-spot")]:
        is_fut = market == "fut"
        h += f'    <div class="ex-block__label {mkt_cls}"><span class="dot-sm"></span>{label}</div>\n'
        h += f'    <div class="ex-block__grid">\n'
        for ex_code, ex_name in ex_names:
            ex_s = ex_sfx[ex_code][1 if is_fut else 0]
            raw = _rk(ex_s, S[ex_s], by=by_map[cat], n=3)
            svg = ex_svg.get(ex_code, "")
            h += f'      <div class="ex-card"><div class="ex-card__head"><div class="ex-logo {ex_code}">{svg}</div><div class="ex-card__name">{ex_name}</div></div><div class="ex-rows">\n'
            for pair, pct, vol in raw:
                dp = pair if is_fut else f"{base_of(pair)}/USDT"
                if is_fut and ex_code == "okx":
                    dp = base_of(pair.replace("-USDT-SWAP", "")) + "USDT"
                url = turl(ex_code, pair, is_fut)
                c = "up" if pct >= 0 else "down"
                sg = "+" if pct >= 0 else ""
                # streak 徽标
                st_key = f"{ex_code}_{market}_{by_map[cat]}"
                st_count = streaks.get((st_key, pair), 0)
                st_badge = f'<span class="streak" title="近期连续在榜 {st_count} 次">{_fire_svg}{st_count}</span>' if st_count > 1 else ""
                if cat == "vol":
                    h += f'        <a class="ex-row" href="{url}" target="_blank" rel="noopener"><div class="ex-row__pair">{dp}{st_badge}</div><div class="ex-row__right"><span class="ex-row__val {c}">{fmt(vol)}</span><span class="ex-row__sub">{sg}{pct:.2f}%</span></div></a>\n'
                else:
                    h += f'        <a class="ex-row" href="{url}" target="_blank" rel="noopener"><div class="ex-row__pair">{dp}{st_badge}</div><div class="ex-row__right"><span class="ex-row__val {c}">{sg}{pct:.2f}%</span><span class="ex-row__sub">{fmt(vol)}</span></div></a>\n'
            h += '      </div></div>\n'
        h += '    </div>\n'
    h += '  </div>\n'
    return h


btc_cls = "up" if btc_c >= 0 else "down"

# ──────────────────────────────────────────────
# 11. 收集榜单排名 + streak
# ──────────────────────────────────────────────
_EX_KEYS = [("bn", "bn_s", "bn_f"), ("okx", "okx_s", "okx_f"),
            ("bg", "bg_s", "bg_f"), ("bb", "bb_s", "bb_f")]
_ALL_RANKINGS = {}  # key: "{ex}_{market}_{cat}" → [sym, ...]
for ex_code, sk, fk in _EX_KEYS:
    for cat in ("vol", "g", "l"):
        for market, ex_s in [("spot", sk), ("fut", fk)]:
            top = _rk(ex_s, S[ex_s], by=cat, n=3)
            _ALL_RANKINGS[f"{ex_code}_{market}_{cat}"] = [p[0] for p in top]

# ──────────────────────────────────────────────
# 11b. 从历史快照计算 streak（连续在榜次数，按小时去重）
# ──────────────────────────────────────────────
streak_map = {}  # (key, sym) → count
try:
    with open(SNAPL_FILE) as _sf:
        hist_lines = _sf.readlines()
    # 按小时分组：同一小时内的多个快照合并为一个
    hourly = {}  # hour_key → ranking set
    for line in hist_lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            rk = obj.get("rankings")
            ts = obj.get("ts", "")
            if not rk:
                continue
            # 用时间戳的小时部分做 key
            if isinstance(ts, str) and ts:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            else:
                continue
            hk = dt.strftime("%Y-%m-%d %H")
            if hk not in hourly:
                hourly[hk] = {}
            # 合并该小时内所有快照的 ranking
            for k, v in rk.items():
                hourly[hk].setdefault(k, set()).update(v)
        except Exception:
            pass
    # 按时间倒序排列小时
    sorted_hours = sorted(hourly.keys(), reverse=True)
    # 逐币统计连续在榜次数（按小时）
    for key, cur_syms in _ALL_RANKINGS.items():
        for sym in cur_syms:
            count = 0
            for hk in sorted_hours:
                if sym in hourly[hk].get(key, set()):
                    count += 1
                else:
                    break
            if count > 3:
                streak_map[(key, sym)] = count
except Exception:
    pass

# 读取模板并填入数据
with open(TPL_FILE) as f:
    page = f.read()

page = page.replace("{{TIME}}", now.strftime("%Y-%m-%d %H:%M"))
page = page.replace("{{NL_HTML}}", nl_html)
page = page.replace("{{LISTING_HTML}}", listing_html)
page = page.replace("{{HN_ROWS}}", hn_html)
page = page.replace("{{NEWS_ROWS}}", news_html)
page = page.replace("{{EX_VOL}}", _ex_panel("vol", "etab-vol", True, streaks=streak_map))
page = page.replace("{{EX_GAIN}}", _ex_panel("gain", "etab-gain", streaks=streak_map))
page = page.replace("{{EX_LOSS}}", _ex_panel("loss", "etab-loss", streaks=streak_map))

with open(OUT_FILE, "w") as f:
    f.write(page)
print(f"HTML written: {len(page)} bytes → {OUT_FILE}", flush=True)


# ──────────────────────────────────────────────
# 12. 快照 + 清理
# ──────────────────────────────────────────────

hn_snap = [{"t": s["title"], "s": s["score"], "c": s["descendants"], "ts": s["time"]} for s in HN_STORIES]
crypto_snap = [{"t": n["title"], "tag": n.get("tag", "")} for n in CT_NEWS]
snap_line = json.dumps({
    "ts": now.isoformat(),
    "btc": {"price": btc_p, "change": btc_c, "mcap": btc_mcap},
    "hn": hn_snap,
    "crypto": crypto_snap,
    "rankings": _ALL_RANKINGS,
}, ensure_ascii=False)

with open(SNAPL_FILE, "a") as f:
    f.write(snap_line + "\n")
print(f"Snapshot appended: BTC ${btc_p:,.0f} ({btc_c:+.2f}%)", flush=True)

# 清理超过 7 天的旧快照
try:
    with open(SNAPL_FILE) as _f:
        lines = _f.readlines()
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
            continue  # 坏行不再保留，防止文件无限膨胀
    if len(clean) < len(lines):
        with open(SNAPL_FILE, "w") as f:
            f.write("\n".join(clean) + "\n" if clean else "")
        print(f"Snapshot cleanup: {len(lines)} → {len(clean)} entries", flush=True)
except Exception:
    pass


# ──────────────────────────────────────────────
# 13. 推送 GitHub
# ──────────────────────────────────────────────
print("Pushing to GitHub...", flush=True)


def _gh_push(path, content, message, _retries=2):
    """通过 GitHub Contents API 更新文件，409 时自动重试。"""
    if not GITHUB_TOKEN:
        print(f"  {path}: SKIP (no token)", flush=True)
        return
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "User-Agent": "Mozilla/5.0",
               "Accept": "application/vnd.github.v3+json"}

    for attempt in range(_retries + 1):
        # 获取当前 SHA
        sha = None
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=8, context=_SSL_CTX) as r:
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
            with urllib.request.urlopen(req, timeout=10, context=_SSL_CTX) as r:
                sha_out = json.loads(r.read()).get("content", {}).get("sha", "")[:8]
                print(f"  {path}: OK ({sha_out})", flush=True)
                return
        except urllib.error.HTTPError as e:
            if e.code == 409 and attempt < _retries:
                print(f"  {path}: 409 conflict, retry {attempt+1}/{_retries}...", flush=True)
                time.sleep(1)
                continue
            print(f"  {path}: FAIL - {e}", flush=True)
            return
        except Exception as e:
            print(f"  {path}: FAIL - {e}", flush=True)
            return


with open(SNAPL_FILE) as _f:
    _snapl = _f.read()
with open(SNAP_HTML_FILE) as _f:
    _snap_html = _f.read()
msg = f"Dashboard update {now.strftime('%Y-%m-%d %H:%M')} UTC"
pushes = [
    ("betanews.html", page, msg),
    ("new-listings.json", json.dumps(deduped, indent=2, ensure_ascii=False), msg),
    ("dashboard-snapshots.jsonl", _snapl, msg),
    ("exchange-pairs-snapshot.json", json.dumps(current, indent=2), msg),
    ("snapshot.html", _snap_html, msg),
]
with ThreadPoolExecutor(max_workers=5) as ex_pool:
    list(ex_pool.map(lambda p: _gh_push(*p), pushes))

print("\n=== Done ===")
print(f"BTC: ${btc_p:,.0f} ({btc_c:+.2f}%)  Supply: {btc_supply:,.0f}")
print(f"Klines: {len(R)} valid  New: {len(new_pairs)}  Ann: {len(all_ann)}  HN: {len(HN_STORIES)}  CT: {len(CT_NEWS)}")

# 写入执行结果 log
_log_path = os.path.join(DATA_DIR, "gen_page.log")
try:
    _ex_status = {
        "Binance spot": len(bn_st), "Binance fut": len(bn_ft),
        "OKX spot": len(okx_st), "OKX fut": len(okx_ft),
        "Bitget spot": len(bg_st), "Bitget fut": len(bg_ft),
        "Bybit spot": len(bb_st), "Bybit fut": len(bb_ft),
    }
    _failed = [k for k, v in _ex_status.items() if v == 0]
    _ok = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    with open(_log_path, "w") as _lf:
        _lf.write(f"ts: {_ok}\n")
        _lf.write(f"btc: ${btc_p:,.0f} ({btc_c:+.2f}%)\n")
        _lf.write(f"tickers: {'OK' if not _failed else 'PARTIAL' if len(_failed) < 8 else 'FAIL'}\n")
        for _k, _v in _ex_status.items():
            _lf.write(f"  {_k}: {'FAIL' if _v == 0 else _v}\n")
        _lf.write(f"klines: {len(R)} valid  new: {len(new_pairs)}\n")
        _lf.write(f"ann: {len(all_ann)}  hn: {len(HN_STORIES)}  ct: {len(CT_NEWS)}\n")
except Exception:
    pass
