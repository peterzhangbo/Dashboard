import json, urllib.request, os, re, sys
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
SNAP_FILE = os.path.join(DATA_DIR, "exchange-pairs-snapshot.json")
NEW_FILE = os.path.join(DATA_DIR, "new-listings.json")
OUT_FILE = os.path.join(DATA_DIR, "betanews.html")
TPL_FILE = os.path.join(DATA_DIR, "template.html")

EXCLUDE = {"BTC","ETH","SOL","BNB","XRP","ADA","DOGE","AVAX","DOT","LINK","MATIC","POL","UNI","AAVE","LTC","BCH","ATOM","NEAR","FIL","APT","ARB","OP","SUI","SEI","TIA","INJ","FET","RENDER","RNDR","IMX","MKR","PEPE","SHIB","WIF","BONK","FLOKI","TRUMP","HYPE","USDC","USDT","BUSD","FDUSD","TUSD","DAI","USD1","USDD","FRAX","GUSD","PYUSD","USDG","USDS","PAX","BETH","BCC","BCHABC","BCHSV"}
FIAT = {"AUD","GBP","EUR","BRL","JPY","TRY","IDR","RUB","UAH","ZAR","PLN","NGN","ARS","COP","BIDR","BVND","BKRW"}
LEV_RE = re.compile(r'(UP|DOWN|BULL|BEAR)(USDT|BTC|ETH|BNB)$', re.IGNORECASE)

