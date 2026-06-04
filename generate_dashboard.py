#!/usr/bin/env python3
"""
毎朝の投資ダッシュボード生成スクリプト
Daily Investment Dashboard Generator
Uses: yfinance / frankfurter.app / Yahoo Finance RSS / Google News RSS
"""

import yfinance as yf
import requests
from datetime import datetime, timedelta
import pytz
import feedparser
import os
import time
import re
import html as html_lib
import json

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

# ============================================================
# Portfolio Configuration
# ============================================================

PORTFOLIO = {
    "NVDA":  {"name": "NVIDIA Corp.",       "invested_jpy": 34415, "monthly_jpy": 0},
    "AVGO":  {"name": "Broadcom Inc.",      "invested_jpy": 72592, "monthly_jpy": 0},
    "KTOS":  {"name": "Kratos Defense",     "invested_jpy": 21225, "monthly_jpy": 0},
    "UPST":  {"name": "Upstart Holdings",   "invested_jpy": 10820, "monthly_jpy": 0},
    "UBER":  {"name": "Uber Technologies",  "invested_jpy": 11416, "monthly_jpy": 0},
    "TMC":   {"name": "TMC the metals co.", "invested_jpy": 4784,  "monthly_jpy": 0},
}

# Future planned purchases (not yet held, watching for right entry)
FUTURE_PURCHASES = [
    {"ticker": "MU",     "name": "Micron Technology", "reason": "AIメモリ・2倍狙いメイン", "timing": "6月24日決算後"},
    {"ticker": "8035.T", "name": "東京エレクトロン", "reason": "円建て・AI半導体装置",     "timing": "NISA本開設後"},
]

# Important upcoming dates (manually maintained)
IMPORTANT_DATES = [
    {"date": "2026-06-12", "event": "SpaceX IPO（SPCX上場予定）",  "ticker": None,   "type": "ipo"},
    {"date": "2026-06-22", "event": "AVGO 配当権利確定日",          "ticker": "AVGO", "type": "dividend"},
    {"date": "2026-06-24", "event": "MU 決算発表→購入判断",         "ticker": "MU",   "type": "earnings"},
    {"date": "2026-06-30", "event": "AVGO 配当入金（約104円）",     "ticker": "AVGO", "type": "dividend"},
]

# Watchlist for dip-opportunity scanning (not yet held)
OPPORTUNITY_WATCHLIST = [
    ("AVGO", "Broadcom"),
    ("AMD",  "AMD"),
    ("PLTR", "Palantir"),
    ("RKLB", "Rocket Lab"),
    ("NET",  "Cloudflare"),
    ("MRVL", "Marvell Tech"),
    ("ARM",  "ARM Holdings"),
    ("SMCI", "Super Micro"),
    ("MU",   "Micron"),
]

INDICES = {
    "^IXIC": "NASDAQ",
    "^GSPC": "S&P500",
    "^SOX":  "SOX半導体指数",
    "^N225": "日経225",
    "^VIX":  "VIX恐怖指数",
}

CURRENCY_PAIRS = [
    ("USD", "JPY"),
    ("MYR", "JPY"),
    ("USD", "MYR"),
    ("EUR", "JPY"),
    ("GBP", "JPY"),
    ("AUD", "JPY"),
    ("SGD", "JPY"),
]

# 1-year growth estimates when no analyst target available
SECTOR_GROWTH_1Y = {
    "NVDA":  0.35,
    "AVGO":  0.25,
    "KTOS":  0.22,
    "UPST":  0.40,
    "UBER":  0.20,
    "TMC":   0.50,
}

# ============================================================
# Data Fetching
# ============================================================

def get_stock_data():
    stocks = {}
    for ticker, meta in PORTFOLIO.items():
        try:
            t    = yf.Ticker(ticker)
            hist = t.history(period="5d", interval="1d")
            info = t.info

            if len(hist) >= 2:
                prev_close = float(hist["Close"].iloc[-2])
                current    = float(hist["Close"].iloc[-1])
            elif len(hist) == 1:
                current    = float(hist["Close"].iloc[-1])
                prev_close = float(info.get("previousClose", current))
            else:
                current    = float(info.get("regularMarketPrice") or info.get("currentPrice") or 0)
                prev_close = float(info.get("previousClose", current))

            change     = current - prev_close
            change_pct = (change / prev_close * 100) if prev_close else 0
            target     = info.get("targetMeanPrice")
            target_dist = ((float(target) - current) / current * 100) if target else None

            stocks[ticker] = {
                "name":         meta["name"],
                "price":        round(current, 2),
                "change":       round(change, 2),
                "change_pct":   round(change_pct, 2),
                "target_price": round(float(target), 2) if target else None,
                "target_dist":  round(target_dist, 1) if target_dist is not None else None,
                "invested_jpy": meta["invested_jpy"],
                "monthly_jpy":  meta["monthly_jpy"],
                "is_jpy":       ".T" in ticker,
            }
        except Exception as e:
            stocks[ticker] = {
                "name":         meta["name"],
                "price":        None,
                "change":       None,
                "change_pct":   None,
                "target_price": None,
                "target_dist":  None,
                "invested_jpy": meta["invested_jpy"],
                "monthly_jpy":  meta["monthly_jpy"],
                "is_jpy":       ".T" in ticker,
                "error":        str(e),
            }
    return stocks


def get_watchlist_data():
    """Fetch prices for opportunity watchlist + future purchase tickers."""
    tickers = list({t for t, _ in OPPORTUNITY_WATCHLIST})
    for fp in FUTURE_PURCHASES:
        if fp["ticker"] not in tickers and not fp["ticker"].endswith(".T"):
            tickers.append(fp["ticker"])

    results = {}
    name_map = dict(OPPORTUNITY_WATCHLIST)
    for ticker in tickers:
        try:
            t    = yf.Ticker(ticker)
            hist = t.history(period="5d", interval="1d")
            info = t.info
            if len(hist) >= 2:
                prev_close = float(hist["Close"].iloc[-2])
                current    = float(hist["Close"].iloc[-1])
            elif len(hist) == 1:
                current    = float(hist["Close"].iloc[-1])
                prev_close = float(info.get("previousClose", current))
            else:
                current    = float(info.get("regularMarketPrice") or 0)
                prev_close = float(info.get("previousClose", current))
            change_pct = (current - prev_close) / prev_close * 100 if prev_close else 0
            target = info.get("targetMeanPrice")
            results[ticker] = {
                "name":       name_map.get(ticker, ticker),
                "price":      round(current, 2),
                "change_pct": round(change_pct, 2),
                "target":     round(float(target), 2) if target else None,
            }
        except Exception:
            pass
    return results


def get_investment_opportunities(watchlist_data):
    """Return today's dip opportunities from watchlist (≥3% down)."""
    opps = []
    for ticker, data in watchlist_data.items():
        pct = data.get("change_pct")
        if pct is None:
            continue
        if pct <= -5:
            opps.append({"ticker": ticker, "name": data["name"],
                         "price": data.get("price"), "change_pct": pct, "level": "strong"})
        elif pct <= -3:
            opps.append({"ticker": ticker, "name": data["name"],
                         "price": data.get("price"), "change_pct": pct, "level": "moderate"})
    opps.sort(key=lambda x: x["change_pct"])
    return opps


def get_important_dates_countdown():
    """Return IMPORTANT_DATES with days-until countdown."""
    jst = pytz.timezone("Asia/Tokyo")
    now = datetime.now(jst)
    results = []
    for item in IMPORTANT_DATES:
        dt = jst.localize(datetime.strptime(item["date"], "%Y-%m-%d"))
        days_away = (dt.date() - now.date()).days
        if days_away >= -1:   # include yesterday
            results.append({
                **item,
                "days_away": days_away,
                "label": "🔥 今日！" if days_away == 0
                         else ("明日" if days_away == 1 else
                               ("昨日" if days_away == -1 else f"{days_away}日後")),
                "urgent": days_away <= 1,
            })
    return results


def get_index_data():
    indices = {}
    for ticker, name in INDICES.items():
        try:
            t    = yf.Ticker(ticker)
            hist = t.history(period="5d", interval="1d")
            info = t.info

            if len(hist) >= 2:
                prev    = float(hist["Close"].iloc[-2])
                current = float(hist["Close"].iloc[-1])
            elif len(hist) == 1:
                current = float(hist["Close"].iloc[-1])
                prev    = float(info.get("previousClose", current))
            else:
                current = float(info.get("regularMarketPrice") or 0)
                prev    = float(info.get("previousClose", current))

            change     = current - prev
            change_pct = (change / prev * 100) if prev else 0

            indices[ticker] = {
                "name":       name,
                "value":      round(current, 2),
                "change":     round(change, 2),
                "change_pct": round(change_pct, 2),
            }
        except Exception as e:
            indices[ticker] = {"name": name, "value": None, "change": None,
                               "change_pct": None, "error": str(e)}
    return indices


def _frankfurter_get(url, retries=2):
    for attempt in range(retries):
        try:
            r = requests.get(url, timeout=12)
            if r.status_code == 200:
                return r.json()
        except Exception:
            if attempt < retries - 1:
                time.sleep(1)
    return None


def get_currency_data():
    jst       = pytz.timezone("Asia/Tokyo")
    now       = datetime.now(jst)
    today     = now.strftime("%Y-%m-%d")
    yday      = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    week_ago  = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    mon_start = (now - timedelta(days=30)).strftime("%Y-%m-%d")

    all_bases = {f for f, _ in CURRENCY_PAIRS}
    latest, previous, series = {}, {}, {}

    for base in all_bases:
        d = _frankfurter_get(f"https://api.frankfurter.app/latest?from={base}")
        if d:
            latest[base] = d.get("rates", {})
            latest[base][base] = 1.0

        d = _frankfurter_get(f"https://api.frankfurter.app/{yday}?from={base}")
        if d:
            previous[base] = d.get("rates", {})
            previous[base][base] = 1.0

        d = _frankfurter_get(f"https://api.frankfurter.app/{mon_start}..{today}?from={base}")
        if d:
            series[base] = d.get("rates", {})

    currencies = {}
    for frm, to in CURRENCY_PAIRS:
        key       = f"{frm}/{to}"
        rate      = latest.get(frm, {}).get(to)
        prev_rate = previous.get(frm, {}).get(to)
        day_chg   = round((rate - prev_rate) / prev_rate * 100, 3) if (rate and prev_rate and prev_rate != 0) else None

        week_rate = None
        if frm in series:
            for d in sorted(series[frm].keys()):
                if d >= week_ago:
                    week_rate = series[frm][d].get(to)
                    break
        week_chg = round((rate - week_rate) / week_rate * 100, 2) if (rate and week_rate and week_rate != 0) else None

        vals       = [v.get(to) for v in series.get(frm, {}).values() if v.get(to)] if frm in series else []
        month_high = round(max(vals), 4) if vals else None
        month_low  = round(min(vals), 4) if vals else None

        currencies[key] = {
            "from": frm, "to": to,
            "rate":            round(rate, 4) if rate else None,
            "day_change_pct":  day_chg,
            "week_change_pct": week_chg,
            "month_high":      month_high,
            "month_low":       month_low,
        }
    return currencies

# ============================================================
# Portfolio Config — purchase price tracking
# ============================================================

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "portfolio_config.json")


def load_portfolio_config(stocks, currencies):
    """Load existing purchase config, or create one from today's prices (first run)."""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, encoding="utf-8") as f:
            return json.load(f)

    usd_jpy = currencies.get("USD/JPY", {}).get("rate") or 155.0
    config  = {"purchase_info": {}, "usd_jpy_at_purchase": usd_jpy,
               "created": datetime.now(pytz.timezone("Asia/Tokyo")).strftime("%Y-%m-%d")}

    for ticker, data in stocks.items():
        if data.get("price") is None:
            continue
        price   = data["price"]
        inv_jpy = data["invested_jpy"]
        is_jpy  = data["is_jpy"]
        shares  = (inv_jpy / price) if is_jpy else (inv_jpy / (price * usd_jpy)) if price and usd_jpy else 0

        config["purchase_info"][ticker] = {
            "price":        round(price, 4),
            "shares":       round(shares, 6),
            "invested_jpy": inv_jpy,
            "date":         datetime.now(pytz.timezone("Asia/Tokyo")).strftime("%Y-%m-%d"),
            "is_jpy":       is_jpy,
        }

    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    print(f"  📝 初回設定ファイルを作成しました: {CONFIG_FILE}")
    return config


