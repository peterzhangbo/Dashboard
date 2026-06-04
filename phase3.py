#!/usr/bin/env python3
"""Phase 3: Generate HTML and push to GitHub"""
import json, urllib.request, os, re, time, base64
from datetime import datetime, timezone

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
HTML_FILE = os.path.join(DATA_DIR, "betanews.html")
SNAPL_FILE = os.path.join(DATA_DIR, "dashboard-snapshots.jsonl")
P1_FILE = os.path.join(DATA_DIR, "phase1.json")
P2_FILE = os.path.join(DATA_DIR, "phase2.json")

GITHUB_REPO = "peterzhangbo/Dashboard"

with open(P1_FILE) as f: p1 = json.load(f)
with open(P2_FILE) as f: p2 = json.load(f)

btc = p1["btc"]
results = p2["results"]
new_listings = p2["new_listings"]
anns = p2["anns"]
now_utc = p1["now_utc"]
ts_now = p1["ts"]

def safe_float(v, default=0.0):
    try: return float(v)
    except: return default

def base_of(s):
    s2 = s.replace("-","")
    for q in ["USDT","USDC","USD","BUSD","FDUSD"]:
        if s2.endswith(q) and len(s2) > len(q): return s2[:-len(q)]
    return s2

def fp(pair, fut, ex=""):
    if fut and ex == "okx":
        return pair.replace("-USDT-SWAP","") + "USDT"
    return pair

def turl(ex, sym, fut):
    b = base_of(sym)
    if ex == "bn":
        return f"https://www.binance.com/en/futures/{sym}" if fut else f"https://www.binance.com/en/trade/{b}_USDT"
    if ex == "okx":
        if fut: return f"https://www.okx.com/trade-swap/{b.lower()}-usdt-swap"
        return f"https://www.okx.com/trade-spot/{b.lower()}-usdt"
    if ex == "bg":
        return f"https://www.bitget.com/futures/usdt/{sym}" if fut else f"https://www.bitget.com/spot/{sym}"
    if ex == "bb":
        return f"https://www.bybit.com/trade/usdt/{sym}" if fut else f"https://www.bybit.com/trade/spot/{b}/USDT"
    return "#"

def fmt(v):
    if v >= 1e6: return f"${v/1e6:,.2f}M"
    if v >= 1e3: return f"${v/1e3:,.2f}K"
    return f"${v:,.2f}"

# Read existing HTML for HN and news
old = ""
try:
    with open(HTML_FILE) as f: old = f.read()
except: pass

hn_match = re.search(r'(<!-- Hacker News Tab -->.*?</div>\s*</div>\s*</div>)', old, re.DOTALL)
hn_html = hn_match.group(1) if hn_match else '<!-- Hacker News Tab -->\n  <div class="tab-panel" id="tab-hn">\n    <div class="news-list" id="hn-list">\n<div class="news-row"><span class="news-n">1</span><div class="news-body"><a class="news-t" href="#" target="_blank">HN数据加载中...</a><div class="news-meta"><span class="tag tag-defi">科技</span> -</div></div><div class="news-heat">-</div></div>\n    </div>\n  </div>'
if not re.search(r'</div>\s*</div>\s*</div>\s*$', hn_html.strip()):
    hn_html = hn_html.rstrip() + '\n    </div>\n  </div>'

news_match = re.search(r'(<!-- 行业热点 Tab -->.*?</div>\s*</div>\s*</div>)', old, re.DOTALL)
news_html = news_match.group(1) if news_match else '<!-- 行业热点 Tab -->\n  <div class="tab-panel" id="tab-news">\n    <div class="news-list">\n<div class="news-row"><span class="news-n">1</span><div class="news-body"><a class="news-t" href="#" target="_blank">新闻数据加载中...</a><div class="news-meta"><span class="tag tag-crypto">综合</span> -</div></div></div>\n    </div>\n  </div>'
if not re.search(r'</div>\s*</div>\s*</div>\s*$', news_html.strip()):
    news_html = news_html.rstrip() + '\n    </div>\n  </div>'

