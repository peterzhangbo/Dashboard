#!/usr/bin/env python3
"""Phase 2: Fetch 1h klines and announcements"""
import json, urllib.request, urllib.parse, os, re, time, base64
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
P1 = os.path.join(DATA_DIR, "phase1.json")
P2 = os.path.join(DATA_DIR, "phase2.json")
NEW_FILE = os.path.join(DATA_DIR, "new-listings.json")

with open(P1) as f:
    d = json.load(f)

def fetch_json(url, timeout=8):
    req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

def safe_float(v, default=0.0):
    try: return float(v)
    except: return default

EXCLUDE = {"BTC","ETH","SOL","BNB","XRP","ADA","DOGE","AVAX","DOT","LINK","MATIC","POL","UNI","AAVE","LTC","BCH","ATOM","NEAR","FIL","APT","ARB","OP","SUI","SEI","TIA","INJ","FET","RENDER","RNDR","IMX","MKR","PEPE","SHIB","WIF","BONK","FLOKI","TRUMP","HYPE","USDC","USDT","BUSD","FDUSD","TUSD","DAI","USD1","USDD","FRAX","GUSD","PYUSD","USDG","USDS","PAX","BETH","BCC","BCHABC","BCHSV"}
FIAT = {"AUD","GBP","EUR","BRL","JPY","TRY","IDR","RUB","UAH","ZAR","PLN","NGN","ARS","COP","BIDR","BVND","BKRW"}
LEV_RE = re.compile(r'(UP|DOWN|BULL|BEAR)(USDT|BTC|ETH|BNB)$', re.IGNORECASE)

def base_of(s):
    s2 = s.replace("-","")
    for q in ["USDT","USDC","USD","BUSD","FDUSD"]:
        if s2.endswith(q) and len(s2) > len(q): return s2[:-len(q)]
    return s2

def skip(sym):
    b = base_of(sym).upper()
    if b in EXCLUDE or b in FIAT: return True
    if LEV_RE.search(sym.upper()): return True
    return False

def fetch_kline(ex, sym, fut):
    try:
        esym = urllib.parse.quote(sym)  # URL 编码，处理中文等特殊字符
        if ex == "bn":
            ep = "fapi" if fut else "api"
            if fut:
                url = f"https://fapi.binance.com/fapi/v1/klines?symbol={esym}&interval=1h&limit=2"
            else:
                url = f"https://api.binance.com/api/v3/klines?symbol={esym}&interval=1h&limit=2"
            data = fetch_json(url)
            if len(data) < 2: return None
            prev_c = safe_float(data[-2][4]); last_c = safe_float(data[-1][4])
            vol = safe_float(data[-1][7])
            if vol <= 0: vol = safe_float(data[-1][5]) * last_c
            if prev_c <= 0 or vol <= 0: return None
            return (round((last_c - prev_c)/prev_c*100, 2), round(vol, 2))
        elif ex == "okx":
            inst = esym
            url = f"https://www.okx.com/api/v5/market/candles?instId={inst}&bar=1H&limit=2"
            data = fetch_json(url).get("data",[])
            if len(data) < 2: return None
            prev_c = safe_float(data[-2][4]); last_c = safe_float(data[-1][4])
            vol = safe_float(data[-1][7])
            if vol <= 0: vol = safe_float(data[-1][5]) * last_c
            if prev_c <= 0 or vol <= 0: return None
            return (round((last_c - prev_c)/prev_c*100, 2), round(vol, 2))
        elif ex == "bg":
            if fut:
                url = f"https://api.bitget.com/api/v2/mix/market/candles?symbol={esym}&granularity=1H&productType=USDT-FUTURES&limit=2"
            else:
                url = f"https://api.bitget.com/api/v2/spot/market/candles?symbol={esym}&granularity=1h&limit=2"
            data = fetch_json(url).get("data",[])
            if len(data) < 2: return None
            prev_c = safe_float(data[-2][4]); last_c = safe_float(data[-1][4])
            vol = safe_float(data[-1][7])
            if vol <= 0: vol = safe_float(data[-1][5]) * last_c
            if prev_c <= 0 or vol <= 0: return None
            return (round((last_c - prev_c)/prev_c*100, 2), round(vol, 2))
        elif ex == "bb":
            cat = "linear" if fut else "spot"
            url = f"https://api.bybit.com/v5/market/kline?category={cat}&symbol={esym}&interval=60&limit=2"
            data = fetch_json(url).get("result",{}).get("list",[])
            data = list(reversed(data))
            if len(data) < 2: return None
            prev_c = safe_float(data[-2][4]); last_c = safe_float(data[-1][4])
            vol = safe_float(data[-1][7])
            if vol <= 0: vol = safe_float(data[-1][5]) * last_c
            if prev_c <= 0 or vol <= 0: return None
            return (round((last_c - prev_c)/prev_c*100, 2), round(vol, 2))
    except:
        return None

