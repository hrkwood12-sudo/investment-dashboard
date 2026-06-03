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
    "KTOS":  {"name": "Kratos Defense",     "invested_jpy": 21225, "monthly_jpy": 0},
    "UPST":  {"name": "Upstart Holdings",   "invested_jpy": 10820, "monthly_jpy": 0},
    "UBER":  {"name": "Uber Technologies",  "invested_jpy": 11416, "monthly_jpy": 0},
    "TMC":   {"name": "TMC the metals co.", "invested_jpy": 4784,  "monthly_jpy": 0},
}

# Future planned purchases (not yet held, watching for right entry)
FUTURE_PURCHASES = [
    {"ticker": "AVGO",   "name": "Broadcom Inc.",     "reason": "AI半導体・安定成長",       "timing": "今夜決算後"},
    {"ticker": "MU",     "name": "Micron Technology", "reason": "AIメモリ・2倍狙いメイン", "timing": "6月24日決算後"},
    {"ticker": "8035.T", "name": "東京エレクトロン", "reason": "円建て・AI半導体装置",     "timing": "NISA本開設後"},
]

# Important upcoming dates (manually maintained)
IMPORTANT_DATES = [
    {"date": "2026-06-03", "event": "AVGO 決算発表（今夜！）",    "ticker": "AVGO", "type": "earnings"},
    {"date": "2026-06-12", "event": "SpaceX IPO（SPCX上場予定）", "ticker": None,   "type": "ipo"},
    {"date": "2026-06-24", "event": "MU 決算発表",                "ticker": "MU",   "type": "earnings"},
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
        ("AI・半導体",      "positive"): "半導体セクター全体に追い風。NVDAの株価上昇が期待されます。",
        ("AI・半導体",      "negative"): "半導体セクター全体に下押し圧力。NVDA・購入予定のAVGO・MUの動向を注視。",
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
                rss_desc     = clean_text(entry.get("description") or entry.get("summary") or "")
                article_link = entry.get("link", "")
                full_text    = rss_desc
                if len(rss_desc) < 200 and article_link:
                    fetched = fetch_article_excerpt(article_link)
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
            for entry in feed.entries[:2]:
                title = entry.get("title", "").strip()
                if not title or title in seen:
                    continue
                seen.add(title)
                rss_desc     = clean_text(entry.get("description") or entry.get("summary") or "")
                article_link = entry.get("link", "")
                full_text    = rss_desc
                if len(rss_desc) < 150 and article_link:
                    fetched = fetch_article_excerpt(article_link)
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

    return items[:25]

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
                ticker = item["ticker"] or ""
                actions.append(("HIGH",
                    f"🔥 今日は{item['event']}！決算後の動きを見てから購入判断をしましょう。"
                    f"急落なら買いチャンス、急騰なら少し様子見が賢明です。"))
            elif item["type"] == "ipo":
                actions.append(("HIGH", f"🚀 今日は{item['event']}！上場後の初値・値動きに注目。"))
        elif days_away == 1:
            actions.append(("MEDIUM", f"⏰ 明日は{item['event']}！今日中に情報収集しておきましょう。"))
        elif 2 <= days_away <= 3:
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
<div class="learn-card urgent">
  <div class="learn-label">⚠️ 本日の注意</div>
  <div class="learn-ttl">{u['title']}</div>
  <div class="learn-body">{u['content']}</div>
</div>""")

    c = learning["company"]
    parts.append(f"""
<div class="learn-card company">
  <div class="learn-label">🚀 今日の注目企業</div>
  <div class="learn-ttl">{c['name']}</div>
  <div class="learn-status">{c['status']}</div>
  <div class="learn-body"><strong>事業内容：</strong>{c['what']}<br><br>
  <strong>今なぜ注目？：</strong>{c['why_now']}<br><br>
  <strong>あなたのポートフォリオとの関係：</strong>{c['relation']}</div>
</div>""")

    t = learning["trend"]
    parts.append(f"""
<div class="learn-card trend">
  <div class="learn-label">🔥 業界トレンド解説</div>
  <div class="learn-ttl">{t['title']}</div>
  <div class="learn-body">{t['content']}</div>
  <div class="learn-impact">📊 {t['impact']}</div>
</div>""")

    tm = learning["term"]
    parts.append(f"""
<div class="learn-card term">
  <div class="learn-label">💡 今日の投資用語</div>
  <div class="learn-ttl">{tm['term']}</div>
  <div class="learn-body">{tm['explain']}</div>
</div>""")

    w = learning["wise"]
    parts.append(f"""
<div class="learn-card wise">
  <div class="learn-label">💳 WISE活用法</div>
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
            icon   = {"earnings": "📊", "ipo": "🚀", "nisa": "🏦"}.get(d["type"], "📅")
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

def generate_html(stocks, indices, currencies, news, actions, pnl, jpy_table,
                  earnings, watchlist_data, opportunities, dates_countdown):
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

    # -------- Section 1: Stocks with inline P&L --------
    stocks_html = ""
    for ticker, d in stocks.items():
        if d.get("price") is None:
            stocks_html += (f'<div class="stock-card neutral-border">'
                            f'<span class="ticker">{ticker}</span> '
                            f'<span class="company">{d["name"]}</span> '
                            f'<span class="neutral">— データ取得中</span></div>')
            continue

        sym   = "¥" if d["is_jpy"] else "$"
        pct   = d["change_pct"]
        col   = _sign_color(pct)
        arr   = _arrow(pct)

        # Analyst target
        t_html = ""
        if d["target_price"] and d["target_dist"] is not None:
            tc = "positive" if d["target_dist"] > 0 else "negative"
            t_html = (f'<div class="stock-meta">アナリスト目標: {sym}{d["target_price"]:,} '
                      f'<span class="{tc}">({d["target_dist"]:+.1f}%)</span></div>')

        # Inline P&L
        pnl_d = pnl.get("per_stock", {}).get(ticker)
        pnl_html = ""
        if pnl_d:
            pcol = _sign_color(pnl_d["pnl_pct"])
            parr = _arrow(pnl_d["pnl_pct"])
            pnl_html = (f'<div class="stock-pnl">'
                        f'<span class="muted">取得: {sym}{pnl_d["buy_price"]:,.2f}</span>'
                        f'<span class="muted pnl-arrow">→</span>'
                        f'<span>現在: {sym}{pnl_d["cur_price"]:,.2f}</span>'
                        f'<span class="{pcol} pnl-inline">{parr} {fmt_jpy(pnl_d["pnl_jpy"])} '
                        f'({pnl_d["pnl_pct"]:+.2f}%)</span>'
                        f'</div>')

        # Alert
        alert = ""
        if pct <= -10: alert = '<div class="alert buy-alert">🔴 -10%以上の急落！予備資金での買い増しシグナル！</div>'
        elif pct <= -5: alert = '<div class="alert watch-alert">🟡 -5%以上の下落。-10%で買い増し検討。</div>'

        stocks_html += f"""
<div class="stock-card {col}-border">
  <div class="stock-header">
    <div><span class="ticker">{ticker}</span><span class="company"> {d['name']}</span></div>
    <div class="stock-price {col}">{sym}{d['price']:,.2f} <span class="change">{arr}{abs(d['change']):.2f}（{pct:+.2f}%）</span></div>
  </div>
  {t_html}
  {pnl_html}
  {alert}
</div>"""

    # P&L total bar
    total_col = _sign_color(total_pnl_pct)
    total_arr = _arrow(total_pnl_pct)
    pnl_total_html = f"""
<div class="pnl-total {total_col}-border">
  <div class="pnl-total-row"><span>投資総額</span><span>¥{total_invested:,}</span></div>
  <div class="pnl-total-row"><span>現在の評価額</span><span>¥{pnl.get('total_current',0):,}</span></div>
  <div class="pnl-total-row big {total_col}">
    <span>損益合計</span>
    <span>{total_arr} {fmt_jpy(total_pnl)} ({total_pnl_pct:+.2f}%)</span>
  </div>
</div>"""

    # -------- Section 2: Indices --------
    idx_html = ""
    for ticker, d in indices.items():
        if d.get("value") is None:
            idx_html += (f'<div class="index-card neutral-border">'
                         f'<div class="index-name">{d["name"]}</div><div class="neutral">－</div></div>')
            continue
        pct     = d["change_pct"]
        col     = _sign_color(pct)
        arr     = _arrow(pct)
        vix_cls = ""
        if ticker == "^VIX":
            vix_cls = "vix-danger" if d["value"] > 30 else ("vix-warn" if d["value"] > 20 else "vix-calm")
        idx_html += f"""
<div class="index-card {col}-border {vix_cls}">
  <div class="index-name">{d['name']}</div>
  <div class="index-value {col}">{d['value']:,.2f}</div>
  <div class="index-change {col}">{arr} {abs(pct):.2f}%</div>
</div>"""
    mkt_html = "".join(f'<div class="mkt-exp">{e}</div>' for e in mkt_exps)

    # -------- Section 3: Currencies --------
    fx_html = ""
    for key, d in currencies.items():
        if d.get("rate") is None:
            fx_html += f'<div class="fx-card"><div class="fx-pair">{key}</div><div class="neutral">－</div></div>'
            continue
        rate  = d["rate"]
        wk    = d.get("week_change_pct") or 0
        dc    = d.get("day_change_pct")  or 0
        col   = _sign_color(wk)
        arr   = _arrow(wk)
        adv   = currency_advice(key, rate, dc, wk)
        rate_s = f"{rate:,.2f}" if rate >= 10 else f"{rate:,.4f}"
        hl_html = ""
        if d.get("month_high") and d.get("month_low"):
            mh = d["month_high"]; ml = d["month_low"]
            mh_s = f"{mh:,.2f}" if mh >= 10 else f"{mh:,.4f}"
            ml_s = f"{ml:,.2f}" if ml >= 10 else f"{ml:,.4f}"
            hl_html = f'<div class="fx-hl">1ヶ月: 高値{mh_s} / 安値{ml_s}</div>'
        big_alert = (f'<div class="fx-alert">⚠️ 本日大きく動いています（{dc:+.2f}%）！</div>'
                     if abs(dc) > 2 else "")
        fx_html += f"""
<div class="fx-card">
  <div class="fx-pair">{key}</div>
  <div class="fx-rate">{rate_s}</div>
  <div class="fx-change {col}">{arr} 週間 {wk:+.2f}%　|　本日 {dc:+.2f}%</div>
  {hl_html}
  {big_alert}
  <div class="fx-advice">💡 {adv}</div>
</div>"""

    best_html = (f'<div class="best-fx">🏆 今週WISEで最も強い通貨: <strong>{best_c}</strong>（対円 +{bwk:.1f}%）</div>'
                 if (best_c and bwk and bwk > 1) else "")

    # JPY Conversion Table
    jpy_conv_html = ""
    if jpy_table:
        amounts = [10000, 30000, 50000, 100000]
        headers = "".join(f"<th>¥{a:,}</th>" for a in amounts)
        rows    = ""
        for curr, info in jpy_table.items():
            cells = "".join(f'<td>{info["conversions"][a]:,.2f} {curr}</td>' for a in amounts)
            rows += f"<tr><td class='curr-name'>{curr}</td>{cells}</tr>"
        jpy_conv_html = f"""
<div class="jpy-conv">
  <div class="jpy-conv-title">💴 日本円換金シミュレーター（今すぐ両替すると）</div>
  <div class="table-wrap">
    <table class="conv-table">
      <thead><tr><th>通貨</th>{headers}</tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
  <div class="muted" style="font-size:0.78em;margin-top:6px">※ Frankfurter API（欧州中央銀行レート）に基づく参考値。WISEの実際のレートとは若干異なる場合があります。</div>
</div>"""

    # -------- Section 4: News --------
    news_html = ""
    for item in news:
        summary_html = f'<div class="news-summary">{item["summary"]}</div>' if item.get("summary") else ""
        impact       = item.get("impact", {})
        impact_html  = ""
        outlook_html = ""
        if impact:
            sent        = impact.get("sentiment", "neutral")
            cls         = {"positive":"impact-pos","negative":"impact-neg"}.get(sent,"impact-neu")
            impact_html  = f'<div class="news-impact {cls}">{impact.get("impact","")}</div>'
            if impact.get("outlook"):
                outlook_html = f'<div class="news-outlook">{impact["outlook"]}</div>'
        news_html += f"""
<div class="news-item">
  <span class="news-cat">{item['category']}</span>
  <a href="{item['link']}" target="_blank" class="news-title">{item['title']}</a>
  {summary_html}
  {impact_html}
  {outlook_html}
  <span class="news-src">{item['source']}</span>
</div>"""
    if not news_html:
        news_html = '<div class="muted" style="padding:10px">ニュースを取得できませんでした。</div>'

    # -------- Section 5: Opportunities --------
    opps_html = _opportunities_html(dates_countdown, watchlist_data, opportunities, earnings, FUTURE_PURCHASES)

    # -------- Section 6: Actions --------
    pri_cls    = {"HIGH":"act-high","MEDIUM":"act-med","INFO":"act-info"}
    action_html = ""
    for pri, msg in actions:
        action_html += f'<div class="act-item {pri_cls.get(pri,"act-info")}">{msg}</div>'

    # -------- Full HTML --------
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>📊 投資ダッシュボード {now.strftime('%m/%d')}</title>
<style>
:root{{
  --bg:#0d1117;--bg2:#161b22;--bg3:#1c2128;--border:#30363d;
  --txt:#e6edf3;--muted:#8b949e;--dim:#6e7681;
  --blue:#58a6ff;--green:#3fb950;--red:#f85149;--yellow:#d29922;
  --purple:#bc8cff;--orange:#ffa657;
}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Hiragino Sans','Yu Gothic UI',sans-serif;background:var(--bg);color:var(--txt);line-height:1.6;padding:12px;font-size:15px}}
a{{color:var(--blue)}}
.hdr{{text-align:center;padding:18px 0 14px;border-bottom:1px solid var(--border);margin-bottom:18px}}
.hdr h1{{font-size:1.6em;color:var(--blue)}}
.hdr .dt{{color:var(--muted);font-size:0.85em;margin-top:4px}}
.hdr .sub{{color:var(--dim);font-size:0.8em;margin-top:2px}}
.hdr .pnl-badge{{display:inline-block;margin-top:8px;padding:4px 14px;border-radius:20px;font-size:0.9em;font-weight:bold}}
.pnl-badge.positive{{background:rgba(63,185,80,.15);color:var(--green);border:1px solid rgba(63,185,80,.3)}}
.pnl-badge.negative{{background:rgba(248,81,73,.15);color:var(--red);border:1px solid rgba(248,81,73,.3)}}
.pnl-badge.neutral{{background:rgba(139,148,158,.1);color:var(--muted);border:1px solid var(--border)}}
.sec{{margin-bottom:20px}}
.sec-ttl{{font-size:1.05em;font-weight:bold;padding:9px 14px;background:var(--bg2);border-radius:8px 8px 0 0;border-left:4px solid var(--blue)}}
.sec-body{{background:var(--bg2);border-radius:0 0 8px 8px;padding:12px;border:1px solid var(--border);border-top:none}}

/* Stocks */
.stock-card{{background:var(--bg3);border-radius:8px;padding:12px;margin-bottom:8px;border-left:4px solid var(--border)}}
.positive-border{{border-left-color:var(--green)}}
.negative-border{{border-left-color:var(--red)}}
.neutral-border{{border-left-color:var(--border)}}
.stock-header{{display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:6px}}
.ticker{{font-weight:bold;font-size:1.05em;color:var(--blue)}}
.company{{color:var(--muted);font-size:0.85em}}
.stock-price{{font-size:1.1em;font-weight:bold}}.change{{font-size:0.82em;margin-left:6px}}
.stock-meta{{font-size:0.8em;color:var(--muted);margin-top:4px}}
.stock-pnl{{display:flex;flex-wrap:wrap;gap:8px;font-size:0.84em;margin-top:6px;padding:6px 8px;background:var(--bg2);border-radius:5px;align-items:center}}
.pnl-arrow{{color:var(--dim)}}
.pnl-inline{{font-weight:bold}}
.muted{{color:var(--muted)}}
.alert{{margin-top:8px;padding:7px 10px;border-radius:6px;font-size:0.88em}}
.buy-alert{{background:rgba(248,81,73,.12);color:var(--red);border:1px solid rgba(248,81,73,.3)}}
.watch-alert{{background:rgba(210,153,34,.12);color:var(--yellow);border:1px solid rgba(210,153,34,.3)}}
.positive{{color:var(--green)}}.negative{{color:var(--red)}}.neutral{{color:var(--muted)}}

/* P&L Total */
.pnl-total{{border-radius:8px;padding:12px;border-left:4px solid var(--border);background:var(--bg3);margin-top:10px}}
.pnl-total-row{{display:flex;justify-content:space-between;padding:4px 0;font-size:0.9em;border-bottom:1px solid var(--border)}}
.pnl-total-row:last-child{{border-bottom:none}}
.pnl-total-row.big{{font-size:1.05em;font-weight:bold;padding-top:8px}}

/* Indices */
.idx-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(145px,1fr));gap:8px}}
.index-card{{background:var(--bg3);border-radius:8px;padding:11px;text-align:center;border-left:3px solid var(--border)}}
.index-name{{font-size:0.78em;color:var(--muted);margin-bottom:3px}}
.index-value{{font-size:1.15em;font-weight:bold}}.index-change{{font-size:0.82em}}
.vix-danger{{background:rgba(248,81,73,.08)}}.vix-warn{{background:rgba(210,153,34,.08)}}.vix-calm{{background:rgba(63,185,80,.05)}}
.mkt-exp{{padding:9px 12px;margin-bottom:7px;background:var(--bg3);border-radius:6px;border-left:3px solid var(--blue);font-size:0.9em}}
.mkt-exps{{margin-top:12px}}