def calculate_pnl(stocks, currencies, config):
    """Calculate current profit/loss per stock and total."""
    usd_jpy   = currencies.get("USD/JPY", {}).get("rate") or 155.0
    per_stock = {}
    total_inv = 0
    total_cur = 0

    for ticker, data in stocks.items():
        if data.get("price") is None:
            continue
        purchase = config.get("purchase_info", {}).get(ticker)
        if not purchase:
            continue

        cur_price   = data["price"]
        buy_price   = purchase["price"]
        shares      = purchase["shares"]
        inv_jpy     = purchase["invested_jpy"]
        is_jpy      = data["is_jpy"]

        cur_val_jpy = cur_price * shares if is_jpy else cur_price * shares * usd_jpy
        pnl_jpy     = cur_val_jpy - inv_jpy
        pnl_pct     = (cur_price - buy_price) / buy_price * 100 if buy_price else 0

        per_stock[ticker] = {
            "name":         data["name"],
            "shares":       round(shares, 4),
            "buy_price":    round(buy_price, 2),
            "cur_price":    round(cur_price, 2),
            "invested_jpy": inv_jpy,
            "cur_val_jpy":  round(cur_val_jpy),
            "pnl_jpy":      round(pnl_jpy),
            "pnl_pct":      round(pnl_pct, 2),
            "is_jpy":       is_jpy,
        }
        total_inv += inv_jpy
        total_cur += cur_val_jpy

    return {
        "per_stock":      per_stock,
        "total_invested": round(total_inv),
        "total_current":  round(total_cur),
        "total_pnl":      round(total_cur - total_inv),
        "total_pnl_pct":  round((total_cur - total_inv) / total_inv * 100, 2) if total_inv else 0,
    }

# ============================================================
# News
# ============================================================

def clean_text(text, limit=900):
    text = html_lib.unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def fetch_article_excerpt(url, max_chars=900):
    """Try to scrape meaningful article paragraphs from the URL."""
    if not HAS_BS4:
        return ""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        }
        r = requests.get(url, timeout=7, headers=headers, allow_redirects=True)
        if r.status_code != 200:
            return ""
        soup = BeautifulSoup(r.content, "lxml")
        for tag in soup(["script","style","nav","header","footer","aside","figure","figcaption","iframe"]):
            tag.decompose()
        body = (soup.find("div", class_=re.compile(
                    r"caas-body|article-body|article__body|story-body|post-body|content-body|article-content", re.I))
                or soup.find("article")
                or soup)
        paras = [p.get_text(" ", strip=True) for p in body.find_all("p") if len(p.get_text(strip=True)) > 55]
        return " ".join(paras)[:max_chars].strip()
    except Exception:
        return ""


def analyze_news_impact(title, description, category):
    full = (title + " " + description).lower()

    pos_words = ["beat","exceed","surge","upgrade","buy","strong","record",
                 "growth","raise","bullish","outperform","demand","win",
                 "positive","profit","revenue growth","ai demand","data center",
                 "rate cut","lower rates","boom","autonomous","contract","defense"]
    neg_words = ["miss","cut guidance","fall","downgrade","sell","weak","loss",
                 "layoff","warn","bearish","decline","below","tariff",
                 "risk","recession","default","rate hike","inventory glut",
                 "antitrust","investigation","fine","ban","restrict"]

    pos = sum(1 for w in pos_words if w in full)
    neg = sum(1 for w in neg_words if w in full)

    if pos > neg:   sentiment, emoji = "positive", "📈"
    elif neg > pos: sentiment, emoji = "negative", "📉"
    else:           sentiment, emoji = "neutral",  "📊"

    impact_map = {
        ("NVDA",            "positive"): "NVDAに強気材料。AI・データセンター需要への追い風で株価上昇が期待されます。",
        ("NVDA",            "negative"): "NVDAに注意。ポートフォリオ最大銘柄のため影響大。動向を注視してください。",
        ("KTOS",            "positive"): "防衛需要の拡大はKTOSに有利。ドローン・無人機分野での追い風です。",
        ("KTOS",            "negative"): "KTOSに逆風。防衛予算・契約動向の注視が必要です。",
        ("UPST",            "positive"): "UPSTのAI融資モデルに好材料。金利低下局面で特に恩恵を受けます。",
        ("UPST",            "negative"): "UPSTは金利・信用リスクに敏感。下落に注意してください。",
        ("UBER",            "positive"): "UBERのライドシェア・配達需要に好材料。成長継続が期待されます。",
        ("UBER",            "negative"): "UBERに逆風。競争激化・規制リスクに注意。",
        ("TMC",             "positive"): "深海採掘セクターへの追い風。TMCの事業拡大に期待が持てます。",
        ("TMC",             "negative"): "TMCに下落圧力。投機的銘柄のためリスク管理に注意。",
        ("AI・半導体",      "positive"): "半導体セクター全体に追い風。NVDA・AVGO（保有中）の株価上昇が期待されます。",
        ("AI・半導体",      "negative"): "半導体セクター全体に下押し圧力。NVDA・AVGO（保有中）と購入予定のMUの動向を注視。",
        ("FRB・金利",       "positive"): "金利低下はグロース株に有利。NVDA・UPST・UBERへの追い風になります。",
        ("FRB・金利",       "negative"): "金利上昇はグロース株に不利。ポートフォリオ全体への下落圧力に注意。",
        ("日銀・円相場",    "positive"): "円安継続。ドル建て米国株の円換算価値が上がります。",
        ("日銀・円相場",    "negative"): "円高進行。WISEでのJPY→USD換金チャンスを確認しましょう。",
        ("マレーシア・MYR", "positive"): "MYR強化トレンド。WISEでのMYR保有者にとって有利な状況です。",
        ("マレーシア・MYR", "negative"): "MYR弱化。WISEでMYR→JPY換金を検討するタイミングかもしれません。",
        ("防衛・宇宙",      "positive"): "防衛・宇宙産業への追い風。KTOSに直接恩恵。",
        ("防衛・宇宙",      "negative"): "防衛・宇宙セクターへの逆風。KTOSへの影響を確認してください。",
    }

    impact_text = next(
        (v for (ck, s), v in impact_map.items() if ck in category and s == sentiment),
        "市場にとってポジティブな材料です。" if sentiment == "positive"
        else ("注意が必要なニュースです。ポートフォリオへの影響を確認しましょう。" if sentiment == "negative"
              else "中立的なニュースです。現時点では大きな影響は限定的です。")
    )

    outlook_map = {
        "earnings":      "次の決算発表に注目。",
        "ai":            "AI需要は2025-2026年も継続成長が見込まれます。",
        "interest rate": "今後のFRB会合での発言に引き続き注目。",
        "tariff":        "貿易政策の動向を引き続き注視。",
        "yen":           "日銀の政策変更がある場合は円相場に大きな動きが出る可能性。",
        "memory":        "データセンター向けメモリ需要の回復が株価の鍵を握ります。",
        "defense":       "地政学リスクの動向が防衛株の行方を左右します。",
        "autonomous":    "自律型技術の普及がKTOS・UBERの事業拡大に直結します。",
    }
    outlook = next((v for k, v in outlook_map.items() if k in full), "")

    return {
        "sentiment": sentiment,
        "emoji":     emoji,
        "impact":    f"{emoji} {impact_text}",
        "outlook":   f"🔭 今後の見通し: {outlook}" if outlook else "",
    }


def get_news():
    items = []
    seen  = set()

    stock_feeds = [
        ("NVDA",  "https://finance.yahoo.com/rss/headline?s=NVDA",   "NVDA（NVIDIA）"),
        ("KTOS",  "https://finance.yahoo.com/rss/headline?s=KTOS",   "KTOS（防衛）"),
        ("UPST",  "https://finance.yahoo.com/rss/headline?s=UPST",   "UPST"),
        ("UBER",  "https://finance.yahoo.com/rss/headline?s=UBER",   "UBER"),
        ("TMC",   "https://finance.yahoo.com/rss/headline?s=TMC",    "TMC（深海採掘）"),
        ("AVGO",  "https://finance.yahoo.com/rss/headline?s=AVGO",   "AVGO（Broadcom）"),
        ("MU",    "https://finance.yahoo.com/rss/headline?s=MU",     "MU（Micron）"),
    ]

    for ticker, url, category in stock_feeds:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:3]:
                title = entry.get("title", "").strip()
                if not title or title in seen:
                    continue
                seen.add(title)
                rss_desc     = clean_text(entry.get("description") or entry.get("summary") or "", limit=280)
                article_link = entry.get("link", "")
                full_text    = rss_desc
                if len(rss_desc) < 120 and article_link:
                    fetched = fetch_article_excerpt(article_link, max_chars=280)
                    if fetched:
                        full_text = fetched
                impact = analyze_news_impact(title, full_text, category)
                items.append({
                    "title":    title,
                    "summary":  full_text,
                    "link":     article_link or "#",
                    "category": category,
                    "source":   entry.get("source", {}).get("title", "Yahoo Finance"),
                    "impact":   impact,
                })
        except Exception as e:
            print(f"  Stock news error ({ticker}): {e}")

    macro_queries = [
        ("Federal Reserve interest rate inflation",  "FRB・金利"),
        ("Bank of Japan yen dollar BOJ policy",      "日銀・円相場"),
        ("Malaysia economy ringgit MYR",             "マレーシア・MYR"),
        ("AI semiconductor chip demand nvidia",      "AI・半導体業界"),
        ("NASDAQ stock market technology outlook",   "NASDAQ市場"),
        ("defense drone military autonomous spending","防衛・宇宙"),
        ("SpaceX IPO space industry",                "宇宙・SpaceX"),
    ]

    for query, category in macro_queries:
        try:
            encoded = requests.utils.quote(query)
            feed    = feedparser.parse(
                f"https://news.google.com/rss/search?q={encoded}&hl=en&gl=US&ceid=US:en")
            for entry in feed.entries[:1]:
                title = entry.get("title", "").strip()
                if not title or title in seen:
                    continue
                seen.add(title)
                rss_desc     = clean_text(entry.get("description") or entry.get("summary") or "", limit=280)
                article_link = entry.get("link", "")
                full_text    = rss_desc
                if len(rss_desc) < 100 and article_link:
                    fetched = fetch_article_excerpt(article_link, max_chars=280)
                    if fetched:
                        full_text = fetched
                impact = analyze_news_impact(title, full_text, category)
                items.append({
                    "title":    title,
                    "summary":  full_text,
                    "link":     article_link or "#",
                    "category": category,
                    "source":   entry.get("source", {}).get("title", "Google News"),
                    "impact":   impact,
                })
        except Exception as e:
            print(f"  Macro news error ({category}): {e}")

    return items[:28]

# ============================================================
# Currency Tools
# ============================================================

def jpy_conversion_table(currencies):
    amounts    = [10000, 30000, 50000, 100000]
    conv_pairs = [("USD","JPY"),("MYR","JPY"),("EUR","JPY"),("SGD","JPY"),("AUD","JPY")]
    result     = {}
    for frm, to in conv_pairs:
        key  = f"{frm}/{to}"
        data = currencies.get(key, {})
        rate = data.get("rate")
        if not rate:
            continue
        result[frm] = {
            "rate":        rate,
            "conversions": {amt: round(amt / rate, 2) for amt in amounts},
        }
    return result


def currency_advice(pair, rate, day_change, week_change):
    if rate is None:
        return "データ取得中…"
    wc = week_change or 0
    dc = day_change  or 0
    if pair == "USD/JPY":
        if wc > 2:    return f"円安トレンド継続（{rate:.2f}円）。今ドルを買うのはやや不利。円高を待つのがおすすめ。"
        elif wc < -2: return f"円高進行中（{rate:.2f}円）。今がWISEでJPY→USD換金の好タイミング！"
        elif abs(dc) > 0.5:
            return f"本日{'円安' if dc>0 else '円高'}（{rate:.2f}円）。大きなトレンドには至っていません。"
        return f"USD/JPY: {rate:.2f}円。比較的安定中。急ぎでなければ様子見推奨。"
    elif pair == "MYR/JPY":
        if wc > 1.5:  return f"リンギット強い（{rate:.4f}円）。WISEでMYR→JPY換金のチャンスです。"
        elif wc < -1.5: return f"リンギット弱い（{rate:.4f}円）。今はMYR保持のまま回復を待ちましょう。"
        return f"MYR/JPY: {rate:.4f}円。安定中。"
    elif pair == "USD/MYR":
        return f"USD/MYR: {rate:.4f}。ドルとリンギットの交換レートです。"
    else:
        sym = pair.split("/")[0]
        if wc > 1.5:  return f"{sym}が強い（週間+{wc:.1f}%）。JPYへの換金なら今がチャンスかも。"
        elif wc < -1.5: return f"{sym}が弱い（週間{wc:.1f}%）。しばらく保持を推奨。"
        return f"比較的安定（週間{wc:+.1f}%）。"