def get_listing_time(ex, sym, fut):
    """查询币对在指定交易所的上线时间（秒时间戳），失败返回 0。"""
    try:
        esym = urllib.parse.quote(sym)  # URL 编码
        if ex == "bn":
            url = f"https://fapi.binance.com/fapi/v1/klines?symbol={esym}&interval=1d&startTime=0&limit=1" if fut \
                else f"https://api.binance.com/api/v3/klines?symbol={esym}&interval=1d&startTime=0&limit=1"
            return int(fetch_json(url)[0][0]) // 1000
        if ex == "okx":
            inst_type = "SWAP" if fut else "SPOT"
            return int(fetch_json(
                f"https://www.okx.com/api/v5/public/instruments?instType={inst_type}&instId={esym}"
            )["data"][0]["listTime"]) // 1000
        if ex == "bg":
            if fut:
                return int(fetch_json(
                    f"https://api.bitget.com/api/v2/mix/market/contracts?productType=USDT-FUTURES&symbol={esym}"
                )["data"][0]["openTime"]) // 1000
            else:
                for s in fetch_json("https://api.bitget.com/api/v2/spot/public/symbols").get("data", []):
                    if s.get("symbol") == sym:  # 未编码，用于比较
                        return int(s.get("openTime", 0)) // 1000
                return 0
        if ex == "bb":
            if fut:
                return int(fetch_json(
                    f"https://api.bybit.com/v5/market/instruments-info?category=linear&symbol={esym}"
                )["result"]["list"][0]["launchTime"]) // 1000
            else:
                return int(fetch_json(
                    f"https://api.bybit.com/v5/market/kline?category=spot&symbol={esym}&start=1500000000000&interval=D&limit=1"
                )["result"]["list"][0][0]) // 1000
    except:
        return 0
    return 0
    return None

# Build task list - only top 100 per category to stay within time
tasks = []
for sym in d["bn_spot_top"][:100]: tasks.append(("bn", sym, False))
for sym in d["bn_fut_top"][:100]: tasks.append(("bn", sym, True))
for sym in d["okx_spot_top"][:100]: tasks.append(("okx", sym, False))
for sym in d["okx_fut_top"][:100]: tasks.append(("okx", sym, True))
for sym in d["bg_spot_top"][:100]: tasks.append(("bg", sym, False))
for sym in d["bg_fut_top"][:100]: tasks.append(("bg", sym, True))
for sym in d["bb_spot_top"][:100]: tasks.append(("bb", sym, False))
for sym in d["bb_fut_top"][:100]: tasks.append(("bb", sym, True))

print(f"Phase 2: Fetching {len(tasks)} klines...")

results = {}
def do_fetch(t):
    ex, sym, fut = t
    r = fetch_kline(ex, sym, fut)
    return (ex, sym, fut, r)

with ThreadPoolExecutor(25) as pool:
    futs_map = {pool.submit(do_fetch, t): t for t in tasks}
    done = 0
    for f in as_completed(futs_map):
        done += 1
        if done % 200 == 0: print(f"  Progress: {done}/{len(tasks)}")
        try:
            ex, sym, fut, r = f.result()
            if r: results[f"{ex}|{sym}|{fut}"] = r
        except: pass

print(f"  Valid kline results: {len(results)}")

# New pair klines
new_pairs = d.get("new_pairs", [])
current = d.get("current", {})
now_ts = int(time.time())
cutoff = now_ts - 12 * 3600

# Load existing new-listings
existing_new = []
try:
    with open(NEW_FILE) as f: existing_new = json.load(f)
except: pass

# 给缺少 listing_time 的旧条目补查上线时间
for x in existing_new:
    if "listing_time" not in x:
        ex_code = x.get("ex", x.get("exchange", ""))
        sym_name = x.get("sym", x.get("symbol", ""))
        is_fut = x.get("fut", x.get("market", "") == "fut")
        lt = get_listing_time(ex_code, sym_name, is_fut)
        if lt > 0:
            x["listing_time"] = lt
        else:
            x.setdefault("listing_time", x.get("ts", x.get("discovered", 0)))

# 按 listing_time 过滤 12h 窗口
existing_new = [x for x in existing_new
                if x.get("listing_time", x.get("ts", x.get("discovered", 0))) > cutoff]
existing_syms = {(x.get("ex", x.get("exchange", "")), x.get("sym", x.get("symbol", ""))) for x in existing_new}

new_listings = list(existing_new)
for sym in new_pairs:
    ex_found = None; is_fut = False
    if sym in current.get("bn_spot",[]): ex_found="bn"
    elif sym in current.get("bn_fut",[]): ex_found="bn"; is_fut=True
    elif sym in current.get("okx_spot",[]): ex_found="okx"
    elif sym in current.get("okx_fut",[]): ex_found="okx"; is_fut=True
    elif sym in current.get("bg_spot",[]): ex_found="bg"
    elif sym in current.get("bg_fut",[]): ex_found="bg"; is_fut=True
    elif sym in current.get("bb_spot",[]): ex_found="bb"
    elif sym in current.get("bb_fut",[]): ex_found="bb"; is_fut=True
    if not ex_found: continue
    if (ex_found, sym) in existing_syms: continue
    lt = get_listing_time(ex_found, sym, is_fut)
    if lt == 0 or lt < cutoff:
        continue                     # 查不到或已超 12h → 跳过
    r = fetch_kline(ex_found, sym, is_fut)
    new_listings.append({"sym":sym,"ex":ex_found,"fut":is_fut,"listing_time":lt,
                         "pct":round(r[0],2) if r else 0,"vol":round(r[1],2) if r else 0})

