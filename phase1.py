#!/usr/bin/env python3
"""Phase 1: Fetch tickers, BTC data, diff detection"""
import json, urllib.request, os, re, time
from datetime import datetime, timezone

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
SNAP_FILE = os.path.join(DATA_DIR, "exchange-pairs-snapshot.json")
NEW_FILE  = os.path.join(DATA_DIR, "new-listings.json")
PHASE1_OUT = os.path.join(DATA_DIR, "phase1.json")

def fetch_json(url, timeout=10):
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

print("Phase 1: Fetching tickers...")

bn_st=bn_ft=okx_st=okx_ft=bg_st=bg_ft=bb_st=bb_ft=[]

try:
    bn_st = fetch_json("https://api.binance.com/api/v3/ticker/24hr")
    print(f"  Binance spot: {len(bn_st)}")
except Exception as e: print(f"  Binance spot FAIL: {e}")

try:
    bn_ft = fetch_json("https://fapi.binance.com/fapi/v1/ticker/24hr")
    print(f"  Binance fut: {len(bn_ft)}")
except Exception as e: print(f"  Binance fut FAIL: {e}")

try:
    okx_st = fetch_json("https://www.okx.com/api/v5/market/tickers?instType=SPOT").get("data",[])
    print(f"  OKX spot: {len(okx_st)}")
except Exception as e: print(f"  OKX spot FAIL: {e}")

try:
    okx_ft = fetch_json("https://www.okx.com/api/v5/market/tickers?instType=SWAP").get("data",[])
    print(f"  OKX fut: {len(okx_ft)}")
except Exception as e: print(f"  OKX fut FAIL: {e}")

try:
    bg_st = fetch_json("https://api.bitget.com/api/v2/spot/market/tickers").get("data",[])
    print(f"  Bitget spot: {len(bg_st)}")
except Exception as e: print(f"  Bitget spot FAIL: {e}")

try:
    bg_ft = fetch_json("https://api.bitget.com/api/v2/mix/market/tickers?productType=USDT-FUTURES").get("data",[])
    print(f"  Bitget fut: {len(bg_ft)}")
except Exception as e: print(f"  Bitget fut FAIL: {e}")

try:
    bb_st = fetch_json("https://api.bybit.com/v5/market/tickers?category=spot").get("result",{}).get("list",[])
    print(f"  Bybit spot: {len(bb_st)}")
except Exception as e: print(f"  Bybit spot FAIL: {e}")

try:
    bb_ft = fetch_json("https://api.bybit.com/v5/market/tickers?category=linear").get("result",{}).get("list",[])
    print(f"  Bybit fut: {len(bb_ft)}")
except Exception as e: print(f"  Bybit fut FAIL: {e}")

# BTC
btc_price = 0; btc_chg = 0
for t in bn_st:
    if t.get("symbol") == "BTCUSDT":
        btc_price = safe_float(t.get("lastPrice",0))
        btc_chg = safe_float(t.get("priceChangePercent",0))
        break
btc_mcap = btc_price * 19_860_000

# Build sets
def bn_s(): return {t["symbol"] for t in bn_st if t.get("symbol","").endswith("USDT") and not skip(t["symbol"])}
def bn_f(): return {t["symbol"] for t in bn_ft if t.get("symbol","").endswith("USDT") and not skip(t["symbol"])}
def okx_s():
    r=set()
    for t in okx_st:
        s=t.get("instId","")
        if s.endswith("-USDT") and not skip(s.replace("-","")): r.add(s)
    return r
def okx_f():
    r=set()
    for t in okx_ft:
        s=t.get("instId","")
        if s.endswith("-USDT-SWAP") and not skip(s.replace("-","").replace("SWAP","")): r.add(s)
    return r
def bg_s(): return {t["symbol"] for t in bg_st if t.get("symbol","").endswith("USDT") and not skip(t["symbol"])}
def bg_f(): return {t["symbol"] for t in bg_ft if t.get("symbol","").endswith("USDT") and not skip(t["symbol"])}
def bb_s(): return {t["symbol"] for t in bb_st if t.get("symbol","").endswith("USDT") and not skip(t["symbol"])}
def bb_f(): return {t["symbol"] for t in bb_ft if t.get("symbol","").endswith("USDT") and not skip(t["symbol"])}

current = {"bn_spot":sorted(bn_s()),"bn_fut":sorted(bn_f()),"okx_spot":sorted(okx_s()),"okx_fut":sorted(okx_f()),
           "bg_spot":sorted(bg_s()),"bg_fut":sorted(bg_f()),"bb_spot":sorted(bb_s()),"bb_fut":sorted(bb_f())}
all_current = set()
for v in current.values(): all_current.update(v)

# Diff
old_snap = {}
try:
    with open(SNAP_FILE) as f: old_snap = json.load(f)
except: pass
old_all = set()
for v in old_snap.values(): old_all.update(v)

new_pairs = sorted(all_current - old_all)
print(f"New pairs: {len(new_pairs)}")

# Top syms for klines
def top_syms(tickers, key_sym, key_vol, n):
    items = []
    for t in tickers:
        sym = t.get(key_sym,""); vol = safe_float(t.get(key_vol,0))
        if skip(sym): continue
        items.append((sym,vol))
    items.sort(key=lambda x:-x[1])
    return [x[0] for x in items[:n]]

def okx_top(tickers, n):
    items=[]
    for t in tickers:
        sym=t.get("instId",""); vol=safe_float(t.get("volCcy24h",0))
        bs=sym.replace("-","").replace("SWAP","")
        if skip(bs): continue
        items.append((sym,vol))
    items.sort(key=lambda x:-x[1])
    return [x[0] for x in items[:n]]

def bg_top(tickers, n):
    items=[]
    for t in tickers:
        sym=t.get("symbol",""); vol=safe_float(t.get("quoteVolume",t.get("usdtVolume",0)))
        if skip(sym): continue
        items.append((sym,vol))
    items.sort(key=lambda x:-x[1])
    return [x[0] for x in items[:n]]

def bb_top(tickers, n):
    items=[]
    for t in tickers:
        sym=t.get("symbol",""); vol=safe_float(t.get("quoteVolume",t.get("turnover24h",0)))
        if skip(sym): continue
        items.append((sym,vol))
    items.sort(key=lambda x:-x[1])
    return [x[0] for x in items[:n]]

# Save phase1 data
out = {
    "current": current,
    "new_pairs": new_pairs,
    "btc": {"price": btc_price, "chg": round(btc_chg,2), "mcap": round(btc_mcap,0)},
    "bn_spot_top": top_syms(bn_st, "symbol", "quoteVolume", 200),
    "bn_fut_top": top_syms(bn_ft, "symbol", "quoteVolume", 100),
    "okx_spot_top": okx_top(okx_st, 200),
    "okx_fut_top": okx_top(okx_ft, 100),
    "bg_spot_top": bg_top(bg_st, 200),
    "bg_fut_top": bg_top(bg_ft, 100),
    "bb_spot_top": bb_top(bb_st, 200),
    "bb_fut_top": bb_top(bb_ft, 100),
    "ts": int(time.time()),
    "now_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
}

with open(PHASE1_OUT, "w") as f:
    json.dump(out, f)
with open(SNAP_FILE, "w") as f:
    json.dump(current, f)

print(f"Phase 1 done. BTC=${btc_price:,.0f} ({btc_chg:+.2f}%)  New={len(new_pairs)}")