def get_wise_myr_advice(currencies, trip_date_str):
    """
    Analyse MYR/JPY rates and give a WISE transfer timing recommendation
    for an upcoming Malaysia trip.  Returns None if no trip date is set or
    the trip has already passed.
    """
    if not trip_date_str:
        return None
    jst = pytz.timezone("Asia/Tokyo")
    now = datetime.now(jst)
    try:
        trip_dt = jst.localize(datetime.strptime(trip_date_str, "%Y-%m-%d"))
    except ValueError:
        return None
    days_until = (trip_dt.date() - now.date()).days
    if days_until < 0:
        return None  # trip already passed

    myr_jpy   = currencies.get("MYR/JPY", {})
    rate      = myr_jpy.get("rate")
    wk_chg    = myr_jpy.get("week_change_pct") or 0
    day_chg   = myr_jpy.get("day_change_pct")  or 0
    month_hi  = myr_jpy.get("month_high")
    month_lo  = myr_jpy.get("month_low")

    # ── Urgency level ──────────────────────────────────────────
    if days_until <= 3:
        urgency = "urgent"
        rec     = "🚨 旅行まで3日以内！今すぐWISEで換金してください。"
    elif days_until <= 7:
        urgency = "urgent"
        rec     = "⏰ 旅行まで1週間以内。今日中にWISEで換金しましょう。"
    elif days_until <= 14:
        if wk_chg <= -1.5:
            urgency = "good"
            rec     = f"✅ 旅行まで{days_until}日。今週円高MYR安（{wk_chg:+.1f}%）＝絶好の換金タイミング！今すぐ換金推奨。"
        elif wk_chg >= 2:
            urgency = "wait"
            rec     = f"🟡 旅行まで{days_until}日。MYR高め（{wk_chg:+.1f}%）。もう少し待って円高を狙えますが、旅行が近いので遅くとも1週間前までに換金を。"
        else:
            urgency = "ok"
            rec     = f"📊 旅行まで{days_until}日。為替は安定中（週間{wk_chg:+.1f}%）。今換金するか、あと数日様子を見るか判断しましょう。"
    else:
        # 15日以上先
        if wk_chg <= -2:
            urgency = "good"
            rec     = f"✅ 今週は円高MYR安（{wk_chg:+.1f}%）。旅行まで{days_until}日ありますが、このタイミングで換金するのはアリです。"
        elif wk_chg >= 2.5:
            urgency = "wait"
            rec     = f"⏳ MYR高トレンド中（{wk_chg:+.1f}%）。旅行まで{days_until}日あるので円高になるまで待ちましょう。"
        else:
            urgency = "watch"
            rec     = f"👀 旅行まで{days_until}日。為替は安定中（週間{wk_chg:+.1f}%）。円高トレンドを確認してから換金がベストです。"

    # ── Rate position vs 1-month range ─────────────────────────
    position_text = ""
    if rate and month_hi and month_lo:
        span = month_hi - month_lo
        if span > 0:
            pos_pct = (rate - month_lo) / span * 100
            if pos_pct < 25:
                position_text = f"📉 現在レートは1ヶ月の安値圏（下位{pos_pct:.0f}%）。換金に有利！"
            elif pos_pct > 75:
                position_text = f"📈 現在レートは1ヶ月の高値圏（上位{100-pos_pct:.0f}%）。もう少し待つと有利になる可能性あり。"
            else:
                position_text = f"📊 現在レートは1ヶ月の中間付近（位置{pos_pct:.0f}%）。標準的なタイミングです。"

    # ── JPY→MYR simulation ─────────────────────────────────────
    sims = {}
    if rate:
        for amt in [5000, 10000, 30000, 50000]:
            sims[amt] = round(amt / rate, 2)

    return {
        "trip_date":    trip_date_str,
        "days_until":   days_until,
        "urgency":      urgency,
        "rate":         rate,
        "week_change":  wk_chg,
        "day_change":   day_chg,
        "month_high":   month_hi,
        "month_low":    month_lo,
        "recommendation": rec,
        "position_text":  position_text,
        "sims":           sims,
    }


def best_currency_to_hold(currencies):
    results = [(d["from"], d["week_change_pct"])
               for d in currencies.values()
               if d.get("to") == "JPY" and d.get("week_change_pct") is not None]
    if not results:
        return None, None
    results.sort(key=lambda x: x[1], reverse=True)
    return results[0]

# ============================================================
# Analysis
# ============================================================

def _sign_color(val):
    if val is None: return "neutral"
    return "positive" if val > 0 else ("negative" if val < 0 else "neutral")

def _arrow(val):
    if val is None: return "－"
    return "▲" if val > 0 else ("▼" if val < 0 else "－")


def generate_overall_summary(stocks, indices, currencies):
    """Return 3-5 plain-Japanese bullet points summarising today at a glance."""
    lines = []
    nasdaq  = indices.get("^IXIC", {})
    sox     = indices.get("^SOX",  {})
    vix     = indices.get("^VIX",  {})
    usd_jpy = currencies.get("USD/JPY", {})

    nq  = nasdaq.get("change_pct") or 0
    sx  = sox.get("change_pct")    or 0
    vx  = vix.get("value")         or 0
    uj  = usd_jpy.get("rate")      or 0
    uj_wk = usd_jpy.get("week_change_pct") or 0

    # ── 市場全体 ──
    if nq >= 1:
        lines.append(f"📈 市場は強気。NASDAQが{nq:+.1f}%上昇し、グロース株全般に追い風。")
    elif nq <= -1:
        lines.append(f"📉 市場は軟調。NASDAQが{nq:+.1f}%下落。保有株の動向を注視して。")
    else:
        lines.append(f"📊 市場は横ばい（NASDAQ {nq:+.1f}%）。大きな動きはなし。")

    if sx >= 1.5:
        lines.append(f"🔵 半導体(SOX)が{sx:+.1f}%上昇。NVDAと購入予定のAVGO・MUに追い風。")
    elif sx <= -1.5:
        lines.append(f"🔴 半導体(SOX)が{sx:+.1f}%下落。NVDA・AVGO・MUへの影響に注意。")

    # ── VIX ──
    if vx > 25:
        lines.append(f"⚠️ VIX {vx:.1f}（高め）。市場に緊張感あり。急いで買わないこと。")
    elif vx <= 15:
        lines.append(f"✅ VIX {vx:.1f}（低め）。市場は落ち着いており安定した状況。")

    # ── 保有株の注目動き ──
    movers = [(t, d) for t, d in stocks.items()
              if d.get("change_pct") is not None and abs(d["change_pct"]) >= 2]
    movers.sort(key=lambda x: abs(x[1]["change_pct"]), reverse=True)
    for t, d in movers[:2]:
        pct = d["change_pct"]
        em  = "📈" if pct > 0 else "📉"
        dir_s = "上昇" if pct > 0 else "下落"
        lines.append(f"{em} {t}が{pct:+.1f}%{dir_s}。本日の保有株で最も大きな動き。")

    # ── 為替 ──
    if uj > 0:
        if uj_wk > 2:
            lines.append(f"💱 円安進行中（USD/JPY {uj:.2f}円）。新規購入コストが上がっているため急ぎは禁物。")
        elif uj_wk < -2:
            lines.append(f"💱 円高チャンス（USD/JPY {uj:.2f}円）。WISEでJPY→USD換金を検討！")

    if not lines:
        lines.append("📊 今日は大きな動きなし。市場は安定しており、普段通りのウォッチを継続。")

    return lines


def market_explanations(indices, currencies):
    exps    = []
    nasdaq  = indices.get("^IXIC", {})
    sox     = indices.get("^SOX",  {})
    vix     = indices.get("^VIX",  {})
    nikkei  = indices.get("^N225", {})
    usd_jpy = currencies.get("USD/JPY", {})

    nq_pct  = nasdaq.get("change_pct") or 0
    sox_pct = sox.get("change_pct") or 0
    vix_val = vix.get("value") or 0
    nk_pct  = nikkei.get("change_pct") or 0
    uj_wk   = usd_jpy.get("week_change_pct") or 0
    uj_rate = usd_jpy.get("rate") or 0

    if abs(nq_pct) > 0.3:
        d = "上昇" if nq_pct > 0 else "下落"
        em = "📈" if nq_pct > 0 else "📉"
        eff = "NVDA・UPST・UBERにとって追い風です。" if nq_pct > 0 else "NVDA・UPST・UBERへの下落圧力に注意。"
        exps.append(f"{em} NASDAQが{abs(nq_pct):.1f}%{d}しました。{eff}")
    if abs(sox_pct) > 0.3:
        d = "上昇" if sox_pct > 0 else "下落"
        em = "🔵" if sox_pct > 0 else "🔴"
        exps.append(f"{em} 半導体指数(SOX)が{abs(sox_pct):.1f}%{d}。NVDAと購入予定のAVGO・MUに直接影響します。")
    if abs(nk_pct) > 0.3:
        d = "上昇" if nk_pct > 0 else "下落"
        exps.append(f"🗾 日経225が{abs(nk_pct):.1f}%{d}。購入予定の東京エレクトロンの動向に注目。")
    if vix_val > 30:
        exps.append(f"🚨 VIX恐怖指数が{vix_val:.1f}！市場は危険ゾーン。新規購入は慎重に。予備資金は温存してください。")
    elif vix_val > 20:
        exps.append(f"⚠️ VIX恐怖指数が{vix_val:.1f}。市場不安定。様子見を推奨します。")
    elif 0 < vix_val <= 20:
        exps.append(f"✅ VIX恐怖指数は{vix_val:.1f}と落ち着いています。市場は比較的安定中です。")
    if abs(uj_wk) > 1 and uj_rate > 0:
        if uj_wk > 0:
            exps.append(f"💱 円安が進んでいます（USD/JPY: {uj_rate:.2f}円）。米国株の円換算価値は上がりますが、新規購入コストも増加します。")
        else:
            exps.append(f"💱 円高が進んでいます（USD/JPY: {uj_rate:.2f}円）。WISEでドルを買う好機かもしれません。")
    if not exps:
        exps.append("📊 今日の市場は比較的安定しています。引き続き定期ウォッチを続けましょう。")
    return exps


def action_recommendations(stocks, indices, currencies):
    actions = []
    vix_val = (indices.get("^VIX") or {}).get("value") or 0
    usd_jpy = currencies.get("USD/JPY") or {}
    jst     = pytz.timezone("Asia/Tokyo")
    today   = datetime.now(jst)
    today_s = today.strftime("%Y-%m-%d")

    # Date-based alerts for IMPORTANT_DATES
    for item in IMPORTANT_DATES:
        dt        = jst.localize(datetime.strptime(item["date"], "%Y-%m-%d"))
        days_away = (dt.date() - today.date()).days
        if days_away == 0:
            if item["type"] == "earnings":
                actions.append(("HIGH",
                    f"🔥 今日は{item['event']}！決算後の動きを見てから購入判断をしましょう。"
                    f"急落なら買いチャンス、急騰なら少し様子見が賢明です。"))
            elif item["type"] == "ipo":
                actions.append(("HIGH", f"🚀 今日は{item['event']}！上場後の初値・値動きに注目。"))
            elif item["type"] == "dividend":
                actions.append(("HIGH", f"💰 今日は{item['event']}！忘れずに確認してください。"))
        elif days_away == 1:
            if item["type"] == "dividend":
                actions.append(("MEDIUM", f"💰 明日は{item['event']}！今日中に保有確認を。"))
            else:
                actions.append(("MEDIUM", f"⏰ 明日は{item['event']}！今日中に情報収集しておきましょう。"))
        elif 2 <= days_away <= 3:
            if item["type"] == "dividend":
                actions.append(("INFO", f"💰 {days_away}日後に{item['event']}。保有継続で自動的に権利取得できます。"))
            else:
                actions.append(("INFO", f"📅 {days_away}日後に{item['event']}があります。事前確認を。"))

    # Stock drop alerts
    for ticker, d in stocks.items():
        pct = d.get("change_pct")
        if pct is None: continue
        if pct <= -10:
            actions.append(("HIGH",
                f"🔴 {d['name']}({ticker})が{pct:.1f}%急落！予備資金での買い増しを強く検討してください。"))
        elif pct <= -5:
            actions.append(("MEDIUM",
                f"🟡 {d['name']}({ticker})が{pct:.1f}%下落中。-10%になれば買い増しシグナルです。"))

    if vix_val > 30:
        actions.append(("HIGH",
            "🚨 VIXが30超え！市場は危険ゾーンです。予備資金は温存し、急いで買わないようにしましょう。"))

    wk = usd_jpy.get("week_change_pct") or 0
    rt = usd_jpy.get("rate") or 0
    if wk < -1.5 and rt > 0:
        actions.append(("MEDIUM",
            f"💱 円高チャンス！WISEでJPY→USD換金→SBIで米国株購入のタイミングです（現在: {rt:.2f}円）。"))
    elif wk > 2 and rt > 0:
        actions.append(("INFO",
            f"💱 円安継続（{rt:.2f}円）。米国株の購入は円高になるまで待つのも一つの選択肢です。"))

    best_c, best_wk = best_currency_to_hold(currencies)
    if best_c and best_wk and best_wk > 1.5:
        actions.append(("INFO",
            f"🏆 今週のWISEで最も強い通貨: {best_c}（対円 +{best_wk:.1f}%）。{best_c}保有者は含み益が出ています。"))

    if today.day <= 5:
        actions.append(("INFO",
            "📅 月初！毎月の積立（¥50,000）を実行しましょう。WISEでUSDに換金後、SBI証券で購入してください。"))

    if not actions:
        actions.append(("INFO", "✅ 今日は特別なアクションは不要です。定期ウォッチを継続しましょう。"))
    return actions


def get_earnings_calendar():
    """Fetch next earnings dates for portfolio + watchlist stocks."""
    watch = ["NVDA","KTOS","UPST","UBER","AVGO","MU","AMD","PLTR","RKLB"]
    results = []
    jst = pytz.timezone("Asia/Tokyo")
    now = datetime.now(jst)
    for ticker in watch:
        try:
            info = yf.Ticker(ticker).info
            ts   = info.get("earningsTimestamp") or info.get("earningsDate")
            if ts:
                dt        = datetime.fromtimestamp(int(ts), tz=jst)
                days_away = (dt.date() - now.date()).days
                if -2 <= days_away <= 30:
                    results.append({
                        "ticker":    ticker,
                        "date":      dt.strftime("%m/%d"),
                        "days_away": days_away,
                        "label":     "今日！" if days_away == 0
                                     else ("明日" if days_away == 1 else f"{days_away}日後"),
                        "urgent":    days_away <= 3,
                    })
        except Exception:
            pass
    results.sort(key=lambda x: x["days_away"])
    return results[:8]

