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
    "MU":     {"name": "Micron Technology",  "invested_jpy": 65000, "monthly_jpy": 30000},
    "AVGO":   {"name": "Broadcom Inc.",       "invested_jpy": 15000, "monthly_jpy": 5000},
    "8035.T": {"name": "東京エレクトロン",    "invested_jpy": 5000,  "monthly_jpy": 5000},
    "UPST":   {"name": "Upstart Holdings",    "invested_jpy": 5000,  "monthly_jpy": 0},
    "KTOS":   {"name": "Kratos Defense",      "invested_jpy": 10000, "monthly_jpy": 0},
}

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
    "MU":     0.30,
    "AVGO":   0.22,
    "8035.T": 0.20,
    "UPST":   0.35,
    "KTOS":   0.18,
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
            indices[ticker] = {"name": name, "value": None, "change": None, "change_pct": None, "error": str(e)}
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
    config  = {"purchase_info": {}, "usd_jpy_at_purchase": usd_jpy, "created": datetime.now(pytz.timezone("Asia/Tokyo")).strftime("%Y-%m-%d")}

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
    usd_jpy      = currencies.get("USD/JPY", {}).get("rate") or 155.0
    per_stock    = {}
    total_inv    = 0
    total_cur    = 0

    for ticker, data in stocks.items():
        if data.get("price") is None:
            continue
        purchase = config.get("purchase_info", {}).get(ticker)
        if not purchase:
            continue

        cur_price  = data["price"]
        buy_price  = purchase["price"]
        shares     = purchase["shares"]
        inv_jpy    = purchase["invested_jpy"]
        is_jpy     = data["is_jpy"]

        cur_val_jpy = cur_price * shares if is_jpy else cur_price * shares * usd_jpy
        pnl_jpy     = cur_val_jpy - inv_jpy
        pnl_pct     = (cur_price - buy_price) / buy_price * 100 if buy_price else 0

        per_stock[ticker] = {
            "name":          data["name"],
            "shares":        round(shares, 4),
            "buy_price":     round(buy_price, 2),
            "cur_price":     round(cur_price, 2),
            "invested_jpy":  inv_jpy,
            "cur_val_jpy":   round(cur_val_jpy),
            "pnl_jpy":       round(pnl_jpy),
            "pnl_pct":       round(pnl_pct, 2),
            "is_jpy":        is_jpy,
        }
        total_inv += inv_jpy
        total_cur += cur_val_jpy

    return {
        "per_stock":       per_stock,
        "total_invested":  round(total_inv),
        "total_current":   round(total_cur),
        "total_pnl":       round(total_cur - total_inv),
        "total_pnl_pct":   round((total_cur - total_inv) / total_inv * 100, 2) if total_inv else 0,
    }