/* Currencies */
.fx-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:8px}}
.fx-card{{background:var(--bg3);border-radius:8px;padding:12px}}
.fx-pair{{font-weight:bold;color:var(--blue);font-size:0.95em}}
.fx-rate{{font-size:1.25em;font-weight:bold;margin:3px 0}}
.fx-change{{font-size:0.82em}}.fx-hl{{font-size:0.78em;color:var(--dim);margin-top:3px}}
.fx-alert{{margin-top:5px;padding:4px 8px;background:rgba(210,153,34,.15);color:var(--yellow);border-radius:4px;font-size:0.8em}}
.fx-advice{{margin-top:7px;font-size:0.82em;color:var(--muted);line-height:1.45}}
.best-fx{{padding:10px 12px;margin-bottom:10px;background:rgba(88,166,255,.08);border:1px solid rgba(88,166,255,.2);border-radius:8px;font-size:0.9em}}
.jpy-conv{{margin-top:14px;background:var(--bg3);border-radius:8px;padding:12px}}
.jpy-conv-title{{font-weight:bold;color:var(--blue);margin-bottom:8px;font-size:0.95em}}
.table-wrap{{overflow-x:auto}}
.conv-table{{width:100%;border-collapse:collapse;font-size:0.85em}}
.conv-table th{{background:var(--bg2);padding:7px 10px;text-align:right;color:var(--muted);font-weight:normal;border-bottom:1px solid var(--border)}}
.conv-table th:first-child{{text-align:left}}
.conv-table td{{padding:7px 10px;text-align:right;border-bottom:1px solid var(--border)}}
.conv-table td:first-child{{text-align:left}}
.conv-table tr:last-child td{{border-bottom:none}}
.curr-name{{font-weight:bold;color:var(--blue)}}