# ============================================================
# Learning Content
# ============================================================

FEATURED_COMPANIES = [
    {
        "name": "🚀 SpaceX（スペースX）",
        "status": "非上場（IPO: SPCX 6月12日予定） | 創業者: イーロン・マスク",
        "what": "世界最先端の民間宇宙企業。Starshipロケット・Starlink衛星インターネット・NASAの月探査契約を保有。打ち上げコストを従来比90%削減し宇宙産業を革命中。",
        "why_now": "6月12日にSPCXとしてIPO予定！評価額は約2,000億ドル超。上場直後の値動きに注目。",
        "relation": "KTOSが手がける無人機・宇宙通信システムとは補完関係。宇宙産業全体への注目度が上がるとKTOSにも追い風。",
    },
    {
        "name": "🤖 NVIDIA（エヌビディア）",
        "status": "NASDAQ上場: NVDA（保有中）| 時価総額 約3兆ドル（世界トップ級）",
        "what": "AI革命の最大受益者。H100・H200・Blackwell GPUはAIデータセンターの標準インフラ。CUDAエコシステムでAI開発者を囲い込んでいる。",
        "why_now": "AIブームで売上が急拡大。2024年度の売上高は600億ドル超。あなたが保有中！株価上昇に直接連動します。",
        "relation": "あなたが保有中！AI需要増 → データセンター投資増 → HBMメモリ需要増 → 購入予定のMUにも恩恵。",
    },
    {
        "name": "🛡️ Palantir（パランティア）",
        "status": "NYSE上場: PLTR | 創業者: ピーター・ティール、アレックス・カープ",
        "what": "AI・ビッグデータ分析の防衛・政府向け専門企業。米軍・CIA・FBIが主要顧客。AIPプラットフォームで民間企業向けAI事業も急拡大中。",
        "why_now": "地政学リスク高まりで防衛AI需要が急増。2024年に初の通年黒字達成。S&P500に採用され機関投資家の買いが加速。",
        "relation": "KTOSと同じ防衛テックセクター。両社とも「AIと防衛の融合」をビジネスモデルとしており、KTOS株の参考指標になる。",
    },
    {
        "name": "💡 OpenAI（オープンAI）",
        "status": "非上場 | CEO: サム・アルトマン | 評価額 約1,570億ドル",
        "what": "ChatGPT・GPT-4oを開発するAI最大手。Microsoft（Azure）と提携しクラウドAIサービスを展開。消費者向けAIの代名詞的存在。",
        "why_now": "2024年に消費者向けサービスの月間アクティブユーザーが2億人超え。企業向けAPIも急成長。IPOの可能性が2025-2026年に議論されている。",
        "relation": "AI需要の象徴的存在。OpenAIが使うGPUはNVIDIA製（あなたが保有中）。購入予定のAVGOのカスタムチップ顧客候補でもある。",
    },
    {
        "name": "🔵 TSMC（台湾積体電路製造）",
        "status": "NYSE上場(ADR): TSM | 本拠地: 台湾 | 時価総額 約8,000億ドル",
        "what": "世界最大の半導体受託製造（ファウンドリ）企業。NVIDIA・Apple・AMD・Broadcomの全てのチップを製造。最先端3nmプロセスを独占。",
        "why_now": "AIブームでN3/N2プロセスの需要が爆発。日本・米国・欧州に工場建設中。地政学的リスク（台湾海峡問題）は常に株価の変動要因。",
        "relation": "購入予定のAVGOのチップはTSMCが製造。購入予定の東京エレクトロンはTSMCへの半導体装置の主要サプライヤー。",
    },
    {
        "name": "🌍 ARM Holdings（ARM）",
        "status": "NASDAQ上場: ARM | 本拠地: 英国ケンブリッジ | 2023年IPO",
        "what": "世界のスマートフォンの99%に搭載されるCPU設計を行うチップ設計会社。Apple・Qualcomm・NVIDIAにライセンス提供。自社製造はせずロイヤリティで収益。",
        "why_now": "AI PCとスマートフォンのAI化でARMアーキテクチャの採用が加速。NVIDIA・Google・AmazonもARM系AIチップを開発中。",
        "relation": "英国企業のため GBP/JPY の動きが株価（円換算）に影響。GBP/JPYをWISEでチェックする価値がある理由のひとつ。",
    },
    {
        "name": "⚡ Anduril Industries（アンデュリル）",
        "status": "非上場 | CEO: パーマー・ラッキー（Oculus創業者） | 評価額 約280億ドル",
        "what": "シリコンバレー発の次世代防衛テック企業。AI搭載の無人機・自律型兵器システム・国境警備技術を開発。ペンタゴンから大型契約を次々獲得。",
        "why_now": "2024年に米国防総省から数千億円規模の複数年契約を獲得。テック人材が国防に本格参入した「防衛テック革命」の象徴的存在。",
        "relation": "KTOSと直接競合する領域（無人機・自律システム）。Andurilへの注目度 = KTOS市場の成長性の証拠。",
    },
    {
        "name": "🛸 Rocket Lab（ロケットラボ）",
        "status": "NASDAQ上場: RKLB | 本拠地: 米国・ニュージーランド",
        "what": "小型衛星打ち上げに特化したロケット会社。ElectronロケットとNeutronロケットを開発。衛星製造・宇宙インフラにも事業拡大中。",
        "why_now": "2024年に打ち上げ回数が急増。NASAや民間企業から受注拡大。SpaceXより小型・安価なロケットとして独自市場を確立。",
        "relation": "KTOSが手がける防衛衛星・宇宙通信と隣接する事業領域。SpaceX IPO（6/12）後の宇宙関連株全体の盛り上がりに注目。",
    },
    {
        "name": "🌊 TMC the metals co.（深海採掘）",
        "status": "NASDAQ上場: TMC（保有中）| 本拠地: カナダ",
        "what": "太平洋深海底の多金属団塊（ニッケル・コバルト・マンガン・銅）を採掘する唯一の上場純粋採掘企業。EV・バッテリー向け金属の海底資源開発。",
        "why_now": "EVシフトで必要なレアメタルの陸上採掘が環境規制で難しくなる中、深海採掘が注目を集めている。規制承認待ちで投機的だが長期的ポテンシャルは巨大。",
        "relation": "あなたが保有中！EV・バッテリー需要の成長に連動する夢の10倍枠銘柄。短期は値動きが荒いため長期保有が基本戦略。",
    },
    {
        "name": "📊 AMD（アドバンスト・マイクロ・デバイシズ）",
        "status": "NASDAQ上場: AMD | CEO: リサ・スー",
        "what": "CPU（Ryzen）とGPU（Radeon・Instinct）を手がけるNVIDIAの最大ライバル。MI300X AIアクセラレーターでデータセンター市場に本格参入。",
        "why_now": "NVIDIAのGPU供給不足を受け、AMDのMI300XをMicrosoftやMetaが採用。NVIDIAほど高値ではなく「割安なAI株」との見方も。",
        "relation": "NVDA（保有中）の競合。AMD株の好調 = AI需要強い = NVDAにも追い風。購入予定のMUのメモリチップはAMDのGPUにも搭載。",
    },
    {
        "name": "🏦 Upstart（アップスタート）詳細解説",
        "status": "NASDAQ上場: UPST（保有中）| CEO: デビッド・ジルバーマン",
        "what": "AIを使った融資審査プラットフォーム。従来の信用スコア（FICO）に代わり、2,000以上のデータポイントでデフォルトリスクを予測。銀行に技術提供するB2Bモデル。",
        "why_now": "金利上昇期に業績が悪化したが、金利低下局面では劇的に回復する傾向。FRBの利下げ期待で2024年以降株価が大きく動いている。",
        "relation": "あなたが保有中！金利とAI融資需要の両方に影響される特殊な銘柄。FRBのニュースが出た日はUPSTを特に注視。",
    },
    {
        "name": "🚗 Uber Technologies（ウーバー）詳細解説",
        "status": "NYSE上場: UBER（保有中）| CEO: ダラ・コスロシャヒ",
        "what": "世界70カ国以上でライドシェア・フードデリバリー（Uber Eats）・貨物輸送を展開するプラットフォーム企業。2023年に初の通年黒字を達成。",
        "why_now": "自律走行車との連携（Waymoと提携）・広告事業拡大・AIルート最適化で新たな収益源を開拓中。",
        "relation": "あなたが保有中！景気動向・ガソリン価格・自律走行車の普及に影響される成長株。NVDA（自動運転AI）との将来的な連携も注目。",
    },
    {
        "name": "🔬 xAI（エックスAI）",
        "status": "非上場 | CEO: イーロン・マスク | 評価額 約500億ドル",
        "what": "イーロン・マスクが2023年に設立したAI企業。Grokというチャットボット（X/Twitter統合）とColossus（世界最大級のAI学習クラスター）を開発。",
        "why_now": "Colossusは100,000台のNVIDIA H100 GPUで構成。MicrosoftのOpenAIへの対抗馬として注目。OpenAIとの競争が激化中。",
        "relation": "xAIの大規模AI学習 → NVIDIA GPU需要増（あなたのNVDAに恩恵）→ HBMメモリ需要増 → 購入予定のMUに直接恩恵。",
    },
    {
        "name": "☁️ Cloudflare（クラウドフレア）",
        "status": "NYSE上場: NET | CEO: マシュー・プリンス",
        "what": "インターネットのセキュリティ・CDN・AIエッジコンピューティングを提供するインフラ企業。世界200都市以上のネットワーク拠点を保有。",
        "why_now": "AI推論をクラウドではなく「エッジ（ユーザー近く）」で行う需要が増加中。Workers AIプラットフォームで開発者を獲得。",
        "relation": "AI・クラウドインフラ関連株として注目。購入予定のAVGOのネットワーキングチップの最終ユーザー的な存在。",
    },
]

INDUSTRY_TRENDS = [
    {
        "title": "🤖 AI半導体戦争：NVIDIA vs AMD vs カスタムチップ",
        "content": "NVIDIAがH100/H200/Blackwellで市場の80%以上を独占する中、AMDのMI300X、GoogleのTPU、AmazonのTrainium、MetaのMTIAなどカスタムチップが追い上げ中。Broadcom（AVGO）はカスタムAIチップ設計でGoogleとMeta向けに急成長。この競争が続くほどHBMメモリ（MUの主力）の需要は拡大し続けます。",
        "impact": "あなたの保有株への影響：NVDA ↑ 購入予定：AVGO・MU ↑",
    },
    {
        "title": "💾 HBMメモリ革命：AIが変えるメモリ産業",
        "content": "HBM（High Bandwidth Memory）はAIチップに積み上げる超高速メモリ。従来のDRAMの10倍以上の帯域幅を持ち、ChatGPTなどAIモデルの学習・推論に不可欠。世界シェアはSK Hynix約50%、Micron（MU）・Samsung（三星）が追う構図。Micronは2024-2025年にHBM3E生産を本格化しNVIDIAへの供給を増やしています。",
        "impact": "購入予定のMU 直接恩恵（HBM売上急増）、保有中のNVDA 需要増",
    },
    {
        "title": "🛸 防衛テックの台頭：シリコンバレーが戦争を変える",
        "content": "Anduril・Palantir・Shield AI・Kratos（KTOS）など「DefenseTech」企業が急成長。伝統的な軍事企業（Lockheed、Raytheon）に代わり、AI・無人機・自律システムが主役に。米国防総省はAI・ドローン予算を急拡大中。地政学リスク（ウクライナ・台湾）で需要が恒常化しています。",
        "impact": "あなたの保有株への影響：KTOS 直接恩恵（無人機・ドローン）",
    },
    {
        "title": "🌍 半導体サプライチェーンの再編",
        "content": "米中対立を背景に「半導体の脱中国依存」が世界規模で進行中。米国のCHIPS法（520億ドル補助金）、日本の半導体助成（TSMC熊本工場支援）、欧州CHIPS法など各国が国内製造を強化。東京エレクトロン（TEL）は半導体製造装置の世界3位として全方位で恩恵を受けています。",
        "impact": "購入予定の東京エレクトロン 中長期追い風",
    },
    {
        "title": "🚀 宇宙産業の民営化：New Space時代",
        "content": "SpaceX・Rocket Lab・Blue Origin（Amazon）など民間宇宙企業が急増。打ち上げコストが過去30年で99%削減され、宇宙ビジネスが一般企業にも開放されました。6月12日にSpaceXがSPCXとしてIPO予定！宇宙関連の市場規模は2040年までに1兆ドル超と試算されています。",
        "impact": "あなたの保有株への影響：KTOS（宇宙通信・防衛衛星分野に参入）",
    },
    {
        "title": "💳 AIフィンテック：融資を変えるUPSTの技術",
        "content": "従来の銀行融資は「FICO信用スコア」という単純な指標に頼っていましたが、Upstartは2,000以上のデータを使いAIで融資リスクを評価。その結果、デフォルト率を75%削減しながら融資承認率を2倍以上に改善。ただし金利上昇期には銀行パートナーが融資を絞るため業績が落ちやすい構造上の弱点も。",
        "impact": "あなたの保有株への影響：UPST（金利動向に特に注意が必要）",
    },
    {
        "title": "⚡ データセンターの電力危機とエネルギー株",
        "content": "AI学習・推論に使う電力需要が爆発的に増加。ChatGPT1回の検索はGoogle検索の10倍の電力を消費。米国では2030年までにAIデータセンターが国全体の電力の10%以上を消費すると予測。原子力（Vistra・Constellation）・天然ガス・太陽光など電力株が注目される副次効果も生まれています。",
        "impact": "関連銘柄: Vistra(VST)・Constellation Energy(CEG)・NextEra(NEE)",
    },
]