def generate_predictions(stocks, currencies, config):
    """Generate 1-year and 2-year portfolio value predictions."""
    usd_jpy  = currencies.get("USD/JPY", {}).get("rate") or 155.0
    preds    = {}
    tot_inv  = 0
    tot_1y   = 0
    tot_2y   = 0

    for ticker, data in stocks.items():
        if data.get("price") is None:
            continue
        purchase = config.get("purchase_info", {}).get(ticker)
        if not purchase:
            continue

        cur   = data["price"]
        shr   = purchase["shares"]
        inv   = purchase["invested_jpy"]
        is_jpy = data["is_jpy"]

        # 1-year target
        t1    = data.get("target_price")
        if not t1:
            t1 = round(cur * (1 + SECTOR_GROWTH_1Y.get(ticker, 0.15)), 2)

        # 2-year: apply year-1 gain rate a second time (moderately discounted)
        g1    = (t1 - cur) / cur if cur else 0
        t2    = round(t1 * (1 + g1 * 0.65), 2)

        v1    = t1 * shr if is_jpy else t1 * shr * usd_jpy
        v2    = t2 * shr if is_jpy else t2 * shr * usd_jpy

        preds[ticker] = {
            "name":      data["name"],
            "cur":       cur,
            "t1":        t1,
            "t2":        t2,
            "v1_jpy":    round(v1),
            "v2_jpy":    round(v2),
            "pnl1_jpy":  round(v1 - inv),
            "pnl1_pct":  round((v1 - inv) / inv * 100, 1) if inv else 0,
            "pnl2_jpy":  round(v2 - inv),
            "pnl2_pct":  round((v2 - inv) / inv * 100, 1) if inv else 0,
            "is_jpy":    is_jpy,
            "source":    "アナリスト予測" if data.get("target_price") else "業界成長率推計",
        }
        tot_inv += inv
        tot_1y  += v1
        tot_2y  += v2

    preds["__total__"] = {
        "invested": round(tot_inv),
        "v1":       round(tot_1y),
        "v2":       round(tot_2y),
        "pnl1":     round(tot_1y - tot_inv),
        "pnl1_pct": round((tot_1y - tot_inv) / tot_inv * 100, 1) if tot_inv else 0,
        "pnl2":     round(tot_2y - tot_inv),
        "pnl2_pct": round((tot_2y - tot_inv) / tot_inv * 100, 1) if tot_inv else 0,
    }
    return preds

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
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        }
        r = requests.get(url, timeout=7, headers=headers, allow_redirects=True)
        if r.status_code != 200:
            return ""
        soup = BeautifulSoup(r.content, "lxml")
        for tag in soup(["script", "style", "nav", "header", "footer", "aside", "figure", "figcaption", "iframe"]):
            tag.decompose()
        # Try common article containers
        body = (soup.find("div", class_=re.compile(r"caas-body|article-body|article__body|story-body|post-body|content-body|article-content", re.I))
                or soup.find("article")
                or soup)
        paras = [p.get_text(" ", strip=True) for p in body.find_all("p") if len(p.get_text(strip=True)) > 55]
        text  = " ".join(paras)
        return text[:max_chars].strip()
    except Exception:
        return ""