with open(NEW_FILE,"w") as f: json.dump(new_listings,f,indent=2,ensure_ascii=False)

# Announcements
print("Fetching announcements...")
anns = []

def translate_title(t):
    if not t: return t
    ascii_c = sum(1 for c in t if ord(c)<128)
    if ascii_c < len(t)*0.6: return t
    m = {"New Listing":"新上线","Will List":"即将上线","Lists":"上线","Listed":"已上线",
         "Launch":"上线","Launched":"已上线","Trading":"交易","Perpetual":"永续合约",
         "Futures":"合约","Contract":"合约","Spot":"现货","Margin":"杠杆",
         "Delisting":"下架","Delist":"下架","Maintenance":"维护","Upgrade":"升级",
         "Update":"更新","Announcement":"公告","Notice":"通知","Important":"重要",
         "Support":"支持","Added":"新增","Available":"开放","Token":"代币",
         "Airdrop":"空投","Reward":"奖励","Promotion":"活动","Campaign":"活动",
         "Wallet":"钱包","Leverage":"杠杆","pairs":"交易对","pair":"交易对",
         "Zone":"专区","Innovation":"创新","Assessment":"评估"}
    r = t
    for k,v in m.items(): r = r.replace(k,v)
    return r

try:
    bd = fetch_json("https://www.binance.com/bapi/composite/v1/public/cms/article/list/query?type=1&catalogId=48&pageNo=1&pageSize=5")
    for a in (bd.get("data",{}).get("catalogs",[{}])[0].get("articles",[]) or [])[:5]:
        t = a.get("title","")
        # 跳过杠杆/保证金交易类公告
        if any(k in t for k in ["杠杆","Margin","借贷","借入","借出","Leverage"]):
            continue
        ts = a.get("releaseDate",0)
        if ts > 1e12: ts //= 1000
        anns.append({"title":translate_title(t),"url":f"https://www.binance.com/en/support/announcement/{a.get('code','')}","ts":ts,"src":"Binance"})
    print(f"  Binance: {sum(1 for a in anns if a['src']=='Binance')}")
except Exception as e: print(f"  Binance FAIL: {e}")

try:
    od = fetch_json("https://www.okx.com/priapi/v1/assistant/service-center/home/featured-announcements?defi=false")
    for a in (od.get("data",[]) or [])[:5]:
        t = a.get("title","") or a.get("sTitle","")
        if any(k in t for k in ["杠杆","Margin","借贷","借入","借出","Leverage"]):
            continue
        ts = int(a.get("pTime", a.get("ts",0)))
        if ts > 1e12: ts //= 1000
        anns.append({"title":translate_title(t),"url":a.get("url","") or f"https://www.okx.com/help/{a.get('id','')}","ts":ts,"src":"OKX"})
    print(f"  OKX: {sum(1 for a in anns if a['src']=='OKX')}")
except Exception as e: print(f"  OKX FAIL: {e}")

try:
    gd = fetch_json("https://api.bitget.com/api/v2/public/annoucements?language=zh_CN&annType=coin_listings&limit=5")
    for a in (gd.get("data",[]) or [])[:5]:
        t = a.get("annTitle","") or a.get("title","")
        if any(k in t for k in ["杠杆","Margin","借贷","借入","借出","Leverage"]):
            continue
        ts = int(a.get("cTime", a.get("ts",0)))
        if ts > 1e12: ts //= 1000
        anns.append({"title":translate_title(t),"url":a.get("annUrl","") or f"https://www.bitget.com/zh-CN/support/articles/{a.get('annId','')}","ts":ts,"src":"Bitget"})
    print(f"  Bitget: {sum(1 for a in anns if a['src']=='Bitget')}")
except Exception as e: print(f"  Bitget FAIL: {e}")

try:
    byd = fetch_json("https://api.bybit.com/v5/announcements/index?type=new_crypto&locale=en-US")
    for a in (byd.get("result",{}).get("list",[]) or [])[:5]:
        t = a.get("title","")
        if any(k in t.lower() for k in ["margin","leverage","借贷","杠杆"]):
            continue
        ts = a.get("publishTime","0")
        try: ts = int(ts)
        except: ts = 0
        if ts > 1e12: ts //= 1000
        anns.append({"title":translate_title(t),"url":a.get("url",""),"ts":ts,"src":"Bybit"})
    print(f"  Bybit: {sum(1 for a in anns if a['src']=='Bybit')}")
except Exception as e: print(f"  Bybit FAIL: {e}")

anns.sort(key=lambda x:-x["ts"])
anns = anns[:8]

# Save phase2
out = {"results": results, "new_listings": new_listings, "anns": anns}
with open(P2, "w") as f:
    json.dump(out, f, ensure_ascii=False)
print(f"Phase 2 done. Klines={len(results)} NewListings={len(new_listings)} Announcements={len(anns)}")