INVESTMENT_TERMS = [
    {"term": "P/E ratio（株価収益率・PER）",
     "explain": "株価 ÷ 1株当たり純利益（EPS）で計算。例えばPER30倍なら「今の利益の30年分の価格がついている」という意味。一般的にPER15〜25が適正、30以上は割高、10以下は割安とされますが、成長株は高PERが普通です。NVIDIAはPER50〜60倍でも「成長を先取りしている」と評価されています。"},
    {"term": "EPS（一株当たり利益）",
     "explain": "会社の純利益 ÷ 発行済み株式数。例えばEPS $5.00 なら1株につき$5の利益を生み出しているという意味。決算発表では「アナリスト予想EPS」と「実際のEPS」を比較し、上回れば株価上昇・下回れば下落するのが一般的です。"},
    {"term": "時価総額（Market Cap）",
     "explain": "株価 × 発行済み株式総数。会社の「市場での評価額」です。NVIDIAはMega cap（超大型株）約3兆ドル。時価総額が小さい株は大きく動きやすく、大きい株は安定しやすい傾向があります。"},
    {"term": "52週高値・安値",
     "explain": "過去1年間（52週）の最高値と最安値のこと。現在の株価が52週高値に近い場合は「勢いがある」、52週安値に近い場合は「割安の可能性」と見ることができます。"},
    {"term": "RSI（相対力指数）",
     "explain": "0〜100の数値で株の「買われすぎ」「売られすぎ」を示す指標。一般的にRSI70以上 = 買われすぎ（売りシグナル）、RSI30以下 = 売られすぎ（買いシグナル）とされています。"},
    {"term": "ボラティリティ（価格変動率）",
     "explain": "株価がどれだけ大きく動くかを示す指標。NVDAはボラティリティが高い部類で、短期間で±20%動くことも珍しくありません。TMCはさらに高ボラティリティ（投機的銘柄）のため、長期保有が基本です。"},
    {"term": "ETF（上場投資信託）",
     "explain": "複数の株をまとめて一つの商品にしたもの。QQQ（NASDAQ100）・SOXX（半導体指数）・XAR（宇宙・防衛）などが代表例。個別株が難しい場合はETFから始めると分散投資の効果が得られます。"},
    {"term": "空売り（ショート）とロング",
     "explain": "ロング = 株を買って値上がりを期待する通常の投資。空売り（ショート）= 株を借りて売り、値下がりしてから買い戻す手法。個人投資家は基本的にロングだけで十分です。"},
    {"term": "決算（Earnings）の見方",
     "explain": "四半期ごとに発表される会社の成績表。重要ポイント：① 売上高が予想を上回ったか ② EPS（利益）が予想を上回ったか ③ 次四半期のガイダンス（見通し）が強いか。今夜のAVGO決算でこの3点を確認しましょう。"},
    {"term": "ガイダンス（業績見通し）",
     "explain": "決算発表時に会社が示す「次の四半期・年間の売上・利益の見通し」。市場はしばしば実績より「ガイダンス」に反応します。良い決算でも「次の見通しが弱い」と言った瞬間に株価が急落することがあります。今夜のAVGO・来月のMU決算後は特にガイダンスに注目。"},
    {"term": "WISE vs 銀行の為替手数料比較",
     "explain": "銀行でドルを買う際の手数料：三菱UFJ銀行の場合、TTSレートで1ドルあたり約1円（約0.6%）の手数料がかかります。¥50,000を両替すると約¥300〜¥500のコスト。WISEは0.4〜0.6%程度の手数料で、毎月¥50,000を両替するだけで年間数千円の節約になります。"},
    {"term": "配当株 vs 成長株",
     "explain": "配当株：毎年・毎四半期に配当金を支払う株（例：JPモルガン・コカコーラ）。成長株：配当なしで利益を事業拡大に再投資（例：NVDA・UPST・UBER）。あなたのポートフォリオは全て成長株なので、配当収入はなく値上がり益を狙う戦略です。"},
    {"term": "機関投資家と個人投資家の違い",
     "explain": "機関投資家 = 年金基金・投資信託・ヘッジファンドなど大口投資家。市場取引の70〜80%を占め、株価を動かす力があります。13F提出書類（四半期ごとに開示）でウォーレン・バフェットなどの有名投資家が何を買っているか確認できます。"},
]

WISE_TIPS = [
    {"title": "WISEの口座開設と使い方", "content": "WISEは日本の銀行口座から送金・受取・両替ができる多機能口座。口座開設は無料でスマホから10分ほどで完了します。JPY・USD・MYR・EUR・GBPなど50以上の通貨を保有でき、両替手数料は銀行の1/3〜1/5程度。米国株投資家の必須ツールです。"},
    {"title": "WISEでJPY→USDに換金する最適タイミング", "content": "①USD/JPYが1週間単位で下落している時（円高）②VIXが高く市場が不安定な時（今は買いより準備）③月初の積立前に円高を確認してから換金。逆にUSD/JPYが急上昇している時（円安トレンド）は焦って換金せず、円高を待つのが得策です。"},
    {"title": "WISEのレート通知機能を活用", "content": "WISEアプリにはレートアラート機能があります。「USD/JPYが150円以下になったら通知」のように設定しておくと、円高のチャンスを見逃しません。毎日チェックしなくてもスマホに通知が来るので便利。目標レートを設定して待つ「指値換金」戦略に活用できます。"},
    {"title": "MYRをWISEで賢く管理する方法", "content": "マレーシアリンギット（MYR）はアジア通貨の中では比較的安定。WISEでMYRを保有しておき、マレーシアとの取引や旅行時に活用できます。MYR/JPYが強い時（リンギット高）に一部をJPYに換金し、弱い時は保持するのが基本戦略です。"},
    {"title": "WISEのデビットカードで海外ショッピング", "content": "WISEカード（デビット）を使うと海外での支払いもリアルタイムで最安レートで決済されます。クレジットカードの外貨手数料（1.6〜3%）と比べて圧倒的に安い。米国株の配当金を受け取るUSD口座としても活用可能です（SBI証券と組み合わせ）。"},
]


def get_learning_content(indices, currencies, stocks):
    """Return multi-section learning content for the day."""
    today     = datetime.now(pytz.timezone("Asia/Tokyo"))
    day_idx   = today.timetuple().tm_yday

    vix_val    = (indices.get("^VIX") or {}).get("value") or 0
    uj_wk      = (currencies.get("USD/JPY") or {}).get("week_change_pct") or 0
    any_drop10 = any((d.get("change_pct") or 0) <= -10 for d in stocks.values())

    urgent = None
    if vix_val > 25:
        urgent = {"title": "⚠️ VIX急上昇中の対処法",
                  "content": "VIXが25超え。市場が「恐怖」を感じているサインです。でも歴史的に見ると、VIXが高い時こそ優良株が安く買えるチャンスでもあります。ウォーレン・バフェットの名言：「皆が恐れている時に買え」。ただし全力投資は禁物。予備資金を少しずつ使うのが賢明です。"}
    elif any_drop10:
        urgent = {"title": "⚠️ 急落時の判断基準",
                  "content": "保有株が-10%以上下落。パニックで売るのは最も損をする行動です。まず「なぜ下落したか」を確認しましょう。①業績悪化なら慎重に ②市場全体の恐怖なら買い増しのチャンスかも。長期目線で判断することが重要です。"}
    elif abs(uj_wk) > 2:
        urgent = {"title": "💱 為替大きく動いています",
                  "content": f"USD/JPYが週間{uj_wk:+.1f}%動いています。{'円安が進んでいます。米国株の購入は円高を待つのも選択肢。' if uj_wk > 0 else '円高進行中！WISEでJPY→USD換金のチャンスです。今すぐWISEアプリをチェックしてください。'}"}

    return {
        "urgent":  urgent,
        "company": FEATURED_COMPANIES[day_idx % len(FEATURED_COMPANIES)],
        "trend":   INDUSTRY_TRENDS[day_idx % len(INDUSTRY_TRENDS)],
        "term":    INVESTMENT_TERMS[day_idx % len(INVESTMENT_TERMS)],
        "wise":    WISE_TIPS[day_idx % len(WISE_TIPS)],
    }

# ============================================================
# HTML Helpers
# ============================================================

def _learning_html(learning):
    parts = []

    if learning.get("urgent"):
        u = learning["urgent"]
        parts.append(f"""
<div class="learn-item">
  <div class="learn-lbl lu">⚠️ 本日の注意</div>
  <div class="learn-ttl">{u['title']}</div>
  <div class="learn-body">{u['content']}</div>
</div>""")

    c = learning["company"]
    parts.append(f"""
<div class="learn-item">
  <div class="learn-lbl lc">🚀 今日の注目企業</div>
  <div class="learn-ttl">{c['name']}</div>
  <div class="learn-meta">{c['status']}</div>
  <div class="learn-body"><strong>事業内容：</strong>{c['what']}<br><br>
  <strong>今なぜ注目？：</strong>{c['why_now']}<br><br>
  <strong>あなたのポートフォリオとの関係：</strong>{c['relation']}</div>
</div>""")

    t = learning["trend"]
    parts.append(f"""
<div class="learn-item">
  <div class="learn-lbl lt">🔥 業界トレンド</div>
  <div class="learn-ttl">{t['title']}</div>
  <div class="learn-body">{t['content']}</div>
  <div class="learn-impact">📊 {t['impact']}</div>
</div>""")

    tm = learning["term"]
    parts.append(f"""
<div class="learn-item">
  <div class="learn-lbl lk">💡 投資用語</div>
  <div class="learn-ttl">{tm['term']}</div>
  <div class="learn-body">{tm['explain']}</div>
</div>""")

    w = learning["wise"]
    parts.append(f"""
<div class="learn-item">
  <div class="learn-lbl lw">💳 WISE活用法</div>
  <div class="learn-ttl">{w['title']}</div>
  <div class="learn-body">{w['content']}</div>
</div>""")

    return "\n".join(parts)


def _opportunities_html(dates_countdown, watchlist_data, opportunities, earnings, future_purchases):
    parts = []

    # ---- A: 重要スケジュール カウントダウン ----
    if dates_countdown:
        chips = ""
        for d in dates_countdown:
            urgcls = "opp-date-urgent" if d["urgent"] else ""
            icon   = {"earnings": "📊", "ipo": "🚀", "nisa": "🏦", "dividend": "💰"}.get(d["type"], "📅")
            chips += f"""
<div class="opp-date-chip {urgcls}">
  <div class="opp-date-icon">{icon}</div>
  <div class="opp-date-info">
    <div class="opp-date-event">{d['event']}</div>
    <div class="opp-date-label">{d['label']} — {d['date']}</div>
  </div>
</div>"""
        parts.append(f"""
<div class="opp-block">
  <div class="opp-block-ttl">📅 重要スケジュール（カウントダウン）</div>
  <div class="opp-dates">{chips}</div>
</div>""")

    # ---- B: 購入予定銘柄ウォッチ ----
    if future_purchases:
        fp_html = ""
        for fp in future_purchases:
            ticker = fp["ticker"]
            data   = watchlist_data.get(ticker, {})
            price  = data.get("price")
            pct    = data.get("change_pct")
            target = data.get("target")
            price_s = f"${price:,.2f}" if price else "取得中…"
            pct_s   = ""
            if pct is not None:
                col = "positive" if pct > 0 else ("negative" if pct < 0 else "neutral")
                arr = "▲" if pct > 0 else ("▼" if pct < 0 else "－")
                pct_s = f'<span class="{col}">{arr}{abs(pct):.2f}%</span>'
            tgt_s = f'<span class="muted" style="font-size:0.8em">目標: ${target:,.2f}</span>' if target else ""
            fp_html += f"""
<div class="fp-card">
  <div class="fp-header">
    <span class="ticker">{ticker}</span>
    <span class="company"> {fp['name']}</span>
  </div>
  <div class="fp-price">{price_s} {pct_s} {tgt_s}</div>
  <div class="fp-reason">🎯 {fp['reason']}</div>
  <div class="fp-timing">⏰ 購入予定: {fp['timing']}</div>
</div>"""
        parts.append(f"""
<div class="opp-block">
  <div class="opp-block-ttl">🛒 購入予定銘柄ウォッチ（現在値）</div>
  <div class="fp-grid">{fp_html}</div>
</div>""")

    # ---- C: 今日の急落チャンス ----
    if opportunities:
        opp_html = ""
        for o in opportunities:
            lvl_cls = "opp-strong" if o["level"] == "strong" else "opp-mod"
            icon    = "🔥" if o["level"] == "strong" else "👀"
            msg     = ("急落-5%以上！買いを強く検討するタイミングです。" if o["level"] == "strong"
                       else "3%以上の下落。-5%で買いを検討しましょう。")
            price_s = f"${o['price']:,.2f}" if o.get("price") else ""
            opp_html += f"""
<div class="opp-card {lvl_cls}">
  <div class="opp-ticker-row">
    <span class="ticker">{o['ticker']}</span>
    <span class="company"> {o['name']}</span>
    <span class="negative opp-pct">{o['change_pct']:+.2f}%</span>
    <span class="muted" style="font-size:0.82em">{price_s}</span>
  </div>
  <div class="opp-msg">{icon} {msg}</div>
</div>"""
        parts.append(f"""
<div class="opp-block">
  <div class="opp-block-ttl">⚡ 今日の急落チャンス（ウォッチリスト）</div>
  {opp_html}
</div>""")
    else:
        parts.append("""
<div class="opp-block">
  <div class="opp-block-ttl">⚡ 今日の急落チャンス（ウォッチリスト）</div>
  <div class="muted" style="padding:8px;font-size:0.88em">今日はウォッチリスト株に大きな急落は見られません。引き続き定期確認を。</div>
</div>""")

    # ---- D: 決算カレンダー ----
    if earnings:
        chips = ""
        for e in earnings:
            cls  = "urgent" if e["urgent"] else ""
            chips += f'<div class="earn-chip {cls}"><strong>{e["ticker"]}</strong><div class="earn-date">{e["date"]} ({e["label"]})</div></div>'
        parts.append(f"""
<div class="opp-block">
  <div class="opp-block-ttl">📅 今後の決算カレンダー（30日以内）</div>
  <div class="earn-grid">{chips}</div>
  <div class="muted" style="font-size:0.78em;margin-top:8px">※ 決算日は変更される場合があります。事前に確認してください。</div>
</div>""")

    return "\n".join(parts) if parts else '<div class="muted" style="padding:8px">情報を取得中…</div>'