def analyze_news_impact(title, description, category):
    full = (title + " " + description).lower()

    pos_words = ["beat", "exceed", "surge", "upgrade", "buy", "strong", "record",
                 "growth", "raise", "bullish", "outperform", "demand", "win",
                 "positive", "profit", "revenue growth", "ai demand", "data center",
                 "rate cut", "lower rates", "boom"]
    neg_words = ["miss", "cut guidance", "fall", "downgrade", "sell", "weak", "loss",
                 "layoff", "warn", "bearish", "decline", "below", "tariff",
                 "risk", "recession", "default", "rate hike", "inventory glut",
                 "antitrust", "investigation", "fine"]

    pos = sum(1 for w in pos_words if w in full)
    neg = sum(1 for w in neg_words if w in full)

    if pos > neg:   sentiment, emoji = "positive", "📈"
    elif neg > pos: sentiment, emoji = "negative", "📉"
    else:           sentiment, emoji = "neutral",  "📊"

    impact_map = {
        ("MU",            "positive"): "MUに強気材料。株価上昇・アナリスト目標引き上げの可能性があります。",
        ("MU",            "negative"): "MUに弱気材料。-10%下落時の買い増しシグナルを準備しておきましょう。",
        ("AVGO",          "positive"): "AVGOのAI/ネットワーク需要に追い風。上昇トレンド継続の可能性。",
        ("AVGO",          "negative"): "AVGOに下落圧力。短期的な調整に注意。",
        ("UPST",          "positive"): "UPSTのAI融資モデルに好材料。金利低下局面で特に恩恵を受けます。",
        ("UPST",          "negative"): "UPSTは金利・信用リスクに敏感。下落に注意してください。",
        ("KTOS",          "positive"): "防衛需要の拡大はKTOSに有利。ドローン・無人機分野での追い風。",
        ("KTOS",          "negative"): "KTOSに逆風。防衛予算・契約動向の注視が必要です。",
        ("東京エレクトロン","positive"): "東京エレクトロンに好材料。半導体装置の需要増加が期待されます。",
        ("東京エレクトロン","negative"): "東京エレクトロンに注意。半導体設備投資の動向を確認してください。",
        ("AI・半導体",    "positive"): "半導体セクター全体に追い風。MU・AVGOの株価上昇が期待されます。",
        ("AI・半導体",    "negative"): "半導体セクター全体に下押し圧力。MU・AVGOの動向を注視。",
        ("FRB・金利",     "positive"): "金利低下はグロース株に有利。MU・UPST・AVGOへの追い風になります。",
        ("FRB・金利",     "negative"): "金利上昇はグロース株に不利。ポートフォリオ全体への下落圧力に注意。",
        ("日銀・円相場",  "positive"): "円安継続。ドル建て米国株の円換算価値が上がります。",
        ("日銀・円相場",  "negative"): "円高進行。WISEでのJPY→USD換金チャンスを確認しましょう。",
        ("マレーシア・MYR","positive"): "MYR強化トレンド。WISEでのMYR保有者にとって有利な状況です。",
        ("マレーシア・MYR","negative"): "MYR弱化。WISEでMYR→JPY換金を検討するタイミングかもしれません。",
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

    # Yahoo Finance RSS — stock specific with real article descriptions
    stock_feeds = [
        ("MU",     "https://finance.yahoo.com/rss/headline?s=MU",    "MU（Micron）"),
        ("AVGO",   "https://finance.yahoo.com/rss/headline?s=AVGO",  "AVGO（Broadcom）"),
        ("UPST",   "https://finance.yahoo.com/rss/headline?s=UPST",  "UPST"),
        ("KTOS",   "https://finance.yahoo.com/rss/headline?s=KTOS",  "KTOS（防衛）"),
        ("8035.T", "https://finance.yahoo.com/rss/headline?s=8035.T","東京エレクトロン"),
    ]

    for ticker, url, category in stock_feeds:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:3]:
                title = entry.get("title", "").strip()
                if not title or title in seen:
                    continue
                seen.add(title)
                # Try RSS description first, then try fetching the actual article
                rss_desc = clean_text(entry.get("description") or entry.get("summary") or "")
                article_link = entry.get("link", "")
                full_text = rss_desc
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

    # Google News RSS — macro and sector
    macro_queries = [
        ("Federal Reserve interest rate inflation",  "FRB・金利"),
        ("Bank of Japan yen dollar BOJ policy",      "日銀・円相場"),
        ("Malaysia economy ringgit MYR",             "マレーシア・MYR"),
        ("AI semiconductor chip demand nvidia",      "AI・半導体業界"),
        ("NASDAQ stock market technology outlook",   "NASDAQ市場"),
        ("defense drone military spending",          "防衛・宇宙"),
    ]

    for query, category in macro_queries:
        try:
            encoded = requests.utils.quote(query)
            feed    = feedparser.parse(f"https://news.google.com/rss/search?q={encoded}&hl=en&gl=US&ceid=US:en")
            for entry in feed.entries[:2]:
                title = entry.get("title", "").strip()
                if not title or title in seen:
                    continue
                seen.add(title)
                rss_desc = clean_text(entry.get("description") or entry.get("summary") or "")
                article_link = entry.get("link", "")
                full_text = rss_desc
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
    """Return how much you get for key JPY amounts."""
    amounts    = [10000, 30000, 50000, 100000]
    conv_pairs = [("USD", "JPY"), ("MYR", "JPY"), ("EUR", "JPY"), ("SGD", "JPY"), ("AUD", "JPY")]
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
        if wc > 2:   return f"円安トレンド継続（{rate:.2f}円）。今ドルを買うのはやや不利。円高を待つのがおすすめ。"
        elif wc < -2:return f"円高進行中（{rate:.2f}円）。今がWISEでJPY→USD換金の好タイミング！"
        elif abs(dc) > 0.5:
            return f"本日{'円安' if dc>0 else '円高'}（{rate:.2f}円）。大きなトレンドには至っていません。"
        return f"USD/JPY: {rate:.2f}円。比較的安定中。急ぎでなければ様子見推奨。"
    elif pair == "MYR/JPY":
        if wc > 1.5: return f"リンギット強い（{rate:.4f}円）。WISEでMYR→JPY換金のチャンスです。"
        elif wc < -1.5:return f"リンギット弱い（{rate:.4f}円）。今はMYR保持のまま回復を待ちましょう。"
        return f"MYR/JPY: {rate:.4f}円。安定中。"
    elif pair == "USD/MYR":
        return f"USD/MYR: {rate:.4f}。ドルとリンギットの交換レートです。"
    else:
        sym = pair.split("/")[0]
        if wc > 1.5: return f"{sym}が強い（週間+{wc:.1f}%）。JPYへの換金なら今がチャンスかも。"
        elif wc < -1.5:return f"{sym}が弱い（週間{wc:.1f}%）。しばらく保持を推奨。"
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
# Analysis & Learning
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
        eff = "MU・AVGO・UPSTにとって追い風です。" if nq_pct > 0 else "MU・AVGO・UPSTへの下落圧力に注意。"
        exps.append(f"{em} NASDAQが{abs(nq_pct):.1f}%{d}しました。{eff}")
    if abs(sox_pct) > 0.3:
        d = "上昇" if sox_pct > 0 else "下落"
        em = "🔵" if sox_pct > 0 else "🔴"
        exps.append(f"{em} 半導体指数(SOX)が{abs(sox_pct):.1f}%{d}。MUとAVGOに直接影響します。")
    if abs(nk_pct) > 0.3:
        d = "上昇" if nk_pct > 0 else "下落"
        exps.append(f"🗾 日経225が{abs(nk_pct):.1f}%{d}。東京エレクトロンの動向に注目。")
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

    for ticker, d in stocks.items():
        pct = d.get("change_pct")
        if pct is None: continue
        if pct <= -10:
            actions.append(("HIGH",   f"🔴 {d['name']}({ticker})が{pct:.1f}%急落！予備資金¥10,000での買い増しを強く検討してください。"))
        elif pct <= -5:
            actions.append(("MEDIUM", f"🟡 {d['name']}({ticker})が{pct:.1f}%下落中。-10%になれば買い増しシグナルです。"))

    if vix_val > 30:
        actions.append(("HIGH", "🚨 VIXが30超え！市場は危険ゾーンです。予備資金は温存し、急いで買わないようにしましょう。"))

    wk = usd_jpy.get("week_change_pct") or 0
    rt = usd_jpy.get("rate") or 0
    if wk < -1.5 and rt > 0:
        actions.append(("MEDIUM", f"💱 円高チャンス！WISEでJPY→USD換金→SBIで米国株購入のタイミングです（現在: {rt:.2f}円）。"))
    elif wk > 2 and rt > 0:
        actions.append(("INFO", f"💱 円安継続（{rt:.2f}円）。米国株の購入は円高になるまで待つのも一つの選択肢です。"))

    best_c, best_wk = best_currency_to_hold(currencies)
    if best_c and best_wk and best_wk > 1.5:
        actions.append(("INFO", f"🏆 今週のWISEで最も強い通貨: {best_c}（対円 +{best_wk:.1f}%）。{best_c}保有者は含み益が出ています。"))

    today = datetime.now(pytz.timezone("Asia/Tokyo"))
    if today.day <= 5:
        actions.append(("INFO", "📅 月初！毎月の積立（¥50,000）を実行しましょう。MU: ¥30,000 / AVGO: ¥5,000 / 東京エレクトロン: ¥5,000 / 予備: ¥10,000"))

    if not actions:
        actions.append(("INFO", "✅ 今日は特別なアクションは不要です。定期ウォッチを継続しましょう。"))
    return actions