def fetch_json(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

def base_of(s):
    s2 = s.replace("-","")
    for q in ["USDT","USDC","USD","BUSD","FDUSD"]:
        if s2.endswith(q) and len(s2) > len(q): return s2[:-len(q)]
    return s2

def skip(sym):
    b = base_of(sym).upper()
    return b in EXCLUDE or b in FIAT or bool(LEV_RE.search(sym.upper()))

def fmt(v):
    if v >= 1e6: return "${:,.2f}M".format(v/1e6)
    if v >= 1e3: return "${:,.2f}K".format(v/1e3)
    return "${:,.2f}".format(v)

def turl(ex, sym, fut):
    b = base_of(sym)
    if ex == "bn":
        return "https://www.binance.com/en/futures/{}".format(sym) if fut else "https://www.binance.com/en/trade/{}_USDT".format(b)
    if ex == "okx":
        return "https://www.okx.com/trade-swap/{}-usdt-swap".format(b.lower()) if fut else "https://www.okx.com/trade-spot/{}-usdt".format(b.lower())
    if ex == "bg":
        return "https://www.bitget.com/futures/usdt/{}".format(sym) if fut else "https://www.bitget.com/spot/{}".format(sym)
    if ex == "bb":
        return "https://www.bybit.com/trade/usdt/{}".format(sym) if fut else "https://www.bybit.com/trade/spot/{}/USDT".format(b)

def top_syms(data, sym_k, vol_k, n=60, is_sw=False):
    items = []
    for d in data:
        sym = d.get(sym_k, "")
        if is_sw:
            if not sym.endswith("-USDT-SWAP"): continue
        elif sym_k == "instId":
            if not sym.endswith("-USDT"): continue
        else:
            if not sym.endswith("USDT"): continue
        if skip(sym): continue
        v = float(d.get(vol_k, 0) or 0)
        if v > 0: items.append((sym, v))
    items.sort(key=lambda x: -x[1])
    return [s for s, v in items[:n]]

print("Fetching tickers...", flush=True)
bn_st = fetch_json("https://api.binance.com/api/v3/ticker/24hr")
bn_ft = fetch_json("https://fapi.binance.com/fapi/v1/ticker/24hr")
okx_st = fetch_json("https://www.okx.com/api/v5/market/tickers?instType=SPOT").get("data", [])
okx_ft = fetch_json("https://www.okx.com/api/v5/market/tickers?instType=SWAP").get("data", [])
bg_st = fetch_json("https://api.bitget.com/api/v2/spot/market/tickers").get("data", [])
bg_ft = fetch_json("https://api.bitget.com/api/v2/mix/market/tickers?productType=USDT-FUTURES").get("data", [])
bb_st = fetch_json("https://api.bybit.com/v5/market/tickers?category=spot").get("result", {}).get("list", [])
bb_ft = fetch_json("https://api.bybit.com/v5/market/tickers?category=linear").get("result", {}).get("list", [])
print("Tickers done", flush=True)

S = {
    "bn_s": top_syms(bn_st, "symbol", "quoteVolume", 200),
    "bn_f": top_syms(bn_ft, "symbol", "quoteVolume", 100),
    "okx_s": top_syms(okx_st, "instId", "volCcy24h", 200),
    "okx_f": top_syms(okx_ft, "instId", "volCcy24h", 100, True),
    "bg_s": top_syms(bg_st, "symbol", "quoteVolume", 200),
    "bg_f": top_syms(bg_ft, "symbol", "usdtVolume", 100),
    "bb_s": top_syms(bb_st, "symbol", "turnover24h", 200),
    "bb_f": top_syms(bb_ft, "symbol", "turnover24h", 100),
}

total = sum(len(v) for v in S.values())
print(f"Candidate symbols: {total}", flush=True)

def ku(ex, sym):
    m = {
        "bn_s": "https://api.binance.com/api/v3/klines?symbol={}&interval=1h&limit=2",
        "bn_f": "https://fapi.binance.com/fapi/v1/klines?symbol={}&interval=1h&limit=2",
        "okx_s": "https://www.okx.com/api/v5/market/candles?instId={}&bar=1H&limit=2",
        "okx_f": "https://www.okx.com/api/v5/market/candles?instId={}&bar=1H&limit=2",
        "bg_s": "https://api.bitget.com/api/v2/spot/market/candles?symbol={}&granularity=1h&limit=2",
        "bg_f": "https://api.bitget.com/api/v2/mix/market/candles?symbol={}&granularity=1H&productType=USDT-FUTURES&limit=2",
        "bb_s": "https://api.bybit.com/v5/market/kline?category=spot&symbol={}&interval=60&limit=2",
        "bb_f": "https://api.bybit.com/v5/market/kline?category=linear&symbol={}&interval=60&limit=2",
    }
    return m[ex].format(sym)

def fk(ex, sym):
    try:
        d = fetch_json(ku(ex, sym))
        if ex.startswith("okx"): kl = d.get("data", [])
        elif ex.startswith("bb"): kl = list(reversed(d.get("result", {}).get("list", [])))
        elif ex.startswith("bg"): kl = d.get("data", [])
        else: kl = d
        if len(kl) < 2: return (sym, None, None)
        pc = float(kl[-2][4]); cc = float(kl[-1][4])
        cv = float(kl[-1][5]); cq = float(kl[-1][7]) if len(kl[-1]) > 7 else 0
        if pc <= 0: return (sym, None, None)
        vol = cq if cq > 0 else cv * cc
        return (sym, (cc - pc) / pc * 100, vol)
    except:
        return (sym, None, None)

print("Fetching klines...", flush=True)
tasks = []
for ex in S:
    for s in S[ex]: tasks.append((ex, s))
R = {}
done = 0
with ThreadPoolExecutor(max_workers=20) as pool:
    futs = {pool.submit(fk, ex, s): (ex, s) for ex, s in tasks}
    for f in as_completed(futs):
        ex, s = futs[f]; sym, p, v = f.result()
        R[(ex, sym)] = (p, v)
        done += 1
        if done % 200 == 0: print(f"  Klines: {done}/{len(tasks)}", flush=True)
print(f"Klines done: {done}", flush=True)

def rk(ex, syms, by="vol", n=3):
    items = []
    for s in syms:
        p, v = R.get((ex, s), (None, None))
        if v is None or p is None or v <= 0: continue
        items.append((s, p, v))
    if by == "vol": items.sort(key=lambda x: -x[2])
    elif by == "g": items.sort(key=lambda x: -x[1])
    elif by == "l": items.sort(key=lambda x: x[1])
    return items[:n]

print("Fetching announcements...", flush=True)
bn_ann = fetch_json("https://www.binance.com/bapi/composite/v1/public/cms/article/list/query?type=1&catalogId=48&pageNo=1&pageSize=5")
bb_ann = fetch_json("https://api.bybit.com/v5/announcements/index?type=new_crypto&locale=en-US")
okx_ann = fetch_json("https://www.okx.com/priapi/v1/assistant/service-center/home/featured-announcements?defi=false")
bg_ann = fetch_json("https://api.bitget.com/api/v2/public/annoucements?language=zh_CN&annType=coin_listings&limit=5")

btc_d = [d for d in bn_st if d["symbol"] == "BTCUSDT"][0]
btc_p = float(btc_d["lastPrice"]); btc_c = float(btc_d["priceChangePercent"])

now = datetime.now(timezone.utc)
def ft_ts(ts):
    ts = int(ts)
    if ts > 1e12: ts = ts // 1000
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%m-%d %H:%M")

def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

all_ann = []
for a in bn_ann["data"]["catalogs"][0]["articles"][:5]:
    mkt = "合约" if "Futures" in a["title"] or "Perpetual" in a["title"] else "现货"
    all_ann.append(("Binance", "https://www.binance.com/en/support/announcement/{}".format(a["code"]), a["title"], a["releaseDate"], ft_ts(a["releaseDate"]), mkt))
for a in okx_ann.get("data", {}).get("announcements", [])[:5]:
    all_ann.append(("OKX", "https://www.okx.com{}".format(a["url"]), a["title"], int(a["publishTime"]) * 1000, ft_ts(a["publishTime"]), "合约"))
for a in bg_ann.get("data", [])[:5]:
    ts = int(a["cTime"]) if isinstance(a["cTime"], str) else a["cTime"]
    mkt = "合约" if "合约" in a["annTitle"] or "永续" in a["annTitle"] else "现货"
    all_ann.append(("Bitget", a["annUrl"], a["annTitle"], ts, ft_ts(ts), mkt))
for a in bb_ann["result"]["list"][:5]:
    mkt = "合约" if "Perpetual" in a["title"] or "leverage" in a["title"] else "现货"
    all_ann.append(("Bybit", a["url"], a["title"], a["publishTime"], ft_ts(a["publishTime"]), mkt))
all_ann.sort(key=lambda x: -x[3])

if os.path.exists(NEW_FILE):
    with open(NEW_FILE) as f: deduped = json.load(f)
else: deduped = []
now_ts = int(now.timestamp())
deduped = [p for p in deduped if p.get("discovered", 0) > now_ts - 12 * 3600]

listing_html = ""
for i, (ex, url, title, ts, time_str, mkt) in enumerate(all_ann[:8]):
    tag_cls = {"Binance": "tag-ex", "OKX": "tag-crypto", "Bitget": "tag-defi", "Bybit": "tag-pol"}[ex]
    listing_html += '<div class="news-row"><span class="news-n">{}</span><div class="news-body"><a class="news-t" href="{}" target="_blank">{}</a><div class="news-meta"><span class="tag {}">{} {}</span> {}</div></div></div>\n'.format(i+1, url, esc(title), tag_cls, ex, mkt, time_str)

nl_html = ""
for p in deduped[:10]:
    ex_name = {"bn": "Binance", "okx": "OKX", "bg": "Bitget", "bb": "Bybit"}[p["exchange"]]
    mkt = "永续" if p["market"] == "fut" else "现货"
    url = turl(p["exchange"], p["symbol"], p["market"] == "fut")
    chg = p.get("change", 0); vol = p.get("volume", 0)
    cls = "up" if chg >= 0 else "down"; sg = "+" if chg >= 0 else ""
    ts_str = datetime.fromtimestamp(p["discovered"], tz=timezone.utc).strftime("%m-%d %H:%M")
    nl_html += '<div class="nl-item" data-ts="{}"><span class="nl-pair"><a href="{}" target="_blank">{}</a></span><span class="nl-chg {}">{}{:.2f}%</span><span class="nl-vol">{}</span><span class="nl-right"><span class="nl-ex">{}</span><span class="nl-type">{}</span><span class="nl-time">{}</span></span></div>\n'.format(
        p["discovered"], url, p["symbol"], cls, sg, chg, fmt(vol), ex_name, mkt, ts_str)

ex_keys = {"Binance": "bn", "OKX": "okx", "Bitget": "bg", "Bybit": "bb"}
def mk_ex_panel(cat, tid, active=False):
    act = " active" if active else ""
    h = '  <div class="ex-panel{}" id="{}">\n    <div class="ex-dual">\n'.format(act, tid)
    for mkt, label in [("spot", "现货"), ("fut", "永续合约")]:
        is_fut = mkt == "fut"
        h += '      <div class="ex-side"><div class="ex-side-label">{}</div>\n        <div class="ex-grid">\n'.format(label)
        for en, ec in ex_keys.items():
            ex_s = {"bn": "bn_f" if is_fut else "bn_s", "okx": "okx_f" if is_fut else "okx_s",
                    "bg": "bg_f" if is_fut else "bg_s", "bb": "bb_f" if is_fut else "bb_s"}[ec]
            raw = rk(ex_s, S[ex_s], by={"vol": "vol", "gain": "g", "loss": "l"}[cat], n=3)
            h += '          <div class="ex-box"><div class="ex-box-name">{}</div>\n'.format(en)
            for pair, pct, vol in raw:
                dp = pair if is_fut else "{}/USDT".format(base_of(pair))
                if is_fut and ec == "okx":
                    dp = base_of(pair.replace("-USDT-SWAP", "")) + "USDT"
                url = turl(ec, pair, is_fut)
                c = "up" if pct >= 0 else "down"
                sg = "+" if pct >= 0 else ""
                if cat == "vol":
                    arrow = "▲" if pct >= 0 else "▼"
                    h += '            <div class="ex-item"><div class="ex-item-pair"><a href="{}" target="_blank">{}</a></div><div class="ex-item-data"><b>{}</b> <span class="{}" style="font-size:10px;opacity:.5">{}</span></div></div>\n'.format(url, dp, fmt(vol), c, arrow)
                else:
                    h += '            <div class="ex-item"><div class="ex-item-pair"><a href="{}" target="_blank">{}</a></div><div class="ex-item-data"><span class="{}" style="font-weight:700;font-size:14px">{}{:.2f}%</span> <span style="font-size:11px;color:var(--t3)">{}</span></div></div>\n'.format(url, dp, c, sg, pct, fmt(vol))
            h += '          </div>\n'
        h += '        </div>\n      </div>\n'
    h += '    </div>\n  </div>\n'
    return h

with open(OUT_FILE) as f:
    old = f.read()

hn_match = re.search(r'(<!-- Hacker News Tab -->[\s\S]*?</div>\s*</div>\s*</div>)', old)
hn_html = hn_match.group(1) if hn_match and hn_match.group(1).count("</div>") >= 3 else ""

news_match = re.search(r'(<!-- 行业热点 Tab -->[\s\S]*?</div>\s*</div>\s*</div>)', old)
news_html = news_match.group(1) if news_match and news_match.group(1).count("</div>") >= 3 else ""

# Read template
with open(TPL_FILE) as f:
    page = f.read()

page = page.replace("{{TIME}}", now.strftime("%Y-%m-%d %H:%M"))
page = page.replace("{{BTC_PRICE}}", "{:,.0f}".format(btc_p))
page = page.replace("{{BTC_CHG_CLS}}", "up" if btc_c >= 0 else "down")
page = page.replace("{{BTC_ARROW}}", "▲" if btc_c >= 0 else "▼")
page = page.replace("{{BTC_CHG_VAL}}", "{:.2f}".format(abs(btc_c)))
page = page.replace("{{BTC_MCAP}}", "{:.2f}".format(btc_p * 19850000 / 1e12))
page = page.replace("{{NL_HTML}}", nl_html.strip() if nl_html.strip() else '<div style="padding:8px;color:var(--t3);font-size:11px">12h 内暂无新增交易对</div>')
page = page.replace("{{LISTING_HTML}}", listing_html)
page = page.replace("{{HN_HTML}}", hn_html if hn_html else '<div class="tab-panel" id="tab-hn"><div class="news-list" id="hn-list"><div class="ex-row" style="color:var(--t3)">暂无数据</div></div></div>')
page = page.replace("{{NEWS_HTML}}", news_html if news_html else '<div class="tab-panel" id="tab-news"><div class="news-list"><div class="ex-row" style="color:var(--t3)">暂无数据</div></div></div>')
page = page.replace("{{EX_VOL}}", mk_ex_panel("vol", "etab-vol", True))
page = page.replace("{{EX_GAIN}}", mk_ex_panel("gain", "etab-gain"))
page = page.replace("{{EX_LOSS}}", mk_ex_panel("loss", "etab-loss"))

with open(OUT_FILE, "w") as f:
    f.write(page)
print(f"Done: {len(page)} bytes", flush=True)
