#!/usr/bin/env python3
"""Gussie Garcia's AI Stock Tracker data job. Runs on GitHub Actions (no Claude, no keys needed).

Pulls for every stock/fund on the list:
  - live price + fundamentals from TradingView's public screener
  - 10 years of monthly prices from Yahoo Finance (growth per year, worst drop, ups and downs)
  - latest headlines from Yahoo Finance news feeds
Writes site/data.json + site/index.html for GitHub Pages.
"""
import json, os, re, shutil, time, urllib.request
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from html import unescape

UA = {"User-Agent": "Mozilla/5.0 (gussie-ai-stock-tracker)", "Content-Type": "application/json"}

# ticker, exchange, theme, kind, risk 1-5, plain-English description
UNIVERSE = [
    ("VOO", "AMEX", "Index funds", "fund", 2, "The 500 biggest US companies in one fund (S&P 500). The classic long-term core."),
    ("VTI", "AMEX", "Index funds", "fund", 2, "The entire US stock market, about 3,500 companies, in one fund."),
    ("QQQ", "NASDAQ", "Index funds", "fund", 3, "The 100 biggest Nasdaq companies. Heavy in tech and AI."),
    ("VUG", "AMEX", "Index funds", "fund", 3, "Large US growth companies in one Vanguard fund."),
    ("VGT", "AMEX", "Index funds", "fund", 3, "US technology companies in one Vanguard fund."),
    ("NVDA", "NASDAQ", "AI chips", "stock", 4, "Nvidia. Makes the chips most AI systems are trained and run on."),
    ("AVGO", "NASDAQ", "AI chips", "stock", 4, "Broadcom. Custom AI chips and networking for data centers."),
    ("TSM", "NYSE", "AI chips", "stock", 4, "Taiwan Semiconductor. Manufactures chips for Nvidia, Apple, AMD and others."),
    ("AMD", "NASDAQ", "AI chips", "stock", 4, "AMD. Computer and AI chips, Nvidia's main rival."),
    ("SMH", "NASDAQ", "AI chips", "fund", 4, "One fund holding the top ~25 chip companies."),
    ("MSFT", "NASDAQ", "Big Tech & AI software", "stock", 3, "Microsoft. Cloud (Azure), Office, and a major AI investor."),
    ("GOOGL", "NASDAQ", "Big Tech & AI software", "stock", 3, "Alphabet. Google Search, YouTube, Google Cloud and Gemini AI."),
    ("AMZN", "NASDAQ", "Big Tech & AI software", "stock", 3, "Amazon. Online retail and AWS, the largest cloud business."),
    ("META", "NASDAQ", "Big Tech & AI software", "stock", 4, "Meta. Facebook, Instagram, WhatsApp, spending heavily on AI."),
    ("PLTR", "NASDAQ", "Big Tech & AI software", "stock", 5, "Palantir. AI and data software for governments and companies. Priced for very high growth."),
    ("VRT", "NYSE", "Data centers & power", "stock", 4, "Vertiv. Power and cooling equipment that keeps AI data centers running."),
    ("ANET", "NYSE", "Data centers & power", "stock", 4, "Arista Networks. High-speed networking inside data centers."),
    ("EQIX", "NASDAQ", "Data centers & power", "stock", 3, "Equinix. Owns data centers worldwide and rents space (pays a dividend)."),
    ("DLR", "NYSE", "Data centers & power", "stock", 3, "Digital Realty. Owns and leases data centers (pays a dividend)."),
    ("CEG", "NASDAQ", "Data centers & power", "stock", 4, "Constellation Energy. Largest US nuclear power producer, selling power to data centers."),
    ("VST", "NYSE", "Data centers & power", "stock", 4, "Vistra. Power plants supplying electricity demand from data centers."),
    ("SPCX", "NASDAQ", "Space", "stock", 5, "SpaceX. Rockets and Starlink internet. Public since June 2026, so little price history."),
    ("RKLB", "NASDAQ", "Space", "stock", 5, "Rocket Lab. Small rockets and satellite parts. Not yet profitable."),
    ("ASTS", "NASDAQ", "Space", "stock", 5, "AST SpaceMobile. Satellites that connect directly to regular phones. Very speculative."),
    ("UFO", "NASDAQ", "Space", "fund", 4, "One fund holding space companies."),
    ("LMT", "NYSE", "Defense & drones", "stock", 2, "Lockheed Martin. F-35 jets, missiles, space systems. Pays a dividend."),
    ("RTX", "NYSE", "Defense & drones", "stock", 2, "RTX (Raytheon). Missiles, defense systems and jet engines."),
    ("NOC", "NYSE", "Defense & drones", "stock", 2, "Northrop Grumman. Stealth bombers, space and missile defense."),
    ("AVAV", "NASDAQ", "Defense & drones", "stock", 5, "AeroVironment. Military drones. Big price swings."),
    ("KTOS", "NASDAQ", "Defense & drones", "stock", 5, "Kratos. Drones and defense tech. Big price swings."),
    ("ITA", "CBOE", "Defense & drones", "fund", 3, "One fund holding US aerospace and defense companies."),
    ("SHLD", "AMEX", "Defense & drones", "fund", 3, "One fund holding defense technology companies, including drones."),
    ("LLY", "NYSE", "Healthcare & biotech", "stock", 3, "Eli Lilly. Weight-loss and diabetes drugs (Zepbound, Mounjaro)."),
    ("VRTX", "NASDAQ", "Healthcare & biotech", "stock", 3, "Vertex. Cystic fibrosis and gene-editing medicines."),
    ("ISRG", "NASDAQ", "Healthcare & biotech", "stock", 3, "Intuitive Surgical. da Vinci surgical robots."),
    ("CRSP", "NASDAQ", "Healthcare & biotech", "stock", 5, "CRISPR Therapeutics. Gene editing. Very speculative."),
    ("XBI", "AMEX", "Healthcare & biotech", "fund", 4, "One fund holding many smaller biotech companies."),
    ("IBIT", "NASDAQ", "Crypto", "fund", 5, "BlackRock's Bitcoin fund. Owns bitcoin; buy it like a stock."),
    ("ETHA", "NASDAQ", "Crypto", "fund", 5, "BlackRock's Ethereum fund. Owns ether; buy it like a stock."),
    ("COIN", "NASDAQ", "Crypto", "stock", 5, "Coinbase. The largest US crypto exchange."),
    ("MSTR", "NASDAQ", "Crypto", "stock", 5, "Strategy (MicroStrategy). Holds billions in bitcoin. Swings more than bitcoin itself."),
    ("TSLA", "NASDAQ", "EVs & robotics", "stock", 5, "Tesla. Electric cars, batteries, self-driving and robots."),
]