def get_daily_tip(indices, currencies, stocks):
    vix_val    = (indices.get("^VIX") or {}).get("value") or 0
    uj_wk      = (currencies.get("USD/JPY") or {}).get("week_change_pct") or 0
    sox_pct    = (indices.get("^SOX") or {}).get("change_pct") or 0
    any_drop10 = any((d.get("change_pct") or 0) <= -10 for d in stocks.values())

    if vix_val > 25:
        return {"title": "VIX恐怖指数が高い時の対処法",
                "content": "VIXが高い時は市場が「恐怖」を感じているサインです。でも歴史的に見ると、VIXが高い時こそ優良株が安く買えるチャンスでもあります。ウォーレン・バフェットの名言：「皆が恐れている時に買え」。ただし無謀な全力投資は禁物。予備資金を少しずつ使うのが賢明です。"}
    if any_drop10:
        return {"title": "株が急落した時の判断基準",
                "content": "保有株が-10%以上下落した時、パニックで売るのは最も損をする行動です。まず「なぜ下落したか」を確認しましょう。①業績悪化（ファンダメンタルの問題）→ 判断が必要。②市場全体の下落や一時的な恐怖→ 買い増しのチャンスかも。MUのような半導体株はサイクルが激しいので、長期目線で持つことが重要です。"}
    if abs(uj_wk) > 2:
        return {"title": "円安・円高と米国株投資の関係",
                "content": "円安（例：1ドル=160円）の時：既に持っている米国株の円換算価値は上がります。でも新たに買う時のコストも高くなります。円高（例：1ドル=140円）の時：米国株を安く買えるチャンス！WISEで円安→円高のタイミングを見てJPY→USDに換金しておくと有利です。"}
    if abs(sox_pct) > 2:
        return {"title": "SOX半導体指数とMU・AVGOの関係",
                "content": "SOX（フィラデルフィア半導体指数）はMicron、Broadcom、NVIDIAなど主要半導体メーカーの集合体です。SOXが動くとあなたのMU・AVGOも連動して動くことが多いです。SOXを毎日チェックすることで保有株の動きを事前に予測できます。"}

    today = datetime.now(pytz.timezone("Asia/Tokyo"))
    tips = [
        {"title": "分散投資の重要性", "content": "複数の業種・銘柄に投資することでリスクを分散できます。あなたのポートフォリオはIT・半導体・防衛など複数セクターに分散されていて、バランスが取れています。一つの銘柄が下落しても他が補う構造です。"},
        {"title": "ドルコスト平均法（積立投資）", "content": "毎月一定額（¥50,000）を投資する方法です。価格が高い時は少ない株数、安い時は多い株数を買えるため、平均購入コストを自然に下げる効果があります。市場タイミングを気にしすぎず、淡々と続けることが成功の鍵です。"},
        {"title": "アナリスト目標株価の使い方", "content": "プロのアナリストが予測する「12ヶ月後の目標価格」です。現在価格が目標より大幅に低ければ、まだ上昇余地があるサインかもしれません。ただし目標はあくまで予測なので、複数アナリストの平均値を参考にする程度にとどめましょう。"},
        {"title": "WISEを使った賢い投資戦略", "content": "通常、銀行でドルを買うと1〜3%の手数料がかかります。WISEを使えば中値レートに近い低コストで換金できます。戦略：円高の時にWISEでJPY→USDに換金してドルを保持→タイミングを見てSBIで米国株を購入。これだけで年間数千円のコスト削減になります。"},
        {"title": "半導体業界のスーパーサイクル", "content": "半導体はAIブームでデータセンター向け需要が急増中です。MicronはAI向けHBMメモリの主要供給者として注目されています。Broadcomはカスタムチップ（ASIC）でGoogleやMeta向けに供給しています。短期の株価変動より長期の業界成長トレンドを意識しましょう。"},
        {"title": "予備資金（現金）の重要性", "content": "¥10,000の予備資金を常に持っておく戦略は非常に賢明です。「暴落の時に買う」ためのお金です。投資家の格言：「チャンスの時にお金がない」が一番もったいない。普段は使わず、-10%急落のサインが出た時だけ使うのが正しい使い方です。"},
        {"title": "損益計算の正しい見方", "content": "短期の損益（今日±X%）に一喜一憂するのは禁物です。重要なのは「投資を始めてからの合計損益」です。毎月¥50,000を積立てながら数年間持ち続けることで、複利の効果が現れてきます。最初の1〜2年は小さく見えても、5年後・10年後に差が出ます。"},
    ]
    return tips[today.weekday() % len(tips)]