# ============================================================
# HTML Generation
# ============================================================

def _act_icon(msg):
    """Extract leading emoji as action icon."""
    icons = ["🔴","🟡","🚨","💱","🏆","📅","🔥","⏰","✅","⚡"]
    for ic in icons:
        if msg.startswith(ic):
            return ic, msg[len(ic):].lstrip()
    return "•", msg


def generate_html(stocks, indices, currencies, news, actions, pnl, jpy_table,
                  earnings, watchlist_data, opportunities, dates_countdown,
                  myr_advice=None):
    jst      = pytz.timezone("Asia/Tokyo")
    now      = datetime.now(jst)
    weekdays = ["月曜日","火曜日","水曜日","木曜日","金曜日","土曜日","日曜日"]
    date_str = now.strftime(f"%Y年%m月%d日（{weekdays[now.weekday()]}）%H:%M JST")

    mkt_exps    = market_explanations(indices, currencies)
    learning    = get_learning_content(indices, currencies, stocks)
    best_c, bwk = best_currency_to_hold(currencies)

    total_invested = pnl.get("total_invested", 0)
    total_pnl      = pnl.get("total_pnl", 0)
    total_pnl_pct  = pnl.get("total_pnl_pct", 0)

    def fmt_jpy(v):
        return f"¥{v:,}" if v >= 0 else f"-¥{abs(v):,}"

    # ══════════════════════════════════════════════
    # Build HTML blocks — iOS Stocks / Minna Bank style
    # ══════════════════════════════════════════════

    total_col = _sign_color(total_pnl_pct)
    total_arr = _arrow(total_pnl_pct)
    pnl_cls   = "pos" if total_pnl_pct > 0 else ("neg" if total_pnl_pct < 0 else "neu")

    # ── Section 1: Stock rows (iOS Stocks style) ──
    stock_rows = ""
    for ticker, d in stocks.items():
        sym   = "¥" if d["is_jpy"] else "$"
        if d.get("price") is None:
            stock_rows += f"""
<div class="s-row">
  <div class="s-left"><div class="s-ticker">{ticker}</div><div class="s-name">{d['name']}</div></div>
  <div class="s-right"><div class="s-price t2">取得中…</div></div>
</div>"""
            continue
        pct   = d["change_pct"]
        pill  = "pill-g" if pct > 0 else ("pill-r" if pct < 0 else "pill-n")
        pnl_d = pnl.get("per_stock", {}).get(ticker)

        tgt = ""
        if d.get("target_price") and d.get("target_dist") is not None:
            tc = "g" if d["target_dist"] > 0 else "r"
            tgt = f'<span class="t3"> 目標{sym}{d["target_price"]:,}（{d["target_dist"]:+.1f}%）</span>'

        pnl_sub = ""
        if pnl_d:
            pp    = pnl_d["pnl_pct"]
            pp_cl = "tg" if pp > 0 else ("tr" if pp < 0 else "t2")
            pp_ar = "▲" if pp > 0 else ("▼" if pp < 0 else "－")
            pnl_sub = (f'<div class="s-sub">'
                       f'取得 {sym}{pnl_d["buy_price"]:,.2f} → 現在 {sym}{pnl_d["cur_price"]:,.2f}'
                       f'　<span class="{pp_cl}">{pp_ar} {fmt_jpy(pnl_d["pnl_jpy"])} ({pp:+.2f}%)</span>'
                       f'{tgt}</div>')

        alert = ""
        if pct <= -10: alert = '<div class="alert-stripe alert-buy">🔴 -10%以上急落！買い増しシグナル</div>'
        elif pct <= -5: alert = '<div class="alert-stripe alert-watch">🟡 -5%以上の下落。様子見を継続</div>'

        stock_rows += f"""
<div class="s-row">
  <div class="s-left">
    <div class="s-ticker">{ticker}</div>
    <div class="s-name">{d['name']}</div>
  </div>
  <div class="s-right">
    <div class="s-price">{sym}{d['price']:,.2f}</div>
    <div class="pill {pill}">{_arrow(pct)}{abs(pct):.2f}%</div>
  </div>
</div>{pnl_sub}{alert}"""

    pnl_summary = f"""
<div class="pnl-block">
  <div class="pnl-row"><span class="t2">投資総額</span><span>¥{total_invested:,}</span></div>
  <div class="pnl-row"><span class="t2">現在の評価額</span><span>¥{pnl.get('total_current',0):,}</span></div>
  <div class="pnl-row pnl-big">
    <span class="t2">損益合計</span>
    <span class="{'tg' if total_pnl_pct>0 else 'tr' if total_pnl_pct<0 else 't2'}">{total_arr} {fmt_jpy(total_pnl)} ({total_pnl_pct:+.2f}%)</span>
  </div>
</div>"""

    # ── Section 2: Market indices ──
    idx_chips = ""
    for t, d in indices.items():
        if d.get("value") is None:
            idx_chips += f'<div class="idx-chip"><div class="idx-name">{d["name"]}</div><div class="t2">－</div></div>'
            continue
        pct    = d["change_pct"]
        vcls   = "tg" if pct > 0 else ("tr" if pct < 0 else "t2")
        arr    = _arrow(pct)
        vxcls  = ""
        if t == "^VIX":
            vxcls = " vx-d" if d["value"] > 30 else (" vx-w" if d["value"] > 20 else " vx-c")
        idx_chips += f"""
<div class="idx-chip{vxcls}">
  <div class="idx-name">{d['name']}</div>
  <div class="idx-val {vcls}">{d['value']:,.2f}</div>
  <div class="idx-chg {vcls}">{arr} {abs(pct):.2f}%</div>
</div>"""

    mkt_notes = "".join(f'<div class="mkt-note">{e}</div>' for e in mkt_exps)

    # ── WISE Malaysia trip card ──
    wise_trip_html = ""
    if myr_advice:
        ma       = myr_advice
        urg      = ma["urgency"]
        rate_s   = f"{ma['rate']:,.4f}" if ma.get("rate") else "取得中…"
        wk_s     = f"{ma['week_change']:+.2f}%" if ma.get("week_change") is not None else "—"
        # Urgency colour
        urg_col  = {"urgent": "var(--r)", "good": "var(--g)", "ok": "var(--b)",
                    "wait": "var(--o)", "watch": "var(--t2)"}.get(urg, "var(--t2)")
        urg_bg   = {"urgent": "rgba(255,69,58,.12)", "good": "rgba(48,209,88,.10)",
                    "ok": "rgba(10,132,255,.10)", "wait": "rgba(255,159,10,.10)",
                    "watch": "rgba(255,255,255,.05)"}.get(urg, "rgba(255,255,255,.05)")
        # Countdown badge
        if ma["days_until"] == 0:
            cd_badge = '<span style="color:var(--r);font-weight:700">🚀 今日！</span>'
        elif ma["days_until"] == 1:
            cd_badge = '<span style="color:var(--o);font-weight:700">明日</span>'
        else:
            cd_badge = f'<span style="color:var(--t2)">{ma["days_until"]}日後</span>'
        # Sim rows
        sim_rows = ""
        for jpy_amt, myr_amt in ma["sims"].items():
            sim_rows += f'<div class="trip-sim-row"><span class="t2">¥{jpy_amt:,}</span><span><strong>{myr_amt:,.2f} MYR</strong></span></div>'
        # Month range bar
        range_bar = ""
        if ma.get("month_high") and ma.get("month_low") and ma.get("rate"):
            span = ma["month_high"] - ma["month_low"]
            pos  = (ma["rate"] - ma["month_low"]) / span * 100 if span > 0 else 50
            hi_s = f"{ma['month_high']:,.4f}"; lo_s = f"{ma['month_low']:,.4f}"
            range_bar = f"""
<div class="trip-range">
  <div class="trip-range-lbl"><span class="t3">安値 {lo_s}</span><span class="t3">高値 {hi_s}</span></div>
  <div class="trip-bar-bg"><div class="trip-bar-fill" style="left:{pos:.1f}%"></div></div>
  <div style="font-size:11px;color:var(--t3);text-align:center;margin-top:4px">▲ 現在 {rate_s}</div>
</div>"""
        wise_trip_html = f"""
<div class="card trip-card" style="margin-top:10px">
  <div class="trip-header">
    <div>
      <div class="trip-title">✈️ マレーシア旅行</div>
      <div class="trip-date t2">{ma['trip_date']} まで {cd_badge}</div>
    </div>
    <div style="text-align:right">
      <div style="font-size:22px;font-weight:600">1 MYR</div>
      <div style="font-size:18px;color:var(--t2)">{rate_s} 円</div>
      <div style="font-size:13px;color:var(--t2)">週間 {wk_s}</div>
    </div>
  </div>
  <div class="trip-rec" style="background:{urg_bg};color:{urg_col}">{ma['recommendation']}</div>
  {f'<div class="trip-pos">{ma["position_text"]}</div>' if ma.get("position_text") else ""}
  {range_bar}
  <div class="trip-sim-wrap">
    <div class="trip-sim-ttl">💴 換金シミュレーター（JPY → MYR）</div>
    {sim_rows}
  </div>
</div>"""

    # ── Section 3: Currencies ──
    fx_rows = ""
    for key, d in currencies.items():
        if d.get("rate") is None:
            fx_rows += f'<div class="fx-row"><div><div class="fx-pair">{key}</div></div><div class="t2">－</div></div>'
            continue
        rate   = d["rate"]
        wk     = d.get("week_change_pct") or 0
        dc     = d.get("day_change_pct")  or 0
        wcls   = "tg" if wk > 0 else ("tr" if wk < 0 else "t2")
        pill   = "pill-g" if wk > 0 else ("pill-r" if wk < 0 else "pill-n")
        rate_s = f"{rate:,.2f}" if rate >= 10 else f"{rate:,.4f}"
        hl     = ""
        if d.get("month_high") and d.get("month_low"):
            mh = d["month_high"]; ml = d["month_low"]
            mh_s = f"{mh:,.2f}" if mh >= 10 else f"{mh:,.4f}"
            ml_s = f"{ml:,.2f}" if ml >= 10 else f"{ml:,.4f}"
            hl = f'<div class="fx-hl">1ヶ月: 高値 {mh_s} ／ 安値 {ml_s}</div>'
        adv = currency_advice(key, rate, dc, wk)
        big_mv = f'<div class="fx-big-move">⚠️ 本日大きく動いています（{dc:+.2f}%）</div>' if abs(dc) > 2 else ""
        fx_rows += f"""
<div class="fx-row">
  <div>
    <div class="fx-pair">{key}</div>
    <div class="fx-chg {wcls}">週間 {wk:+.2f}%　本日 {dc:+.2f}%</div>
    {hl}
  </div>
  <div class="fx-right">
    <div class="fx-rate-big">{rate_s}</div>
    <div class="pill {pill} fx-pill">{_arrow(wk)}{abs(wk):.2f}%</div>
  </div>
</div>
<div class="fx-advice-row">💡 {adv}{big_mv}</div>"""

    best_banner = ""
    if best_c and bwk and bwk > 1:
        best_banner = f'<div class="best-banner">🏆 今週WISEで最も強い通貨: <strong>{best_c}</strong>（対円 +{bwk:.1f}%）</div>'

    jpy_conv_html = ""
    if jpy_table:
        amounts = [10000, 30000, 50000, 100000]
        hdr_cells = "".join(f"<th>¥{a:,}</th>" for a in amounts)
        t_rows = ""
        for curr, info in jpy_table.items():
            cells = "".join(f'<td>{info["conversions"][a]:,.2f}</td>' for a in amounts)
            t_rows += f"<tr><td class='conv-curr'>{curr}</td>{cells}</tr>"
        jpy_conv_html = f"""
<div class="conv-wrap">
  <div class="conv-ttl">💴 換金シミュレーター</div>
  <div class="table-scroll">
    <table class="conv-tbl">
      <thead><tr><th>通貨</th>{hdr_cells}</tr></thead>
      <tbody>{t_rows}</tbody>
    </table>
  </div>
  <div class="t3 conv-note">※ 欧州中央銀行レート基準。WISEの実際のレートとは若干異なります。</div>
</div>"""

    # ── Overall summary ──
    summary_lines = generate_overall_summary(stocks, indices, currencies)
    overall_html  = "".join(f'<div class="sum-line">{l}</div>' for l in summary_lines)

    # ── Section 4: News ──
    news_rows = ""
    for item in news:
        impact  = item.get("impact", {})
        sent    = impact.get("sentiment", "neutral")
        imp_cls = {"positive": "imp-pos", "negative": "imp-neg"}.get(sent, "imp-neu")
        imp_txt = impact.get("impact", "")
        summary = (item.get("summary") or "")[:220]
        if len(item.get("summary") or "") > 220:
            summary += "…"
        news_rows += f"""
<div class="news-item">
  <span class="cat-pill">{item['category']}</span>
  <a href="{item['link']}" target="_blank" class="news-ttl">{item['title']}</a>
  {'<div class="news-body">' + summary + '</div>' if summary else ''}
  {'<div class="news-imp ' + imp_cls + '">' + imp_txt + '</div>' if imp_txt else ''}
  <div class="t3 news-src">{item['source']}</div>
</div>"""
    if not news_rows:
        news_rows = '<div class="t2" style="padding:16px">ニュースを取得できませんでした。</div>'

    # ── Section 5: Opportunities ──
    # Dates countdown
    date_rows = ""
    for d in dates_countdown:
        ic    = {"earnings": "📊", "ipo": "🚀", "nisa": "🏦", "dividend": "💰"}.get(d["type"], "📅")
        ucls  = " urg" if d["urgent"] else ""
        date_rows += f"""
<div class="date-row{ucls}">
  <div class="date-icon">{ic}</div>
  <div>
    <div class="date-event">{d['event']}</div>
    <div class="date-cd t3">{d['label']} — {d['date']}</div>
  </div>
</div>"""

    # Future purchases watch
    fp_rows = ""
    for fp in FUTURE_PURCHASES:
        wd    = watchlist_data.get(fp["ticker"], {})
        price = wd.get("price")
        pct_w = wd.get("change_pct")
        tgt_w = wd.get("target")
        ps    = f'${price:,.2f}' if price else '取得中…'
        pp    = ""
        if pct_w is not None:
            pp_cl = "pill-g" if pct_w > 0 else ("pill-r" if pct_w < 0 else "pill-n")
            pp = f'<span class="pill {pp_cl}" style="font-size:12px">{_arrow(pct_w)}{abs(pct_w):.2f}%</span>'
        tgt_s = f'<div class="t3" style="font-size:12px;margin-top:3px">目標 ${tgt_w:,.2f}</div>' if tgt_w else ""
        fp_rows += f"""
<div class="fp-row">
  <div>
    <div class="s-ticker" style="font-size:16px">{fp['ticker']}</div>
    <div class="s-name">{fp['name']}</div>
    <div class="fp-timing">⏰ {fp['timing']}</div>
  </div>
  <div style="text-align:right">
    <div class="s-price" style="font-size:18px">{ps}</div>
    {pp}{tgt_s}
  </div>
</div>"""

    # Watchlist — show ALL stocks, highlight dips
    # Build quick lookup of opportunity tickers
    opp_set = {o["ticker"]: o for o in opportunities}
    dip_rows = ""
    for wt, wname in OPPORTUNITY_WATCHLIST:
        wd    = watchlist_data.get(wt, {})
        wprice = wd.get("price")
        wpct   = wd.get("change_pct")
        wtgt   = wd.get("target")
        ps2    = f'${wprice:,.2f}' if wprice else "取得中"

        if wpct is None:
            pct_html = '<span class="t3">—</span>'
            row_cls  = ""
            badge    = ""
        elif wpct <= -5:
            pct_html = f'<span style="font-size:22px;font-weight:700;color:var(--r)">{wpct:+.2f}%</span>'
            row_cls  = "dip-strong"
            badge    = '<div class="pill pill-r" style="font-size:11px;margin-top:3px">🔥 急落</div>'
        elif wpct <= -3:
            pct_html = f'<span style="font-size:22px;font-weight:700;color:var(--o)">{wpct:+.2f}%</span>'
            row_cls  = "dip-mod"
            badge    = '<div class="pill pill-r" style="font-size:11px;margin-top:3px;background:var(--o);color:#000">👀 下落中</div>'
        elif wpct >= 3:
            pct_html = f'<span style="font-size:20px;font-weight:600;color:var(--g)">{wpct:+.2f}%</span>'
            row_cls  = ""
            badge    = ""
        else:
            pct_html = f'<span style="font-size:20px;font-weight:500;color:var(--t2)">{wpct:+.2f}%</span>'
            row_cls  = ""
            badge    = ""

        tgt_s = f'<div style="font-size:11px;color:var(--t3);margin-top:2px">目標 ${wtgt:,.2f}</div>' if wtgt else ""
        dip_rows += f"""
<div class="dip-row {row_cls}">
  <div class="s-left">
    <div class="s-ticker" style="font-size:17px">{wt}</div>
    <div class="s-name">{wname}</div>
  </div>
  <div style="text-align:right">
    {pct_html}
    <div style="font-size:16px;font-weight:500;margin-top:2px">{ps2}</div>
    {tgt_s}{badge}
  </div>
</div>"""

    # Earnings calendar
    earn_chips = ""
    for e in earnings:
        ecls = " earn-urg" if e["urgent"] else ""
        earn_chips += f'<div class="earn-chip{ecls}"><div style="font-weight:600">{e["ticker"]}</div><div class="earn-d">{e["date"]} {e["label"]}</div></div>'
    earn_section = f'<div class="earn-scroll">{earn_chips}</div>' if earn_chips else '<div class="t3" style="padding:0 16px 12px;font-size:13px">今後30日以内の決算なし</div>'

    # ── Section 6: Actions (Minna Bank list style) ──
    act_rows = ""
    pri_map  = {"HIGH": "act-h", "MEDIUM": "act-m", "INFO": "act-i"}
    for pri, msg in actions:
        icon, text = _act_icon(msg)
        tcls = {"HIGH": "tr", "MEDIUM": "to", "INFO": "t2"}.get(pri, "t2")
        act_rows += f"""
<div class="act-row">
  <div class="act-icon">{icon}</div>
  <div class="act-text {tcls}">{text}</div>
  <div class="act-chev t3">›</div>
</div>"""

    # ── Section 7: Learning ──
    learning = get_learning_content(indices, currencies, stocks)
    learn_html = _learning_html(learning)

    # ══════════════════════════════════════════════
    # Full HTML  (iOS-inspired dark design)
    # ══════════════════════════════════════════════
    month_s = now.strftime("%-m月%-d日")
    time_s  = now.strftime("%H:%M")

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>投資ダッシュボード {now.strftime('%m/%d')}</title>
<style>
:root{{
  --bg:#000;--c1:#1c1c1e;--c2:#2c2c2e;--c3:#3a3a3c;
  --sep:rgba(255,255,255,.1);
  --t1:#fff;--t2:rgba(235,235,245,.75);--t3:rgba(235,235,245,.40);
  --g:#30d158;--r:#ff453a;--b:#0a84ff;--o:#ff9f0a;--y:#ffd60a;--p:#bf5af2;--teal:#5ac8fa;
}}
*{{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}}
html{{background:var(--bg)}}
body{{
  font-family:-apple-system,BlinkMacSystemFont,'Hiragino Sans','Yu Gothic UI',sans-serif;
  background:var(--bg);color:var(--t1);font-size:16px;
  -webkit-font-smoothing:antialiased;
  max-width:430px;margin:0 auto;padding-bottom:48px;
}}
a{{color:var(--b);text-decoration:none}}
.t2{{color:var(--t2)}}.t3{{color:var(--t3)}}
.tg{{color:var(--g)}}.tr{{color:var(--r)}}.to{{color:var(--o)}}