/* News */
.news-item{{padding:12px 0;border-bottom:1px solid var(--border);display:flex;flex-direction:column;gap:4px}}
.news-item:last-child{{border-bottom:none}}
.news-cat{{font-size:0.72em;background:rgba(88,166,255,.15);color:var(--blue);padding:2px 8px;border-radius:10px;width:fit-content}}
.news-title{{color:var(--txt);text-decoration:none;font-size:0.92em;line-height:1.4;font-weight:500}}
.news-title:hover{{color:var(--blue);text-decoration:underline}}
.news-summary{{font-size:0.85em;color:#c9d1d9;line-height:1.6;margin-top:3px}}
.news-impact{{margin-top:6px;padding:7px 10px;border-radius:6px;font-size:0.84em;line-height:1.5}}
.news-outlook{{margin-top:4px;padding:5px 10px;border-radius:6px;font-size:0.8em;color:var(--muted);background:rgba(88,166,255,.05);border-left:2px solid rgba(88,166,255,.3)}}
.impact-pos{{background:rgba(63,185,80,.1);color:#3fb950;border-left:3px solid rgba(63,185,80,.4)}}
.impact-neg{{background:rgba(248,81,73,.1);color:#f85149;border-left:3px solid rgba(248,81,73,.4)}}
.impact-neu{{background:rgba(139,148,158,.08);color:var(--muted);border-left:3px solid rgba(139,148,158,.3)}}
.news-src{{font-size:0.72em;color:var(--dim)}}

/* Opportunities Section 5 */
.opp-block{{margin-bottom:14px;padding-bottom:14px;border-bottom:1px solid var(--border)}}
.opp-block:last-child{{border-bottom:none;margin-bottom:0;padding-bottom:0}}
.opp-block-ttl{{font-size:0.88em;font-weight:bold;color:var(--muted);margin-bottom:8px;letter-spacing:.03em}}
.opp-dates{{display:flex;flex-direction:column;gap:7px}}
.opp-date-chip{{display:flex;align-items:center;gap:10px;padding:9px 12px;background:var(--bg3);border-radius:8px;border-left:3px solid var(--border)}}
.opp-date-chip.opp-date-urgent{{border-left-color:var(--orange);background:rgba(255,166,87,.06)}}
.opp-date-icon{{font-size:1.2em}}
.opp-date-event{{font-size:0.92em;font-weight:bold}}
.opp-date-label{{font-size:0.78em;color:var(--muted);margin-top:1px}}
.fp-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px}}
.fp-card{{background:var(--bg3);border-radius:8px;padding:11px;border-left:3px solid var(--purple)}}
.fp-header{{margin-bottom:4px}}
.fp-price{{font-size:1em;font-weight:bold;margin-bottom:4px}}
.fp-reason{{font-size:0.8em;color:var(--muted);margin-bottom:2px}}
.fp-timing{{font-size:0.8em;color:var(--orange)}}
.opp-card{{background:var(--bg3);border-radius:8px;padding:11px;margin-bottom:7px}}
.opp-strong{{border-left:3px solid var(--red);background:rgba(248,81,73,.05)}}
.opp-mod{{border-left:3px solid var(--yellow);background:rgba(210,153,34,.05)}}
.opp-ticker-row{{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:4px}}
.opp-pct{{font-weight:bold;font-size:0.95em}}
.opp-msg{{font-size:0.84em;color:var(--muted)}}
.earn-grid{{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px}}
.earn-chip{{padding:5px 10px;border-radius:6px;font-size:0.82em;background:var(--bg2);border:1px solid var(--border)}}
.earn-chip.urgent{{border-color:var(--red);color:var(--red)}}
.earn-date{{font-size:0.75em;color:var(--muted)}}

/* Actions */
.act-item{{padding:11px 13px;border-radius:8px;margin-bottom:7px;font-size:0.92em}}
.act-high{{background:rgba(248,81,73,.1);border:1px solid rgba(248,81,73,.3);color:var(--red)}}
.act-med{{background:rgba(210,153,34,.1);border:1px solid rgba(210,153,34,.3);color:var(--yellow)}}
.act-info{{background:rgba(88,166,255,.05);border:1px solid rgba(88,166,255,.2);color:var(--muted)}}

/* Learning */
.learn-card{{background:var(--bg3);border-radius:8px;padding:14px;margin-bottom:10px;border-left:4px solid var(--blue)}}
.learn-card.urgent{{border-left-color:var(--yellow);background:rgba(210,153,34,.06)}}
.learn-card.company{{border-left-color:var(--purple)}}
.learn-card.trend{{border-left-color:var(--green)}}
.learn-card.term{{border-left-color:var(--blue)}}
.learn-card.wise{{border-left-color:#79c0ff}}
.learn-label{{font-size:0.72em;font-weight:bold;letter-spacing:.05em;text-transform:uppercase;margin-bottom:5px;color:var(--muted)}}
.learn-ttl{{font-weight:bold;font-size:1em;margin-bottom:7px;color:var(--txt)}}
.learn-body{{font-size:0.87em;line-height:1.7;color:#c9d1d9}}
.learn-impact{{margin-top:8px;font-size:0.82em;padding:5px 9px;background:rgba(63,185,80,.1);color:#3fb950;border-radius:5px}}
.learn-status{{font-size:0.78em;color:var(--dim);margin-bottom:5px}}

.footer{{text-align:center;padding:16px;color:var(--dim);font-size:0.75em;border-top:1px solid var(--border);margin-top:20px;line-height:1.8}}
@media(max-width:480px){{
  .idx-grid{{grid-template-columns:repeat(2,1fr)}}
  .fx-grid{{grid-template-columns:1fr}}
  .fp-grid{{grid-template-columns:1fr}}
  .stock-price{{font-size:1em}}
  .stock-pnl{{gap:5px}}
}}
</style>
</head>
<body>

<div class="hdr">
  <h1>📊 毎朝の投資ダッシュボード</h1>
  <div class="dt">{date_str}</div>
  <div class="sub">投資額: ¥{total_invested:,} | 毎月積立: ¥50,000（6月〜）| NVDA・KTOS・UPST・UBER・TMC</div>
  <div class="pnl-badge {_sign_color(total_pnl_pct)}">{_arrow(total_pnl_pct)} 損益合計: {fmt_jpy(total_pnl)} ({total_pnl_pct:+.2f}%)</div>
</div>

<!-- ① 保有株の損益・株価・アラート -->
<div class="sec">
  <div class="sec-ttl">📊 保有株の損益・株価・アラート</div>
  <div class="sec-body">
    {stocks_html}
    {pnl_total_html}
  </div>
</div>

<!-- ② 市場状況 -->
<div class="sec">
  <div class="sec-ttl">🌏 市場状況（なぜ動いたか日本語解説）</div>
  <div class="sec-body">
    <div class="idx-grid">{idx_html}</div>
    <div class="mkt-exps">{mkt_html}</div>
  </div>
</div>

<!-- ③ 為替ダッシュボード -->
<div class="sec">
  <div class="sec-ttl">💱 為替ダッシュボード（WISE対応）</div>
  <div class="sec-body">
    {best_html}
    <div class="fx-grid">{fx_html}</div>
    {jpy_conv_html}
  </div>
</div>

<!-- ④ ニュース -->
<div class="sec">
  <div class="sec-ttl">📰 ニュース全文（要約・現状・今後・影響）</div>
  <div class="sec-body">{news_html}</div>
</div>

<!-- ⑤ 新しい投資チャンス -->
<div class="sec">
  <div class="sec-ttl">⚡ 新しい投資チャンス</div>
  <div class="sec-body">
    {opps_html}
  </div>
</div>

<!-- ⑥ おすすめアクション -->
<div class="sec">
  <div class="sec-ttl">🎯 今日のおすすめアクション</div>
  <div class="sec-body">{action_html}</div>
</div>

<!-- ⑦ 学習コーナー -->
<div class="sec">
  <div class="sec-ttl">📚 学習コーナー</div>
  <div class="sec-body">
    {_learning_html(learning)}
  </div>
</div>

<div class="footer">
  データソース: Yahoo Finance（株価・指数）/ Frankfurter API（為替）/ Yahoo Finance RSS + Google News（ニュース）<br>
  ※このダッシュボードは情報提供のみです。投資判断は自己責任でお願いします。<br>
  最終更新: {date_str}
</div>

<script>setTimeout(() => location.reload(), 10 * 60 * 1000);</script>
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

    print("  ⑪ HTML生成中...")
    html = generate_html(
        stocks, indices, currencies, news, actions, pnl, jpy_table,
        earnings, watchlist_data, opportunities, dates_countdown
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