# ============================================================
# HTML Generation
# ============================================================

def generate_html(stocks, indices, currencies, news, actions, pnl, jpy_table):
    jst      = pytz.timezone("Asia/Tokyo")
    now      = datetime.now(jst)
    weekdays = ["月曜日","火曜日","水曜日","木曜日","金曜日","土曜日","日曜日"]
    date_str = now.strftime(f"%Y年%m月%d日（{weekdays[now.weekday()]}）%H:%M JST")

    mkt_exps    = market_explanations(indices, currencies)
    tip         = get_daily_tip(indices, currencies, stocks)
    best_c, bwk = best_currency_to_hold(currencies)

    def fmt_jpy(v):
        return f"¥{v:,}" if v >= 0 else f"-¥{abs(v):,}"

    # -------- Stocks --------
    stocks_html = ""
    for ticker, d in stocks.items():
        if d.get("price") is None:
            stocks_html += f'<div class="stock-card neutral-border"><span class="ticker">{ticker}</span> <span class="company">{d["name"]}</span> <span class="neutral">— データ取得中</span></div>'
            continue
        sym  = "¥" if d["is_jpy"] else "$"
        pct  = d["change_pct"]
        col  = _sign_color(pct)
        arr  = _arrow(pct)
        t_html = ""
        if d["target_price"] and d["target_dist"] is not None:
            tc = "positive" if d["target_dist"] > 0 else "negative"
            t_html = f'<div class="stock-meta">アナリスト目標: {sym}{d["target_price"]:,} <span class="{tc}">({d["target_dist"]:+.1f}%)</span></div>'
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
  <div class="stock-meta muted">投資額: ¥{d['invested_jpy']:,} | 毎月: ¥{d['monthly_jpy']:,}</div>
  {alert}