/* ── Header ── */
.hdr{{padding:56px 20px 20px;border-bottom:.5px solid var(--sep)}}
.hdr-lbl{{font-size:13px;color:var(--t3);letter-spacing:.06em;text-transform:uppercase;margin-bottom:4px}}
.hdr-title{{font-size:36px;font-weight:700;letter-spacing:-.5px;line-height:1.1}}
.hdr-time{{font-size:14px;color:var(--t2);margin-top:6px}}
.hdr-pnl{{display:inline-flex;align-items:center;gap:6px;margin-top:14px;padding:7px 16px;border-radius:22px;font-size:16px;font-weight:600}}
.hdr-pnl.pos{{background:rgba(48,209,88,.15);color:var(--g)}}
.hdr-pnl.neg{{background:rgba(255,69,58,.15);color:var(--r)}}
.hdr-pnl.neu{{background:var(--c1);color:var(--t2)}}

/* ── Section wrapper ── */
.pg{{padding:32px 20px 0}}
.pg-ttl{{font-size:24px;font-weight:700;letter-spacing:-.3px;margin-bottom:14px}}
.card{{background:var(--c1);border-radius:14px;overflow:hidden}}
.card+.card{{margin-top:10px}}

/* ── Stock rows (iOS Stocks) ── */
.s-row{{display:flex;align-items:center;justify-content:space-between;padding:13px 16px;border-bottom:.5px solid var(--sep)}}
.s-row:last-of-type{{border-bottom:none}}
.s-left{{flex:1;min-width:0;padding-right:12px}}
.s-right{{text-align:right;flex-shrink:0}}
.s-ticker{{font-size:17px;font-weight:600}}
.s-name{{font-size:13px;color:var(--t2);margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.s-price{{font-size:17px;font-weight:500}}
.s-sub{{padding:5px 16px 9px;font-size:12px;color:var(--t3);background:rgba(255,255,255,.03);border-bottom:.5px solid var(--sep);line-height:1.6}}

/* ── Pills ── */
.pill{{display:inline-block;padding:4px 9px;border-radius:7px;font-size:13px;font-weight:600;margin-top:4px;letter-spacing:-.1px}}
.pill-g{{background:var(--g);color:#000}}
.pill-r{{background:var(--r);color:#fff}}
.pill-n{{background:var(--c2);color:var(--t2)}}

/* ── Alert stripes ── */
.alert-stripe{{padding:8px 16px;font-size:13px;font-weight:500;border-bottom:.5px solid var(--sep)}}
.alert-buy{{background:rgba(255,69,58,.12);color:var(--r)}}
.alert-watch{{background:rgba(255,159,10,.1);color:var(--o)}}

/* ── P&L block ── */
.pnl-block{{background:var(--c1);border-radius:14px;padding:4px 0;margin-top:10px}}
.pnl-row{{display:flex;justify-content:space-between;align-items:center;padding:11px 16px;border-bottom:.5px solid var(--sep);font-size:15px}}
.pnl-row:last-child{{border-bottom:none}}
.pnl-big{{font-size:17px;font-weight:600;padding:14px 16px}}

/* ── Index chips (horizontal scroll) ── */
.idx-scroll{{display:flex;gap:10px;overflow-x:auto;padding-bottom:4px;-webkit-overflow-scrolling:touch;scrollbar-width:none}}
.idx-scroll::-webkit-scrollbar{{display:none}}
.idx-chip{{background:var(--c1);border-radius:14px;padding:13px 14px;min-width:108px;flex-shrink:0;text-align:center}}
.idx-chip.vx-d{{background:rgba(255,69,58,.1)}}
.idx-chip.vx-w{{background:rgba(255,159,10,.08)}}
.idx-chip.vx-c{{background:rgba(48,209,88,.06)}}
.idx-name{{font-size:12px;color:var(--t2);margin-bottom:5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.idx-val{{font-size:19px;font-weight:600}}
.idx-chg{{font-size:13px;margin-top:3px}}
.mkt-note{{background:var(--c1);border-radius:12px;padding:11px 14px;font-size:14px;color:var(--t2);margin-top:8px;line-height:1.6;border-left:3px solid var(--b)}}
.mkt-note+.mkt-note{{margin-top:6px}}

/* ── FX rows ── */
.fx-row{{display:flex;align-items:flex-start;justify-content:space-between;padding:13px 16px;border-bottom:.5px solid var(--sep)}}
.fx-pair{{font-size:17px;font-weight:600}}
.fx-chg{{font-size:13px;margin-top:3px}}
.fx-hl{{font-size:12px;color:var(--t3);margin-top:3px}}
.fx-right{{text-align:right;flex-shrink:0;padding-left:12px}}
.fx-rate-big{{font-size:20px;font-weight:500}}
.fx-pill{{margin-top:4px;display:inline-block}}
.fx-advice-row{{padding:7px 16px 10px;font-size:12px;color:var(--t3);background:rgba(255,255,255,.025);border-bottom:.5px solid var(--sep)}}
.fx-big-move{{color:var(--o);margin-top:3px}}
.best-banner{{background:rgba(10,132,255,.1);border:.5px solid rgba(10,132,255,.3);border-radius:12px;padding:11px 14px;font-size:14px;color:var(--b);margin-bottom:10px}}

/* ── JPY converter ── */
.conv-wrap{{background:var(--c1);border-radius:14px;margin-top:10px;overflow:hidden}}
.conv-ttl{{padding:13px 16px;font-size:15px;font-weight:600;border-bottom:.5px solid var(--sep)}}
.table-scroll{{overflow-x:auto;-webkit-overflow-scrolling:touch}}
.conv-tbl{{width:100%;border-collapse:collapse;font-size:13px}}
.conv-tbl th{{padding:8px 11px;text-align:right;color:var(--t2);font-weight:500;font-size:12px;background:rgba(255,255,255,.03);border-bottom:.5px solid var(--sep)}}
.conv-tbl th:first-child{{text-align:left}}
.conv-tbl td{{padding:9px 11px;text-align:right;border-top:.5px solid var(--sep)}}
.conv-tbl td:first-child{{text-align:left}}
.conv-curr{{font-weight:700;color:var(--b)}}
.conv-note{{padding:8px 14px 12px;font-size:11px}}

/* ── News ── */
.news-item{{padding:14px 16px;border-bottom:.5px solid var(--sep)}}
.news-item:last-child{{border-bottom:none}}
.cat-pill{{display:inline-block;padding:2px 8px;border-radius:5px;font-size:11px;font-weight:600;background:rgba(10,132,255,.15);color:var(--b);margin-bottom:6px}}
.news-ttl{{font-size:15px;font-weight:500;line-height:1.45;color:var(--t1);display:block;margin-bottom:5px}}
.news-ttl:hover{{color:var(--b)}}
.news-body{{font-size:13px;color:var(--t2);line-height:1.65;margin-bottom:7px}}
.news-imp{{font-size:13px;padding:7px 10px;border-radius:8px;margin-bottom:5px;line-height:1.5}}
.imp-pos{{background:rgba(48,209,88,.1);color:var(--g)}}
.imp-neg{{background:rgba(255,69,58,.1);color:var(--r)}}
.imp-neu{{background:rgba(255,255,255,.05);color:var(--t2)}}
.news-out{{font-size:12px;color:var(--t3);padding-left:10px;border-left:2px solid rgba(10,132,255,.3);margin-bottom:5px}}
.news-src{{font-size:11px}}

/* ── Opportunities ── */
.seg-lbl{{font-size:12px;font-weight:600;color:var(--t3);text-transform:uppercase;letter-spacing:.06em;padding:14px 16px 7px}}
.date-row{{display:flex;align-items:center;gap:13px;padding:13px 16px;border-bottom:.5px solid var(--sep)}}
.date-row:last-child{{border-bottom:none}}
.date-row.urg .date-event{{color:var(--o)}}
.date-icon{{font-size:22px;width:34px;text-align:center;flex-shrink:0}}
.date-event{{font-size:15px;font-weight:500}}
.date-cd{{font-size:13px;margin-top:2px}}
.fp-row{{display:flex;align-items:center;justify-content:space-between;padding:13px 16px;border-bottom:.5px solid var(--sep)}}
.fp-row:last-child{{border-bottom:none}}
.fp-timing{{font-size:12px;color:var(--o);margin-top:4px}}
.dip-row{{display:flex;align-items:center;justify-content:space-between;padding:13px 16px;border-bottom:.5px solid var(--sep)}}
.dip-row:last-child{{border-bottom:none}}
.dip-strong{{background:rgba(255,69,58,.06)}}
.dip-mod{{background:rgba(255,159,10,.04)}}
.earn-scroll{{display:flex;gap:8px;overflow-x:auto;padding:12px 16px;-webkit-overflow-scrolling:touch;scrollbar-width:none}}
.earn-scroll::-webkit-scrollbar{{display:none}}
.earn-chip{{background:var(--c2);border-radius:10px;padding:9px 13px;flex-shrink:0;font-size:14px;font-weight:600;text-align:center;min-width:68px}}
.earn-chip.earn-urg{{background:rgba(255,69,58,.2);color:var(--r)}}
.earn-d{{font-size:11px;color:var(--t2);font-weight:400;margin-top:3px}}

/* ── Actions (Minna Bank style) ── */
.act-row{{display:flex;align-items:center;gap:14px;padding:15px 16px;border-bottom:.5px solid var(--sep)}}
.act-row:last-child{{border-bottom:none}}
.act-icon{{font-size:22px;width:34px;text-align:center;flex-shrink:0}}
.act-text{{flex:1;font-size:15px;line-height:1.5}}
.act-chev{{font-size:20px;flex-shrink:0}}

/* ── Learning ── */
.learn-item{{padding:15px 16px;border-bottom:.5px solid var(--sep)}}
.learn-item:last-child{{border-bottom:none}}
.learn-lbl{{font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;margin-bottom:6px}}
.learn-lbl.lc{{color:var(--p)}}.learn-lbl.lt{{color:var(--g)}}.learn-lbl.lk{{color:var(--b)}}.learn-lbl.lw{{color:var(--teal)}}.learn-lbl.lu{{color:var(--y)}}
.learn-ttl{{font-size:16px;font-weight:600;margin-bottom:8px}}
.learn-meta{{font-size:12px;color:var(--t3);margin-bottom:6px}}
.learn-body{{font-size:14px;color:var(--t2);line-height:1.7}}
.learn-impact{{font-size:12px;margin-top:9px;padding:5px 10px;background:rgba(48,209,88,.1);color:var(--g);border-radius:6px}}

/* ── Overall summary ── */
.sum-block{{background:var(--c1);border-radius:14px;padding:14px 16px;margin-bottom:10px}}
.sum-ttl{{font-size:12px;font-weight:700;color:var(--t3);text-transform:uppercase;letter-spacing:.06em;margin-bottom:9px}}
.sum-line{{font-size:14px;color:var(--t2);line-height:1.55;padding:5px 0;border-bottom:.5px solid var(--sep)}}
.sum-line:last-child{{border-bottom:none}}

/* ── WISE Trip card ── */
.trip-card{{overflow:visible}}
.trip-header{{display:flex;align-items:flex-start;justify-content:space-between;padding:14px 16px;border-bottom:.5px solid var(--sep)}}
.trip-title{{font-size:17px;font-weight:700}}
.trip-date{{font-size:13px;margin-top:4px}}
.trip-rec{{padding:11px 14px;font-size:14px;font-weight:500;line-height:1.5;border-bottom:.5px solid var(--sep)}}
.trip-pos{{padding:9px 14px;font-size:13px;color:var(--t2);border-bottom:.5px solid var(--sep)}}
.trip-range{{padding:10px 16px;border-bottom:.5px solid var(--sep)}}
.trip-range-lbl{{display:flex;justify-content:space-between;font-size:11px;margin-bottom:5px}}
.trip-bar-bg{{position:relative;height:6px;background:var(--c3);border-radius:3px;margin:0 2px}}
.trip-bar-fill{{position:absolute;top:-3px;width:12px;height:12px;background:var(--b);border-radius:50%;transform:translateX(-50%);box-shadow:0 0 6px rgba(10,132,255,.6)}}
.trip-sim-wrap{{padding:12px 16px}}
.trip-sim-ttl{{font-size:12px;font-weight:600;color:var(--t3);text-transform:uppercase;letter-spacing:.05em;margin-bottom:9px}}
.trip-sim-row{{display:flex;justify-content:space-between;align-items:center;padding:7px 0;border-bottom:.5px solid var(--sep);font-size:15px}}
.trip-sim-row:last-child{{border-bottom:none}}

/* ── Footer ── */
.footer{{padding:28px 20px;font-size:11px;color:var(--t3);line-height:1.9;border-top:.5px solid var(--sep);margin-top:32px;text-align:center}}
</style>
</head>
<body>

<!-- Header -->
<div class="hdr">
  <div class="hdr-lbl">投資ダッシュボード</div>
  <div class="hdr-title">{month_s}</div>
  <div class="hdr-time">{weekdays[now.weekday()]}　{time_s} JST 更新</div>
  <div class="hdr-pnl {pnl_cls}">{total_arr}&nbsp;{fmt_jpy(total_pnl)}&nbsp;({total_pnl_pct:+.2f}%)</div>
</div>

<!-- ① 保有株 -->
<div class="pg">
  <div class="pg-ttl">📊 保有株</div>
  <div class="card">{stock_rows}</div>
  {pnl_summary}
</div>

<!-- ② 市場 -->
<div class="pg">
  <div class="pg-ttl">🌏 市場状況</div>
  <div class="idx-scroll">{idx_chips}</div>
  {mkt_notes}
</div>

<!-- ③ 為替 -->
<div class="pg">
  <div class="pg-ttl">💱 為替（WISE）</div>
  {best_banner}
  <div class="card">{fx_rows}</div>
  {wise_trip_html}
  {jpy_conv_html}
</div>

<!-- ④ ニュース -->
<div class="pg">
  <div class="pg-ttl">📰 ニュース</div>
  <div class="sum-block">
    <div class="sum-ttl">今日の概要</div>
    {overall_html}
  </div>
  <div class="card">{news_rows}</div>
</div>

<!-- ⑤ 投資チャンス -->
<div class="pg">
  <div class="pg-ttl">⚡ 投資チャンス</div>

  <div class="card">
    <div class="seg-lbl">📅 重要スケジュール</div>
    {date_rows if date_rows else '<div class="t3" style="padding:0 16px 14px;font-size:14px">今後の重要日程なし</div>'}
  </div>

  <div class="card" style="margin-top:10px">
    <div class="seg-lbl">🛒 購入予定銘柄ウォッチ</div>
    {fp_rows}
  </div>

  <div class="card" style="margin-top:10px">
    <div class="seg-lbl">⚡ 今日の急落チャンス</div>
    {dip_rows}
  </div>

  <div class="card" style="margin-top:10px">
    <div class="seg-lbl">📅 決算カレンダー（30日以内）</div>
    {earn_section}
    <div class="t3" style="padding:0 16px 12px;font-size:11px">※ 決算日は変更される場合があります</div>
  </div>
</div>

<!-- ⑥ アクション -->
<div class="pg">
  <div class="pg-ttl">🎯 今日のアクション</div>
  <div class="card">{act_rows}</div>
</div>

<!-- ⑦ 学習 -->
<div class="pg">
  <div class="pg-ttl">📚 学習コーナー</div>
  <div class="card">{learn_html}</div>
</div>

<div class="footer">
  Yahoo Finance・Frankfurter API・Google News<br>
  ※ 情報提供のみ。投資判断は自己責任でお願いします。<br>
  最終更新: {date_str}
</div>

<script>setTimeout(()=>location.reload(),10*60*1000);</script>
</body>
</html>"""

# ============================================================
# Main
# ============================================================

def main():
    print("📊 投資ダッシュボード生成開始...")

    print("  ① 株価データ取得中...")
    stocks = get_stock_data()

    print("  ② 市場指数取得中...")
    indices = get_index_data()

    print("  ③ 為替データ取得中...")
    currencies = get_currency_data()

    print("  ④ ポートフォリオ設定読み込み中...")
    config = load_portfolio_config(stocks, currencies)

    print("  ⑤ 損益計算中...")
    pnl = calculate_pnl(stocks, currencies, config)

    print("  ⑥ 換金シミュレーター計算中...")
    jpy_table = jpy_conversion_table(currencies)

    print("  ⑦ 決算カレンダー取得中...")
    earnings = get_earnings_calendar()

    print("  ⑧ ウォッチリスト・投資チャンス取得中...")
    watchlist_data   = get_watchlist_data()
    opportunities    = get_investment_opportunities(watchlist_data)
    dates_countdown  = get_important_dates_countdown()

    print("  ⑨ ニュース取得中（記事本文を取得しています）...")
    news = get_news()

    print("  ⑩ アクション・アドバイス生成中...")
    actions = action_recommendations(stocks, indices, currencies)

    print("  ⑪ WISE旅行タイミング計算中...")
    trip_date_str = config.get("malaysia_trip_date", "")
    myr_advice    = get_wise_myr_advice(currencies, trip_date_str)
    if myr_advice:
        print(f"     ✈️ マレーシア旅行まで {myr_advice['days_until']}日 / 推奨: {myr_advice['urgency']}")
    else:
        print("     ℹ️ malaysia_trip_date が未設定（portfolio_config.json で設定可能）")

    print("  ⑫ HTML生成中...")
    html = generate_html(
        stocks, indices, currencies, news, actions, pnl, jpy_table,
        earnings, watchlist_data, opportunities, dates_countdown,
        myr_advice=myr_advice
    )

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"✅ 完了！ → {out}")
    print(f"   損益: {'+' if pnl['total_pnl'] >= 0 else ''}¥{pnl['total_pnl']:,} ({pnl['total_pnl_pct']:+.2f}%)")
    if opportunities:
        print(f"   ⚡ チャンス銘柄: {', '.join(o['ticker'] for o in opportunities)}")


if __name__ == "__main__":
    main()