# Hidden behind the "Speculative" filter in the app: unprofitable, tiny, or crypto names that have fallen 65-90%.
SPECULATIVE = {"ASTS", "RKLB", "CRSP", "AVAV", "KTOS", "COIN", "MSTR", "ETHA"}

COLS = ["description", "close", "change", "Perf.W", "Perf.1M", "Perf.YTD", "Perf.Y", "Perf.5Y",
        "market_cap_basic", "price_earnings_ttm", "total_revenue_yoy_growth_ttm", "dividends_yield_current"]


def get(url, body=None, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=json.dumps(body).encode() if body else None, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except Exception:
            if i == tries - 1: raise
            time.sleep(2 + 3 * i)


def live():
    tick = [f"{ex}:{t}" for t, ex, *_ in UNIVERSE]
    d = json.loads(get("https://scanner.tradingview.com/america/scan", {"symbols": {"tickers": tick}, "columns": COLS}))
    return {r["s"].split(":")[1]: dict(zip(COLS, r["d"])) for r in d["data"]}


def history(t):
    """Monthly adjusted closes (dividends included) for up to 10 years."""
    for host in ("query1", "query2"):
        try:
            d = json.loads(get(f"https://{host}.finance.yahoo.com/v8/finance/chart/{t}?interval=1mo&range=10y"))["chart"]["result"][0]
            ts, adj = d["timestamp"], d["indicators"]["adjclose"][0]["adjclose"]
            return [(a, b) for a, b in zip(ts, adj) if b]
        except Exception:
            continue
    return []


def stats(h):
    if len(h) < 13: return {"years": round(len(h) / 12, 1)}
    yrs = (h[-1][0] - h[0][0]) / (365.25 * 86400)
    cagr = (h[-1][1] / h[0][1]) ** (1 / yrs) - 1
    peak, mdd = h[0][1], 0
    for _, p in h:
        peak = max(peak, p); mdd = min(mdd, p / peak - 1)
    rets = [h[i][1] / h[i - 1][1] - 1 for i in range(1, len(h))]
    m = sum(rets) / len(rets)
    vol = (sum((r - m) ** 2 for r in rets) / (len(rets) - 1)) ** 0.5 * 12 ** 0.5
    return {"years": round(yrs, 1), "cagr": round(cagr * 100, 1), "max_drop": round(mdd * 100, 1), "volatility": round(vol * 100, 1)}


def news(t, limit=5):
    try:
        x = get(f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={t}&region=US&lang=en-US").decode("utf-8", "ignore")
    except Exception:
        return []
    out, cutoff = [], datetime.now(timezone.utc) - timedelta(days=10)
    for item in re.findall(r"<item>(.*?)</item>", x, re.S):
        title = re.search(r"<title>(.*?)</title>", item, re.S)
        link = re.search(r"<link>(.*?)</link>", item, re.S)
        date = re.search(r"<pubDate>(.*?)</pubDate>", item, re.S)
        if not (title and link and date): continue
        try: dt = parsedate_to_datetime(date.group(1).strip())
        except Exception: continue
        if dt < cutoff: continue
        clean = lambda s: unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", s)).strip()
        out.append({"t": t, "title": clean(title.group(1)), "url": clean(link.group(1)), "when": dt.isoformat()})
        if len(out) >= limit: break
    return out


def main():
    q = live()
    stocks, all_news = [], []
    for t, ex, theme, kind, risk, desc in UNIVERSE:
        v = q.get(t)
        if not v or v.get("close") is None:
            print("skip (no live data):", t); continue
        h = history(t)
        step = max(1, len(h) // 120)
        stocks.append({
            "t": t, "name": v["description"], "theme": theme, "spec": t in SPECULATIVE, "kind": kind, "risk": risk, "about": desc,
            "price": v["close"], "day": v["change"], "week": v["Perf.W"], "month": v["Perf.1M"], "ytd": v["Perf.YTD"],
            "y1": v["Perf.Y"], "y5": v["Perf.5Y"] if len(h) >= 55 else None,
            "mcap": v["market_cap_basic"], "pe": v["price_earnings_ttm"], "rev_growth": v["total_revenue_yoy_growth_ttm"],
            "div": v["dividends_yield_current"], "hist": stats(h),
            "spark": [round(p, 2) for _, p in h[::step]],
        })
        all_news += news(t)
        time.sleep(0.3)
    all_news.sort(key=lambda n: n["when"], reverse=True)
    data = {"updated": datetime.now(timezone.utc).isoformat(timespec="minutes"), "stocks": stocks, "news": all_news[:150]}
    os.makedirs("site", exist_ok=True)
    json.dump(data, open("site/data.json", "w"), separators=(",", ":"))
    shutil.copy("index.html", "site/index.html")
    print(f"wrote {len(stocks)} stocks, {len(data['news'])} headlines")


if __name__ == "__main__":
    main()