</div>"""

    # -------- P&L Section --------
    pnl_rows = ""
    for ticker, d in pnl.get("per_stock", {}).items():
        col = _sign_color(d["pnl_pct"])
        arr = _arrow(d["pnl_pct"])
        sym = "¥" if d["is_jpy"] else "$"
        pnl_rows += f"""
<div class="pnl-row">
  <div class="pnl-ticker"><span class="ticker">{ticker}</span><span class="company"> {d['name']}</span></div>
  <div class="pnl-detail">
    <span class="muted">購入: {sym}{d['buy_price']:,.2f}</span>
    <span class="muted">→</span>
    <span>現在: {sym}{d['cur_price']:,.2f}</span>
    <span class="{col} pnl-val">{arr} {fmt_jpy(d['pnl_jpy'])} ({d['pnl_pct']:+.2f}%)</span>
  </div>
</div>"""

    total_col = _sign_color(pnl.get("total_pnl_pct", 0))
    total_arr = _arrow(pnl.get("total_pnl_pct", 0))
    pnl_total_html = f"""
<div class="pnl-total {total_col}-border">
  <div class="pnl-total-row">
    <span>投資総額</span><span>¥{pnl.get('total_invested',0):,}</span>
  </div>
  <div class="pnl-total-row">
    <span>現在の評価額</span><span>¥{pnl.get('total_current',0):,}</span>
  </div>
  <div class="pnl-total-row big {total_col}">
    <span>損益合計</span>
    <span>{total_arr} {fmt_jpy(pnl.get('total_pnl',0))} ({pnl.get('total_pnl_pct',0):+.2f}%)</span>
  </div>
</div>"""

    # -------- Indices --------
    idx_html = ""
    for ticker, d in indices.items():
        if d.get("value") is None:
            idx_html += f'<div class="index-card neutral-border"><div class="index-name">{d["name"]}</div><div class="neutral">－</div></div>'
            continue
        pct = d["change_pct"]
        col = _sign_color(pct)
        arr = _arrow(pct)
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

    # -------- Currencies --------
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
        big_alert = f'<div class="fx-alert">⚠️ 本日大きく動いています（{dc:+.2f}%）！</div>' if abs(dc) > 2 else ""
        fx_html += f"""
<div class="fx-card">
  <div class="fx-pair">{key}</div>
  <div class="fx-rate">{rate_s}</div>
  <div class="fx-change {col}">{arr} 週間 {wk:+.2f}%　|　本日 {dc:+.2f}%</div>
  {hl_html}
  {big_alert}
  <div class="fx-advice">💡 {adv}</div>