# New listings HTML
nl_html = ""
for item in new_listings:
    ex_map = {"bn":"Binance","okx":"OKX","bg":"Bitget","bb":"Bybit"}
    ex_name = ex_map.get(item["ex"], item["ex"])
    sym = item["sym"]; is_fut = item.get("fut",False)
    url = turl(item["ex"], sym, is_fut)
    display = fp(sym, is_fut, item["ex"])
    if not is_fut and "/" not in display:
        b = base_of(display); display = f"{b}/USDT"
    pct = item.get("pct",0); vol = item.get("vol",0)
    cls = "up" if pct >= 0 else "down"
    arrow = "▲" if pct >= 0 else "▼"
    ts = item.get("listing_time", item.get("ts", 0))
    ts_str = datetime.fromtimestamp(ts, timezone.utc).strftime("%m-%d %H:%M") if ts else "-"
    tag_text = f"{ex_name} {'合约' if is_fut else '现货'}"
    nl_html += f'<div class="nl-item" data-ts="{ts}"><span class="nl-ex">{ex_name}</span><span class="nl-pair"><a href="{url}" target="_blank">{display}</a></span><span class="nl-chg {cls}">{arrow} {abs(pct):.2f}%</span><span class="nl-vol">{fmt(vol)}</span><span class="nl-right"><span class="nl-type">{tag_text}</span><span class="nl-time">{ts_str}</span></span></div>\n'

if not nl_html:
    nl_html = '<div style="padding:8px;color:var(--t3);font-size:11px;text-align:center">12小时内暂无新币上线</div>'

# Announcements HTML
ann_html = ""
for i, a in enumerate(anns):
    src = a["src"]
    tag_cls = {"Binance":"tag-ex","OKX":"tag-crypto","Bitget":"tag-defi","Bybit":"tag-pol"}.get(src,"tag-crypto")
    ts_str = datetime.fromtimestamp(a["ts"], timezone.utc).strftime("%m-%d %H:%M") if a["ts"] and a["ts"] > 0 else "-"
    ann_html += f'<div class="news-row"><span class="news-n">{i+1}</span><div class="news-body"><a class="news-t" href="{a["url"]}" target="_blank">{a["title"]}</a><div class="news-meta"><span class="tag {tag_cls}">{src}</span> {ts_str}</div></div></div>\n'

# Exchange monitoring: build top3 for each (ex, fut, mode)
exchanges = [
    ("bn", "Binance", p1["bn_spot_top"], p1["bn_fut_top"]),
    ("okx", "OKX", p1["okx_spot_top"], p1["okx_fut_top"]),
    ("bg", "Bitget", p1["bg_spot_top"], p1["bg_fut_top"]),
    ("bb", "Bybit", p1["bb_spot_top"], p1["bb_fut_top"]),
]

def get_top3(ex, syms, fut, mode="vol"):
    items = []
    for sym in syms:
        key = f"{ex}|{sym}|{fut}"
        if key not in results: continue
        pct, vol = results[key]
        items.append((sym, pct, vol))
    if mode == "vol": items.sort(key=lambda x:-x[2])
    elif mode == "gain": items.sort(key=lambda x:-x[1])
    elif mode == "loss": items.sort(key=lambda x: x[1])
    return items[:3]

top3_data = {}
for ex, name, spot_syms, fut_syms in exchanges:
    for mode in ["vol","gain","loss"]:
        top3_data[(ex,False,mode)] = get_top3(ex, spot_syms, False, mode)
        top3_data[(ex,True,mode)]  = get_top3(ex, fut_syms, True, mode)

def ex_box_html(ex_name, items, mode="vol", is_fut=False, ex_code=""):
    h = f'<div class="ex-box"><div class="ex-box-name">{ex_name}</div>\n'
    if not items:
        h += '<div style="padding:8px;color:var(--t3);font-size:11px;text-align:center">暂无数据</div>\n'
    else:
        for sym, pct, vol in items:
            url = turl(ex_code, sym, is_fut)
            display = fp(sym, is_fut, ex_code)
            if not is_fut and "/" not in display:
                b = base_of(display); display = f"{b}/USDT"
            cls = "up" if pct >= 0 else "down"
            arrow = "▲" if pct >= 0 else "▼"
            if mode == "vol":
                h += f'<div class="ex-item"><div class="ex-item-pair"><a href="{url}" target="_blank">{display}</a></div><div class="ex-item-data"><b style="font-size:14px">{fmt(vol)}</b> <span class="{cls}" style="font-size:10px;opacity:.5">{arrow}</span></div></div>\n'
            else:
                h += f'<div class="ex-item"><div class="ex-item-pair"><a href="{url}" target="_blank">{display}</a></div><div class="ex-item-data"><span class="{cls}" style="font-size:14px;font-weight:700">{pct:+.2f}%</span> <span style="font-size:10px;color:var(--t3)">{fmt(vol)}</span></div></div>\n'
    h += '</div>\n'
    return h