</div>"""

    best_html = f'<div class="best-fx">🏆 今週WISEで最も強い通貨: <strong>{best_c}</strong>（対円 +{bwk:.1f}%）</div>' if (best_c and bwk and bwk > 1) else ""

    # -------- JPY Conversion Table --------
    jpy_conv_html = ""
    if jpy_table:
        rows = ""
        amounts = [10000, 30000, 50000, 100000]
        headers = "".join(f"<th>¥{a:,}</th>" for a in amounts)
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

    # -------- News --------
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

    # -------- Actions --------
    action_html = ""
    pri_cls = {"HIGH":"act-high","MEDIUM":"act-med","INFO":"act-info"}
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
}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Hiragino Sans','Yu Gothic UI',sans-serif;background:var(--bg);color:var(--txt);line-height:1.6;padding:12px;font-size:15px}}
a{{color:var(--blue)}}
.hdr{{text-align:center;padding:18px 0 14px;border-bottom:1px solid var(--border);margin-bottom:18px}}
.hdr h1{{font-size:1.6em;color:var(--blue)}}
.hdr .dt{{color:var(--muted);font-size:0.85em;margin-top:4px}}
.hdr .sub{{color:var(--dim);font-size:0.8em;margin-top:2px}}
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
.muted{{color:var(--muted)}}
.alert{{margin-top:8px;padding:7px 10px;border-radius:6px;font-size:0.88em}}
.buy-alert{{background:rgba(248,81,73,.12);color:var(--red);border:1px solid rgba(248,81,73,.3)}}
.watch-alert{{background:rgba(210,153,34,.12);color:var(--yellow);border:1px solid rgba(210,153,34,.3)}}
.positive{{color:var(--green)}}.negative{{color:var(--red)}}.neutral{{color:var(--muted)}}

/* P&L */
.pnl-row{{padding:9px 0;border-bottom:1px solid var(--border);display:flex;flex-direction:column;gap:4px}}
.pnl-row:last-child{{border-bottom:none}}
.pnl-ticker{{font-size:0.95em}}
.pnl-detail{{display:flex;flex-wrap:wrap;gap:10px;font-size:0.88em;align-items:center}}
.pnl-val{{font-weight:bold}}
.pnl-total{{border-radius:8px;padding:12px;border-left:4px solid var(--border);background:var(--bg3);margin-top:10px}}
.pnl-total-row{{display:flex;justify-content:space-between;padding:4px 0;font-size:0.9em;border-bottom:1px solid var(--border)}}
.pnl-total-row:last-child{{border-bottom:none}}
.pnl-total-row.big{{font-size:1.05em;font-weight:bold;padding-top:8px}}

/* Predictions */
.pred-row{{background:var(--bg3);border-radius:8px;padding:12px;margin-bottom:8px}}
.pred-name{{margin-bottom:8px;font-size:0.95em}}
.pred-src{{font-size:0.75em;color:var(--dim);margin-left:6px}}
.pred-cols{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}}
.pred-col{{background:var(--bg2);border-radius:6px;padding:8px;text-align:center}}
.pred-label{{font-size:0.72em;color:var(--muted);margin-bottom:3px}}
.pred-price{{font-size:1em;font-weight:bold}}
.pred-jpy{{font-size:0.78em;margin-top:2px}}
.pred-sub{{font-size:0.82em}}
.pred-total{{background:var(--bg3);border-radius:8px;padding:14px;margin-top:10px;border:1px solid rgba(88,166,255,.2)}}
.pred-total-title{{font-weight:bold;color:var(--blue);margin-bottom:10px}}
.pred-total-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}}
.pred-total-col{{background:var(--bg2);border-radius:6px;padding:10px;text-align:center}}
.pred-big{{font-size:1.1em;font-weight:bold;margin-top:4px}}
.pred-disclaimer{{font-size:0.75em;color:var(--dim);margin-top:10px;padding-top:8px;border-top:1px solid var(--border)}}

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

/* JPY Converter */
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

/* Actions */
.act-item{{padding:11px 13px;border-radius:8px;margin-bottom:7px;font-size:0.92em}}
.act-high{{background:rgba(248,81,73,.1);border:1px solid rgba(248,81,73,.3);color:var(--red)}}
.act-med{{background:rgba(210,153,34,.1);border:1px solid rgba(210,153,34,.3);color:var(--yellow)}}
.act-info{{background:rgba(88,166,255,.05);border:1px solid rgba(88,166,255,.2);color:var(--muted)}}

/* Tip */
.tip-box{{background:linear-gradient(135deg,var(--bg3),var(--bg2));border-radius:8px;padding:15px;border:1px solid rgba(88,166,255,.2)}}
.tip-ttl{{font-weight:bold;color:var(--blue);margin-bottom:7px}}
.tip-body{{font-size:0.88em;line-height:1.65;color:#c9d1d9}}

.footer{{text-align:center;padding:16px;color:var(--dim);font-size:0.75em;border-top:1px solid var(--border);margin-top:20px;line-height:1.8}}
@media(max-width:480px){{
  .idx-grid{{grid-template-columns:repeat(2,1fr)}}
  .fx-grid{{grid-template-columns:1fr}}
  .pred-cols{{grid-template-columns:1fr}}
  .pred-total-grid{{grid-template-columns:1fr}}
  .stock-price{{font-size:1em}}
}}
</style>
</head>
<body>

<div class="hdr">
  <h1>📊 毎朝の投資ダッシュボード</h1>
  <div class="dt">{date_str}</div>
  <div class="sub">投資総額: ¥110,000 | 毎月積立: ¥50,000 | 予備資金: ¥10,000</div>
</div>

<div class="sec">
  <div class="sec-ttl">📊 株価・保有銘柄</div>
  <div class="sec-body">{stocks_html}</div>
</div>

<div class="sec">
  <div class="sec-ttl">💰 損益・1年後・2年後の収益予測</div>
  <div class="sec-body">
    {pnl_rows}
    {pnl_total_html}
  </div>
</div>

<div class="sec">
  <div class="sec-ttl">🌏 市場概況</div>
  <div class="sec-body">
    <div class="idx-grid">{idx_html}</div>
    <div class="mkt-exps">{mkt_html}</div>
  </div>
</div>

<div class="sec">
  <div class="sec-ttl">💱 為替ダッシュボード（WISE対応）</div>
  <div class="sec-body">
    {best_html}
    <div class="fx-grid">{fx_html}</div>
    {jpy_conv_html}
  </div>
</div>

<div class="sec">
  <div class="sec-ttl">📰 今日の重要ニュース</div>
  <div class="sec-body">{news_html}</div>
</div>

<div class="sec">
  <div class="sec-ttl">⚡ 今日の推奨アクション</div>
  <div class="sec-body">{action_html}</div>
</div>

<div class="sec">
  <div class="sec-ttl">📚 今日の学習コーナー</div>
  <div class="sec-body">
    <div class="tip-box">
      <div class="tip-ttl">💡 {tip['title']}</div>
      <div class="tip-body">{tip['content']}</div>
    </div>
  </div>
</div>

<div class="footer">
  データソース: Yahoo Finance（株価・指数）/ Frankfurter API（為替）/ Yahoo Finance RSS + Google News（ニュース）<br>
  ※このダッシュボードは情報提供のみです。予測は参考値であり、将来の利益を保証するものではありません。投資判断は自己責任でお願いします。<br>
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

    print("  ⑧ ニュース取得中（記事本文を取得しています）...")
    news = get_news()

    print("  ⑨ アクション・アドバイス生成中...")
    actions = action_recommendations(stocks, indices, currencies)

    print("  ⑦ HTML生成中...")
    html = generate_html(stocks, indices, currencies, news, actions, pnl, jpy_table)

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"✅ 完了！ → {out}")
    print(f"   損益: {'+' if pnl['total_pnl'] >= 0 else ''}¥{pnl['total_pnl']:,} ({pnl['total_pnl_pct']:+.2f}%)")


if __name__ == "__main__":
    main()