def build_panel(mode):
    s=""; f_html=""
    for ex_code, ex_name, _, _ in exchanges:
        s += ex_box_html(ex_name, top3_data.get((ex_code,False,mode),[]), mode, False, ex_code)
        f_html += ex_box_html(ex_name, top3_data.get((ex_code,True,mode),[]), mode, True, ex_code)
    return f'''  <div class="ex-panel" id="etab-{mode}">
    <div class="ex-dual">
      <div class="ex-side"><div class="ex-side-label">现货</div>
        <div class="ex-grid">{s}</div>
      </div>
      <div class="ex-side"><div class="ex-side-label">永续合约</div>
        <div class="ex-grid">{f_html}</div>
      </div>
    </div>
  </div>'''

vol_panel = build_panel("vol")
gain_panel = build_panel("gain")
loss_panel = build_panel("loss")

btc_price = btc["price"]; btc_chg = btc["chg"]; btc_mcap = btc["mcap"]
btc_cls = "up" if btc_chg >= 0 else "down"
btc_arrow = "▲" if btc_chg >= 0 else "▼"

# Full HTML
html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>科技与加密货币仪表盘</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600;700&family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
:root{{color-scheme:light;--bg:#f1f5f9;--card:#fff;--border:#e2e8f0;--t1:#0f172a;--t2:#64748b;--t3:#94a3b8;--accent:#003366;--accent-l:#004d99;--green:#22c55e;--green-bg:#f0fdf4;--red:#ef4444;--red-bg:#fef2f2;--blue:#3b82f6;--orange:#f59e0b;--purple:#8b5cf6;--r:8px;--shadow:0 1px 2px rgba(0,0,0,.05),0 1px 3px rgba(0,0,0,.1);--mono:'Fira Code',monospace;--sans:'Inter','PingFang SC','Microsoft YaHei',sans-serif}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:var(--sans);background:var(--bg);color:var(--t1);line-height:1.5;padding:16px;max-width:1280px;margin:0 auto;font-size:13px}}
a{{color:inherit;text-decoration:none}}
.top-bar{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:16px}}
.nl-card{{background:var(--card);border:1px solid var(--border);border-radius:var(--r);box-shadow:var(--shadow);padding:12px 14px}}
.nl-title{{font-size:11px;font-weight:600;color:var(--t2);text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px}}
.nl-item{{display:flex;align-items:center;gap:6px;font-size:12px;padding:5px 8px;border-bottom:1px solid var(--border)}}
.nl-item:last-child{{border-bottom:none}}
.nl-ex{{font-weight:700;color:var(--accent);font-size:10px;text-transform:uppercase;min-width:48px;text-align:right}}
.nl-pair{{font-family:var(--mono);font-weight:600;font-size:12px;min-width:120px}}
.nl-pair a{{color:var(--t1);text-decoration:none}}.nl-pair a:hover{{color:var(--accent-l);text-decoration:underline}}
.nl-chg{{font-family:var(--mono);font-size:11px;font-weight:600;min-width:55px}}
.nl-vol{{font-family:var(--mono);font-size:11px;color:var(--t2);min-width:50px}}
.nl-right{{margin-left:auto;display:flex;gap:8px;align-items:center}}
.nl-type{{font-size:10px;color:var(--t3);text-align:right;min-width:28px}}
.nl-time{{font-family:var(--mono);font-size:10px;color:var(--t3);min-width:60px;text-align:right}}
.btc-card{{background:var(--card);border:1px solid var(--border);border-radius:var(--r);box-shadow:var(--shadow);padding:16px;display:flex;align-items:center;gap:14px}}
.btc-icon{{width:40px;height:40px;border-radius:50%;background:linear-gradient(135deg,#f7931a,#e8860a);display:flex;align-items:center;justify-content:center;flex-shrink:0}}
.btc-icon svg{{width:22px;height:22px;fill:#fff}}
.btc-price{{font-family:var(--mono);font-size:26px;font-weight:700;letter-spacing:-.5px}}
.btc-chg{{font-family:var(--mono);font-size:13px;font-weight:600;margin-top:1px}}
.btc-chg.up{{color:var(--green)}}.btc-chg.down{{color:var(--red)}}
.btc-meta{{margin-left:auto;text-align:right;font-family:var(--mono);font-size:11px;color:var(--t2);line-height:1.7}}
.tabs-wrap{{background:var(--card);border:1px solid var(--border);border-radius:var(--r);box-shadow:var(--shadow);margin-bottom:16px}}
.tab-bar{{display:flex;border-bottom:1px solid var(--border);padding:0 4px;align-items:center}}
.tab-btn{{padding:10px 16px;font-size:12px;font-weight:600;color:var(--t2);cursor:pointer;border:none;background:none;border-bottom:2px solid transparent;transition:all .15s;font-family:var(--sans);white-space:nowrap}}
.tab-btn.active{{color:var(--accent);border-bottom-color:var(--accent)}}
.tab-btn:hover:not(.active){{color:var(--t1)}}
.tab-right{{margin-left:auto;display:flex;gap:4px;padding-right:4px}}
.sort-btn{{padding:3px 10px;border:1px solid var(--border);border-radius:4px;background:var(--card);font-size:10px;font-weight:500;cursor:pointer;color:var(--t2);transition:all .15s;font-family:var(--sans)}}
.sort-btn.active{{background:var(--accent);color:#fff;border-color:var(--accent)}}
.sort-btn:hover:not(.active){{border-color:var(--accent);color:var(--accent)}}
.tab-panel{{display:none}}.tab-panel.active{{display:block}}
.news-list{{height:352px;overflow:hidden}}
.news-row{{display:flex;gap:8px;padding:10px 12px;border-bottom:1px solid var(--border);align-items:flex-start;transition:background .15s;height:44px;box-sizing:border-box}}
.news-row:last-child{{border-bottom:none}}.news-row:hover{{background:#f8fafc}}
.news-n{{font-family:var(--mono);font-size:11px;font-weight:600;color:var(--t3);min-width:16px;text-align:right;padding-top:2px}}
.news-body{{flex:1;min-width:0}}
.news-t{{font-size:12px;font-weight:500;color:var(--t1);text-decoration:none;line-height:1.4;display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.news-t:hover{{color:var(--accent-l)}}
.news-meta{{font-size:10px;color:var(--t2);margin-top:2px;display:flex;gap:6px;align-items:center}}
.news-heat{{font-family:var(--mono);font-size:11px;font-weight:600;color:var(--accent);min-width:40px;text-align:right;padding-top:2px}}
.tag{{display:inline-block;padding:1px 5px;border-radius:3px;font-size:9px;font-weight:600;letter-spacing:.2px}}
.tag-hot{{background:var(--red-bg);color:var(--red)}}.tag-defi{{background:#eff6ff;color:var(--blue)}}
.tag-ex{{background:#fff7ed;color:var(--orange)}}.tag-crypto{{background:var(--green-bg);color:var(--green)}}
.tag-pol{{background:#f5f3ff;color:var(--purple)}}.tag-sec{{background:var(--red-bg);color:var(--red)}}
.ex-wrap{{background:var(--card);border:1px solid var(--border);border-radius:var(--r);box-shadow:var(--shadow);margin-bottom:16px}}
.ex-tab-bar{{display:flex;border-bottom:1px solid var(--border);padding:0 4px}}
.ex-tab-btn{{padding:10px 16px;font-size:12px;font-weight:600;color:var(--t2);cursor:pointer;border:none;background:none;border-bottom:2px solid transparent;transition:all .15s;font-family:var(--sans);white-space:nowrap}}
.ex-tab-btn.active{{color:var(--accent);border-bottom-color:var(--accent)}}
.ex-tab-btn:hover:not(.active){{color:var(--t1)}}
.ex-panel{{display:none;padding:12px}}.ex-panel.active{{display:block}}
.ex-dual{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}
.ex-side{{border:1px solid var(--border);border-radius:6px;padding:10px;background:var(--card)}}
.ex-side-label{{font-size:12px;font-weight:700;color:var(--t2);text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px}}
.ex-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}}
.ex-box{{border:1px solid var(--border);border-radius:6px;padding:10px;background:#fafbfc}}
.ex-box-name{{font-size:11px;font-weight:700;color:var(--accent);text-transform:uppercase;margin-bottom:8px;padding-bottom:4px;border-bottom:1px solid var(--border)}}
.ex-item{{padding:5px 0}}
.ex-item-pair{{font-family:var(--mono);font-size:13px;font-weight:600}}
.ex-item-pair a{{color:var(--t1);text-decoration:none}}
.ex-item-pair a:hover{{color:var(--accent-l);text-decoration:underline}}
.ex-item-data{{font-family:var(--mono);font-size:12px;color:var(--t2);margin-top:1px}}
.up{{color:var(--green);font-weight:600}}.down{{color:var(--red);font-weight:600}}
.footer{{text-align:center;margin-top:16px;font-size:10px;color:var(--t3);letter-spacing:.3px}}
.modal-overlay{{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.4);z-index:200;justify-content:center;align-items:center}}
.modal-overlay.open{{display:flex}}
.modal-box{{background:var(--card);border-radius:var(--r);box-shadow:0 8px 32px rgba(0,0,0,.2);max-width:560px;width:90%;max-height:80vh;overflow-y:auto;padding:24px}}
.modal-box h3{{font-size:15px;font-weight:700;margin-bottom:12px}}
.modal-box h4{{font-size:12px;font-weight:700;color:var(--accent);margin:14px 0 4px;text-transform:uppercase;letter-spacing:.3px}}
.modal-box p,.modal-box li{{font-size:12px;color:var(--t2);line-height:1.7;margin-bottom:6px}}
.modal-box ul{{padding-left:16px;margin-bottom:8px}}
.modal-box code{{font-family:var(--mono);font-size:11px;background:#f1f5f9;padding:1px 4px;border-radius:3px}}
.modal-close{{float:right;background:none;border:none;font-size:18px;cursor:pointer;color:var(--t3);line-height:1;padding:4px}}
.modal-close:hover{{color:var(--t1)}}
.dot{{width:6px;height:6px;border-radius:50%;background:var(--green);display:inline-block;animation:pulse 2s infinite}}
@keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.4}}}}
.meta{{font-size:11px;color:var(--t2);display:flex;gap:8px;align-items:center;position:relative}}
.meta .ts-btn{{cursor:pointer;border-bottom:1px dashed var(--t3);padding-bottom:1px}}
.meta .ts-btn:hover{{color:var(--accent-l)}}
.snap-dd{{position:absolute;top:100%;right:0;margin-top:6px;background:var(--card);border:1px solid var(--border);border-radius:var(--r);box-shadow:0 4px 16px rgba(0,0,0,.12);z-index:100;min-width:260px;max-height:360px;overflow-y:auto;display:none}}
.snap-dd.open{{display:block}}
.snap-dd-title{{font-size:11px;font-weight:600;color:var(--t2);padding:10px 12px 6px;text-transform:uppercase;letter-spacing:.5px;border-bottom:1px solid var(--border)}}
.snap-item{{display:flex;padding:8px 12px;font-size:12px;cursor:pointer;transition:background .15s;border-bottom:1px solid var(--border)}}
.snap-item:last-child{{border-bottom:none}}.snap-item:hover{{background:#f8fafc}}
.snap-item .s-ts{{font-family:var(--mono);font-weight:500}}
.hdr{{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;flex-wrap:wrap;gap:8px}}
.hdr h1{{font-size:17px;font-weight:700;letter-spacing:-.3px}}
@media(max-width:900px){{.top-bar{{grid-template-columns:1fr}}.ex-dual{{grid-template-columns:1fr}}.ex-grid{{grid-template-columns:1fr 1fr}}}}
@media(max-width:500px){{.ex-grid{{grid-template-columns:1fr}}.btc-price{{font-size:22px}}}}
</style>
</head>
<body>

<div class="hdr">
  <h1>科技与加密货币仪表盘</h1>
  <div class="meta">
    <span class="dot"></span>
    <span class="ts-btn" onclick="toggleSnapDD()">更新于 {now_utc} UTC</span>
    <div class="snap-dd" id="snap-dd">
      <div class="snap-dd-title">历史快照</div>
      <div id="snap-list"><div style="padding:12px;color:var(--t3);font-size:11px">点击加载...</div></div>
    </div>
  </div>
</div>

<div class="top-bar">
  <div class="nl-card" id="nl-card">
    <div class="nl-title">12h 内上线</div>
    <div id="nl-list">
{nl_html}
    </div>
  </div>
  <div class="btc-card" id="btc-card">
    <div class="btc-icon"><svg viewBox="0 0 24 24"><path d="M14.24 10.56c-.31 1.24-2.24.61-2.84.44l.55-2.18c.62.18 2.61.44 2.29 1.74zm-3.11 1.56l-.6 2.41c.74.19 3.03.92 3.37-.44.36-1.42-2.03-1.79-2.77-1.97zm10.57 2.3c-1.34 5.36-6.76 8.62-12.12 7.28S.96 14.94 2.3 9.58 9.06.96 14.42 2.3s8.62 6.76 7.28 12.12zm-5.47-5.58c.08-1.78-1.08-2.47-2.93-3.05l.6-2.39-1.46-.37-.58 2.33c-.38-.1-.78-.18-1.16-.28l.58-2.32-1.46-.37-.6 2.39c-.32-.07-.63-.14-.93-.22l-2.01-.51-.39 1.54s1.08.25 1.06.26c.59.15.7.55.68.87l-.68 2.72c.04.01.1.03.17.05l-.17-.04-1 3.84c-.07.18-.26.45-.67.35.02.02-1.06-.27-1.06-.27l-.73 1.68 1.89.48c.35.09.7.18 1.04.27l-.61 2.42 1.46.37.6-2.39c.4.11.78.21 1.16.31l-.6 2.37 1.46.37.61-2.41c2.35.45 4.11.27 4.86-1.86.6-1.71-.03-2.7-1.26-3.35.9-.21 1.58-.8 1.76-2.03z"/></svg></div>
    <div>
      <div class="btc-price">${btc_price:,.0f}</div>
      <div class="btc-chg {btc_cls}">{btc_arrow} {abs(btc_chg):.2f}%</div>
    </div>
    <div class="btc-meta">
      <div>市值：${btc_mcap/1e12:.2f}万亿</div>
      <div>24h：{btc_arrow} {abs(btc_chg):.2f}%</div>
    </div>
  </div>
</div>

<div class="tabs-wrap">
  <div class="tab-bar">
    <button class="tab-btn active" data-tab="listing" onclick="switchTab('listing')">新币上线</button>
    <button class="tab-btn" data-tab="hn" onclick="switchTab('hn')">Hacker News</button>
    <button class="tab-btn" data-tab="news" onclick="switchTab('news')">行业热点</button>
    <div class="tab-right" id="hn-sort" style="display:none">
      <button class="sort-btn active" onclick="sortHN('score')">最热</button>
      <button class="sort-btn" onclick="sortHN('time')">最新</button>
      <button class="sort-btn" onclick="sortHN('comments')">评论</button>
    </div>
  </div>

  <div class="tab-panel active" id="tab-listing">
    <div class="news-list">
{ann_html}
    </div>
  </div>

{hn_html}

{news_html}
</div>

<div class="ex-wrap">
  <div class="ex-tab-bar">
    <button class="ex-tab-btn active" data-etab="vol" onclick="switchExTab('vol')">1h 成交额</button>
    <button class="ex-tab-btn" data-etab="gain" onclick="switchExTab('gain')">1h 涨幅</button>
    <button class="ex-tab-btn" data-etab="loss" onclick="switchExTab('loss')">1h 跌幅</button>
    <span style="margin-left:auto;padding-right:8px;cursor:pointer;color:var(--t3);display:flex;align-items:center" onclick="openExHelp()" title="统计说明"><svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"/></svg></span>
  </div>
{vol_panel}
{gain_panel}
{loss_panel}
</div>

<div class="modal-overlay" id="ex-help-modal">
  <div class="modal-box">
    <button class="modal-close" onclick="closeExHelp()">&times;</button>
    <h3>交易所监控 · 统计方法说明</h3>
    <h4>数据范围</h4><ul><li>四大交易所：Binance、OKX、Bitget、Bybit</li><li>分别统计现货和永续合约，逻辑相同，仅 API 端点不同</li></ul>
    <h4>候选筛选</h4><ul><li>按 24h ticker 成交额排序，四所现货各取前 200 名，合约各取前 100 名</li><li>排除大市值币（BTC、ETH、SOL 等）、稳定币（USDC、BUSD 等）、杠杆代币（UP/DOWN/BULL/BEAR）、法币对</li></ul>
    <h4>1h K线</h4><ul><li>取最近 2 根 1H K线，使用<strong>最后已收盘</strong>那根的数据计算涨跌幅和成交额</li><li>涨跌幅 = (最后已收盘价 − 前一根收盘价) / 前一根收盘价 × 100%</li><li>成交额 = 最后已收盘 K线的 quote 计价成交量（USDT）</li><li>如果最后已收盘 K线的成交额为 0，或 K线数据不足 2 根，则排除该交易对</li></ul>
    <h4>三种榜单</h4><ul><li>成交额/涨幅/跌幅各取每所每市场 Top 3</li><li>频率统计独立，不跨榜累计</li></ul>
    <h4>更新频率</h4><ul><li>每小时自动更新</li></ul>
  </div>
</div>

<div class="footer">数据来源：Binance · OKX · Bitget · Bybit · Cointelegraph · Hacker News | 每小时自动更新</div>

<script>
function switchTab(id){{
  document.querySelectorAll('.tab-btn').forEach(function(b){{b.classList.toggle('active',b.dataset.tab===id)}});
  document.querySelectorAll('.tab-panel').forEach(function(p){{p.classList.toggle('active',p.id==='tab-'+id)}});
  document.getElementById('hn-sort').style.display=id==='hn'?'flex':'none';
}}
function switchExTab(id){{
  document.querySelectorAll('.ex-tab-btn').forEach(function(b){{b.classList.toggle('active',b.dataset.etab===id)}});
  document.querySelectorAll('.ex-panel').forEach(function(p){{p.classList.toggle('active',p.id==='etab-'+id)}});
}}
function openExHelp(){{document.getElementById('ex-help-modal').classList.add('open')}}
function closeExHelp(){{document.getElementById('ex-help-modal').classList.remove('open')}}
var hnSort='score';
function sortHN(key){{
  hnSort=key;
  var labels={{score:'最热',time:'最新',comments:'评论'}};
  document.querySelectorAll('#hn-sort .sort-btn').forEach(function(b){{b.classList.toggle('active',b.textContent===labels[key])}});
  var list=document.getElementById('hn-list');
  var items=Array.from(list.querySelectorAll('.news-row'));
  items.sort(function(a,b){{var va=parseInt(a.dataset[key])||0,vb=parseInt(b.dataset[key])||0;return vb-va}});
  items.forEach(function(item,i){{item.querySelector('.news-n').textContent=i+1;list.appendChild(item)}});
}}
(function(){{
  var now=Math.floor(Date.now()/1000);
  var list=document.getElementById('nl-list');
  var items=Array.from(list.querySelectorAll('.nl-item'));
  items.sort(function(a,b){{return(parseInt(b.dataset.ts)||0)-(parseInt(a.dataset.ts)||0)}});
  items.forEach(function(el){{
    var ts=parseInt(el.dataset.ts)||0;
    if(now-ts>12*3600){{el.remove()}}else{{list.appendChild(el)}}
  }});
  if(list.children.length===0){{
    document.getElementById('nl-card').style.display='none';
    document.getElementById('btc-card').style.gridColumn='1 / -1';
  }}
}})();
setTimeout(function(){{location.reload()}},69*60*1000);

var snapshots=[];
function toggleSnapDD(){{
  var dd=document.getElementById('snap-dd');
  dd.classList.toggle('open');
  if(dd.classList.contains('open')&&snapshots.length===0) loadSnaps();
}}
function loadSnaps(){{
  fetch('https://cdn.jsdelivr.net/gh/peterzhangbo/Dashboard@main/dashboard-snapshots.jsonl')
    .then(function(r){{if(!r.ok) throw new Error(r.status); return r.text()}})
    .then(parseSnapData)
    .catch(function(){{
      fetch('https://api.github.com/repos/peterzhangbo/Dashboard/contents/dashboard-snapshots.jsonl',{{headers:{{'Accept':'application/vnd.github.v3.raw'}}}})
        .then(function(r){{if(!r.ok) throw new Error(r.status); return r.text()}})
        .then(parseSnapData)
        .catch(function(){{document.getElementById('snap-list').innerHTML='<div style="padding:12px;color:var(--t3);font-size:11px">加载失败</div>'}});
    }});
}}
function parseSnapData(txt){{
  var lines=txt.trim().split('\\n');
  snapshots=[];
  lines.forEach(function(line){{
    try{{var obj=JSON.parse(line);if(obj.ts)snapshots.push(obj)}}catch(e){{}}
  }});
  snapshots.reverse();
  var list=document.getElementById('snap-list');
  if(snapshots.length===0){{list.innerHTML='<div style="padding:12px;color:var(--t3);font-size:11px">暂无快照</div>';return}}
  list.innerHTML='';
  snapshots.forEach(function(s,idx){{
    var d=new Date(s.ts);
    var tsStr=d.toLocaleString('zh-CN',{{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}});
    var item=document.createElement('div');
    item.className='snap-item';
    item.innerHTML='<span class="s-ts">'+tsStr+'</span>';
    item.onclick=function(){{openSnapInNewTab(s)}};
    list.appendChild(item);
  }});
}}
function openSnapInNewTab(s){{
  document.getElementById('snap-dd').classList.remove('open');
  var d=new Date(s.ts);
  var body='<!DOCTYPE html><html><head><meta charset="UTF-8"><title>快照 '+d.toLocaleString('zh-CN')+'</title><style>body{{font-family:Inter,sans-serif;padding:20px;max-width:800px;margin:0 auto;color:#0f172a}}h2{{margin-bottom:12px}}.kv{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-bottom:16px}}.kv div{{padding:10px;border:1px solid #e2e8f0;border-radius:6px}}.kv .l{{font-size:11px;color:#64748b;text-transform:uppercase}}.kv .v{{font-size:18px;font-weight:700;margin-top:4px}}.up{{color:#22c55e}}.down{{color:#ef4444}}table{{width:100%;border-collapse:collapse;font-size:13px}}th{{text-align:left;padding:6px 8px;border-bottom:2px solid #e2e8f0;font-size:11px;color:#64748b}}td{{padding:6px 8px;border-bottom:1px solid #e2e8f0}}a{{color:#003366;text-decoration:none}}a:hover{{text-decoration:underline}}</style></head><body>';
  body+='<h2>快照：'+d.toLocaleString('zh-CN')+'</h2>';
  if(s.btc){{
    var cls=s.btc.change>=0?'up':'down';
    body+='<div class="kv"><div><div class="l">BTC 价格</div><div class="v">$'+Number(s.btc.price).toLocaleString()+'</div></div>';
    body+='<div><div class="l">24h 涨跌</div><div class="v '+cls+'">'+(s.btc.change>=0?'+':'')+s.btc.change.toFixed(2)+'%</div></div>';
    body+='<div><div class="l">市值</div><div class="v">$'+(s.btc.mcap/1e12).toFixed(2)+'万亿</div></div></div>';
  }}
  if(s.hn&&s.hn.length>0){{
    body+='<h3>Hacker News 热门</h3><table><tr><th>#</th><th>标题</th><th>分数</th><th>评论</th></tr>';
    s.hn.forEach(function(h,i){{body+='<tr><td>'+(i+1)+'</td><td>'+h.t+'</td><td>'+h.s+'</td><td>'+h.c+'</td></tr>'}});
    body+='</table>';
  }}
  if(s.crypto&&s.crypto.length>0){{
    body+='<h3>Web3 / 加密热点</h3><table><tr><th>#</th><th>标题</th><th>分类</th></tr>';
    s.crypto.forEach(function(c,i){{body+='<tr><td>'+(i+1)+'</td><td>'+c.t+'</td><td>'+(c.tag||'')+'</td></tr>'}});
    body+='</table>';
  }}
  body+='</body></html>';
  var w=window.open('','_blank');
  w.document.write(body);
  w.document.close();
}}
document.addEventListener('click',function(e){{
  if(!e.target.closest('.meta')) document.getElementById('snap-dd').classList.remove('open');
  if(e.target===document.getElementById('ex-help-modal')) closeExHelp();
}});
</script>
</body>
</html>'''

# Write HTML
with open(HTML_FILE, "w") as f:
    f.write(html)
print(f"HTML written: {len(html)} chars")

# Extract HN data for snapshot
hn_data = []
hn_items = re.findall(r'data-score="(\d+)".*?data-comments="(\d+)".*?class="news-t"[^>]*>([^<]+)</a>', hn_html, re.DOTALL)
for score, comments, title in hn_items:
    hn_data.append({"t": title.strip(), "s": int(score), "c": int(comments)})

crypto_data = [{"t": a["title"], "tag": a["src"]} for a in anns]

# Append snapshot
snap = {
    "ts": int(time.time() * 1000),
    "btc": {"price": btc_price, "change": btc_chg, "mcap": btc_mcap},
    "hn": hn_data,
    "crypto": crypto_data
}
with open(SNAPL_FILE, "a") as f:
    f.write(json.dumps(snap, ensure_ascii=False) + "\n")
print("Snapshot appended")

# Push to GitHub
print("Pushing to GitHub...")

def gh_push(path, content, message):
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    sha = None
    try:
        req = urllib.request.Request(url, headers={
            "Authorization": f"token {GITHUB_TOKEN}",
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/vnd.github.v3+json"
        })
        with urllib.request.urlopen(req, timeout=15) as r:
            sha = json.loads(r.read()).get("sha")
    except: pass

    body = {"message": message, "content": base64.b64encode(content.encode("utf-8")).decode("utf-8")}
    if sha: body["sha"] = sha

    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="PUT", headers={
        "Authorization": f"token {GITHUB_TOKEN}",
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json"
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            result = json.loads(r.read())
            print(f"  {path}: OK ({result.get('content',{}).get('sha','')[:8]})")
    except Exception as e:
        print(f"  {path}: FAIL - {e}")

gh_push("betanews.html", html, f"Dashboard update {now_utc} UTC")
gh_push("new-listings.json", json.dumps(new_listings, indent=2, ensure_ascii=False), f"New listings {now_utc} UTC")

snap_content = open(SNAPL_FILE).read()
gh_push("dashboard-snapshots.jsonl", snap_content, f"Snapshot append {now_utc} UTC")

import json as j
snap_json = j.dumps(p1["current"], indent=2)
gh_push("exchange-pairs-snapshot.json", snap_json, f"Pairs snapshot {now_utc} UTC")

print("\n=== 完成 ===")
print(f"BTC: ${btc_price:,.0f} ({btc_chg:+.2f}%)")
print(f"公告: {len(anns)} 条 | K线: {len(results)} 个 | 快照: 已追加")
