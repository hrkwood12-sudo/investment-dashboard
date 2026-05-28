#!/usr/bin/env python3
"""
毎朝の投資ダッシュボード生成スクリプト
Daily Investment Dashboard Generator
Uses: yfinance (stocks), frankfurter.app (currencies), Google News RSS (news)
"""

import yfinance as yf
import requests
from datetime import datetime, timedelta
import pytz
import feedparser
import os
import time

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

NEWS_QUERIES = [
    ("Micron Technology MU semiconductor",     "MU・半導体"),
    ("Broadcom AVGO AI networking",            "AVGO・AI"),
    ("Tokyo Electron 東京エレクトロン",         "東京エレクトロン"),
    ("Upstart UPST AI lending",                "UPST"),
    ("Kratos Defense KTOS drone",              "KTOS・防衛"),
    ("Federal Reserve interest rate inflation","FRB・金利"),
    ("Bank of Japan yen dollar BOJ",           "日銀・円相場"),
    ("Malaysia economy ringgit MYR",           "マレーシア・MYR"),
    ("AI semiconductor chip industry",         "AI・半導体業界"),
    ("NASDAQ stock market tech",               "NASDAQ市場"),
]

# ============================================================
# Data Fetching
# ============================================================

def get_stock_data():
    stocks = {}
    for ticker, meta in PORTFOLIO.items():
        try:
            t = yf.Ticker(ticker)
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

            target = info.get("targetMeanPrice")
            target_dist = ((float(target) - current) / current * 100) if target else None

            stocks[ticker] = {
                "name":          meta["name"],
                "price":         round(current, 2),
                "change":        round(change, 2),
                "change_pct":    round(change_pct, 2),
                "target_price":  round(float(target), 2) if target else None,
                "target_dist":   round(target_dist, 1) if target_dist is not None else None,
                "invested_jpy":  meta["invested_jpy"],
                "monthly_jpy":   meta["monthly_jpy"],
                "is_jpy":        ".T" in ticker,
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
            t = yf.Ticker(ticker)
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
            indices[ticker] = {
                "name":       name,
                "value":      None,
                "change":     None,
                "change_pct": None,
                "error":      str(e),
            }
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
    jst      = pytz.timezone("Asia/Tokyo")
    now      = datetime.now(jst)
    today    = now.strftime("%Y-%m-%d")
    yday     = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    mon_start = (now - timedelta(days=30)).strftime("%Y-%m-%d")

    all_bases = set()
    for f, t in CURRENCY_PAIRS:
        all_bases.add(f)

    # Fetch latest + yesterday + time series for each base
    latest   = {}
    previous = {}
    series   = {}

    for base in all_bases:
        d = _frankfurter_get(f"https://api.frankfurter.app/latest?from={base}")
        if d:
            latest[base] = d.get("rates", {})
            latest[base][base] = 1.0

        d = _frankfurter_get(f"https://api.frankfurter.app/{yday}?from={base}")
        if d:
            previous[base] = d.get("rates", {})
            previous[base][base] = 1.0

        # Time series for 1-month high/low
        d = _frankfurter_get(f"https://api.frankfurter.app/{mon_start}..{today}?from={base}")
        if d:
            series[base] = d.get("rates", {})  # {date: {currency: rate}}

    currencies = {}
    for frm, to in CURRENCY_PAIRS:
        key = f"{frm}/{to}"
        rate      = latest.get(frm, {}).get(to)
        prev_rate = previous.get(frm, {}).get(to)

        day_change_pct  = round((rate - prev_rate) / prev_rate * 100, 3) if (rate and prev_rate and prev_rate != 0) else None

        # Week change: find rate from 7 days ago in series
        week_rate = None
        if frm in series:
            # Find closest date to week_ago
            dates = sorted(series[frm].keys())
            for d in dates:
                if d >= week_ago:
                    week_rate = series[frm][d].get(to)
                    break
        week_change_pct = round((rate - week_rate) / week_rate * 100, 2) if (rate and week_rate and week_rate != 0) else None

        # 1-month high/low
        month_high = None
        month_low  = None
        if frm in series:
            vals = [v.get(to) for v in series[frm].values() if v.get(to)]
            if vals:
                month_high = round(max(vals), 4)
                month_low  = round(min(vals), 4)

        currencies[key] = {
            "from":            frm,
            "to":              to,
            "rate":            round(rate, 4) if rate else None,
            "day_change_pct":  day_change_pct,
            "week_change_pct": week_change_pct,
            "month_high":      month_high,
            "month_low":       month_low,
        }

    return currencies


def get_news():
    items    = []
    seen     = set()
    base_url = "https://news.google.com/rss/search?q={}&hl=en&gl=US&ceid=US:en"

    for query, category in NEWS_QUERIES:
        try:
            encoded = requests.utils.quote(query)
            feed    = feedparser.parse(base_url.format(encoded))
            for entry in feed.entries[:2]:
                title = entry.get("title", "").strip()
                if not title or title in seen:
                    continue
                seen.add(title)
                items.append({
                    "title":    title,
                    "link":     entry.get("link", "#"),
                    "category": category,
                    "source":   entry.get("source", {}).get("title", "Google News"),
                })
        except Exception:
            pass

    return items[:20]

# ============================================================
# Analysis & Advice
# ============================================================

def _sign_color(val):
    if val is None: return "neutral"
    return "positive" if val > 0 else ("negative" if val < 0 else "neutral")

def _arrow(val):
    if val is None: return "－"
    return "▲" if val > 0 else ("▼" if val < 0 else "－")


def currency_advice(pair, rate, day_change, week_change):
    """Generate WISE advice in Japanese for a currency pair."""
    if rate is None:
        return "データ取得中…"

    wc = week_change or 0
    dc = day_change  or 0

    if pair == "USD/JPY":
        if wc > 2:
            return f"円安トレンド継続（{rate:.2f}円）。今ドルを買うのはやや不利。円高を待つのがおすすめ。"
        elif wc < -2:
            return f"円高進行中（{rate:.2f}円）。今がWISEでJPY→USD換金の好タイミング！"
        elif abs(dc) > 0.5:
            direction = "円安" if dc > 0 else "円高"
            return f"本日{direction}（{rate:.2f}円）。大きなトレンドには至っていません。"
        return f"USD/JPY: {rate:.2f}円。比較的安定中。急ぎでなければ様子見推奨。"

    elif pair == "MYR/JPY":
        if wc > 1.5:
            return f"リンギット強い（{rate:.4f}円）。WISEでMYR→JPY換金のチャンスです。"
        elif wc < -1.5:
            return f"リンギット弱い（{rate:.4f}円）。今はMYR保持のまま回復を待ちましょう。"
        return f"MYR/JPY: {rate:.4f}円。安定中。"

    elif pair == "USD/MYR":
        return f"USD/MYR: {rate:.4f}。ドルとリンギットの交換レートです。"

    else:
        sym = pair.split("/")[0]
        if wc > 1.5:
            return f"{sym}が強い（週間+{wc:.1f}%）。JPYへの換金なら今がチャンスかも。"
        elif wc < -1.5:
            return f"{sym}が弱い（週間{wc:.1f}%）。しばらく保持を推奨。"
        return f"比較的安定（週間{wc:+.1f}%）。"


def best_currency_to_hold(currencies):
    """Find the currency with the strongest weekly trend vs JPY."""
    results = []
    for key, data in currencies.items():
        if data["to"] != "JPY" or data["week_change_pct"] is None:
            continue
        results.append((data["from"], data["week_change_pct"]))
    if not results:
        return None, None
    results.sort(key=lambda x: x[1], reverse=True)
    return results[0]


def market_explanations(indices, currencies):
    exps = []
    nasdaq  = indices.get("^IXIC", {})
    sox     = indices.get("^SOX", {})
    vix     = indices.get("^VIX", {})
    nikkei  = indices.get("^N225", {})
    usd_jpy = currencies.get("USD/JPY", {})

    nq_pct  = nasdaq.get("change_pct") or 0
    sox_pct = sox.get("change_pct") or 0
    vix_val = vix.get("value") or 0
    nk_pct  = nikkei.get("change_pct") or 0
    uj_wk   = usd_jpy.get("week_change_pct") or 0
    uj_rate = usd_jpy.get("rate") or 0

    # NASDAQ
    if abs(nq_pct) > 0.3:
        d   = "上昇" if nq_pct > 0 else "下落"
        em  = "📈" if nq_pct > 0 else "📉"
        eff = "MU・AVGO・UPSTにとって追い風です。" if nq_pct > 0 else "MU・AVGO・UPSTへの下落圧力に注意。"
        exps.append(f"{em} NASDAQが{abs(nq_pct):.1f}%{d}しました。{eff}")

    # SOX
    if abs(sox_pct) > 0.3:
        d  = "上昇" if sox_pct > 0 else "下落"
        em = "🔵" if sox_pct > 0 else "🔴"
        exps.append(f"{em} 半導体指数(SOX)が{abs(sox_pct):.1f}%{d}。MUとAVGOに直接影響します。")

    # Nikkei
    if abs(nk_pct) > 0.3:
        d  = "上昇" if nk_pct > 0 else "下落"
        em = "🗾" if nk_pct > 0 else "🗾"
        exps.append(f"{em} 日経225が{abs(nk_pct):.1f}%{d}。東京エレクトロンの動向に注目。")

    # VIX
    if vix_val > 30:
        exps.append(f"🚨 VIX恐怖指数が{vix_val:.1f}！市場は危険ゾーン。新規購入は慎重に。予備資金は温存してください。")
    elif vix_val > 20:
        exps.append(f"⚠️ VIX恐怖指数が{vix_val:.1f}。市場不安定。様子見を推奨します。")
    elif 0 < vix_val <= 20:
        exps.append(f"✅ VIX恐怖指数は{vix_val:.1f}と落ち着いています。市場は比較的安定中です。")

    # USD/JPY
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
    usd_jpy = (currencies.get("USD/JPY") or {})

    # Stock drop alerts
    for ticker, d in stocks.items():
        pct = d.get("change_pct")
        if pct is None:
            continue
        if pct <= -10:
            actions.append(("HIGH", f"🔴 {d['name']}({ticker})が{pct:.1f}%急落！予備資金¥10,000での買い増しを強く検討してください。"))
        elif pct <= -5:
            actions.append(("MEDIUM", f"🟡 {d['name']}({ticker})が{pct:.1f}%下落中。-10%になれば買い増しシグナルです。注目継続。"))

    # VIX danger
    if vix_val > 30:
        actions.append(("HIGH", "🚨 VIXが30超え！市場は危険ゾーンです。予備資金は温存し、急いで買わないようにしましょう。"))

    # Currency opportunity
    wk = usd_jpy.get("week_change_pct") or 0
    rt = usd_jpy.get("rate") or 0
    if wk < -1.5 and rt > 0:
        actions.append(("MEDIUM", f"💱 円高チャンス！WISEでJPY→USD換金→SBIで米国株購入のタイミングです（現在: {rt:.2f}円）。"))
    elif wk > 2 and rt > 0:
        actions.append(("INFO", f"💱 円安継続（{rt:.2f}円）。米国株の購入は円高になるまで待つのも一つの選択肢です。"))

    # Best currency to hold
    best_curr, best_wk = best_currency_to_hold(currencies)
    if best_curr and best_wk and best_wk > 1.5:
        actions.append(("INFO", f"🏆 今週のWISEで強い通貨: {best_curr}（対円 +{best_wk:.1f}%）。{best_curr}保有者は含み益が出ています。"))

    # Monthly investment reminder
    today = datetime.now(pytz.timezone("Asia/Tokyo"))
    if today.day <= 5:
        actions.append(("INFO", "📅 月初！毎月の積立（¥50,000）を実行しましょう。MU: ¥30,000 / AVGO: ¥5,000 / 東京エレクトロン: ¥5,000 / 予備: ¥10,000"))

    if not actions:
        actions.append(("INFO", "✅ 今日は特別なアクションは不要です。定期ウォッチを継続しましょう。"))

    return actions


def get_daily_tip(indices, currencies, stocks):
    """Return a contextually relevant learning tip in Japanese."""
    vix_val    = (indices.get("^VIX") or {}).get("value") or 0
    uj_wk      = (currencies.get("USD/JPY") or {}).get("week_change_pct") or 0
    sox_pct    = (indices.get("^SOX") or {}).get("change_pct") or 0
    any_drop10 = any((d.get("change_pct") or 0) <= -10 for d in stocks.values())

    # Context-aware tip selection
    if vix_val > 25:
        return {
            "title": "VIX恐怖指数が高い時の対処法",
            "content": (
                "VIXが高い時は市場が「恐怖」を感じているサインです。でも歴史的に見ると、"
                "VIXが高い時こそ株が安く買えるチャンスでもあります。ウォーレン・バフェットの名言："
                "「皆が欲張っている時に恐れ、皆が恐れている時に欲張れ」。"
                "ただし、無謀な全力投資は禁物。予備資金を少しずつ使うのが賢明です。"
            )
        }
    if any_drop10:
        return {
            "title": "株が急落した時の判断基準",
            "content": (
                "保有株が-10%以上下落した時、パニックで売るのは最も損をする行動です。"
                "まず「なぜ下落したか」を確認しましょう。"
                "①業績悪化（ファンダメンタルの問題）→ 判断が必要 "
                "②市場全体の下落や一時的な恐怖→ 買い増しのチャンスかも。"
                "MUのような半導体株はサイクルが激しいので、長期目線で持つことが重要です。"
            )
        }
    if abs(uj_wk) > 2:
        return {
            "title": "円安・円高と米国株投資の関係",
            "content": (
                "円安（例：1ドル=160円）の時：既に持っている米国株の円換算価値は上がります。"
                "でも新たに買う時のコストも高くなります。"
                "円高（例：1ドル=140円）の時：米国株を安く買えるチャンス！"
                "WISEで円安→円高のタイミングを見てJPY→USDに換金しておくと有利です。"
            )
        }
    if abs(sox_pct) > 2:
        return {
            "title": "SOX半導体指数とMU・AVGOの関係",
            "content": (
                "SOX（フィラデルフィア半導体指数）はMicron、Broadcom、NVIDIAなど"
                "主要半導体銘柄を集めた指数です。"
                "SOXが動くとあなたのMU・AVGOも連動して動くことが多いです。"
                "SOXを毎日チェックすることで、保有株の動きを事前に予測できます。"
            )
        }

    # Rotating generic tips by day of week
    today = datetime.now(pytz.timezone("Asia/Tokyo"))
    tips = [
        {
            "title": "分散投資の重要性",
            "content": "複数の業種・銘柄に投資することでリスクを分散できます。あなたのポートフォリオはIT・半導体・防衛など複数セクターに分散されていて、バランスが取れています。一つの銘柄が下落しても他が補う構造です。"
        },
        {
            "title": "ドルコスト平均法（積立投資）",
            "content": "毎月一定額（¥50,000）を投資する方法です。価格が高い時は少ない株数、安い時は多い株数を買えるため、平均購入コストを自然に下げる効果があります。市場タイミングを気にしすぎず、淡々と続けることが成功の鍵です。"
        },
        {
            "title": "アナリスト目標株価の使い方",
            "content": "プロのアナリストが予測する「12ヶ月後の目標価格」です。現在価格が目標より大幅に低ければ、まだ上昇余地があるサインかもしれません。ただし目標はあくまで予測なので、参考程度にとどめましょう。複数アナリストの平均値を見るのがコツです。"
        },
        {
            "title": "WISEを使った賢い投資戦略",
            "content": "通常、銀行でドルを買うと1〜3%の手数料がかかります。WISEを使えば中値レートに近い低コストで換金できます。戦略：円高の時にWISEでJPY→USDに換金してドルを保持→タイミングを見てSBIで米国株を購入。これだけで年間数千円のコスト削減になります。"
        },
        {
            "title": "半導体業界のサイクルを理解しよう",
            "content": "半導体（MU・AVGOなど）は「スーパーサイクル」という需要の波があります。AIブームでデータセンター向け需要が急増中。MicronはAI向けHBMメモリの主要供給者として注目されています。短期の株価変動より、長期の業界成長トレンドを意識しましょう。"
        },
        {
            "title": "予備資金（現金）の重要性",
            "content": "¥10,000の予備資金を常に持っておく戦略は非常に賢明です。「暴落の時に買う」ためのお金です。投資家の格言：「チャンスの時にお金がない」が一番もったいない。普段は使わず、-10%急落のサインが出た時だけ使うのが正しい使い方です。"
        },
        {
            "title": "防衛・宇宙セクターへの投資（KTOS）",
            "content": "Kratos Defense（KTOS）は無人機・ドローン・宇宙システム専門の防衛企業です。地政学リスクの高まりで防衛予算は増加トレンド。AIと防衛の融合も注目ポイントです。半導体・IT株とは値動きが異なるため、ポートフォリオの分散効果があります。"
        },
    ]
    return tips[today.weekday() % len(tips)]

# ============================================================
# HTML Generation
# ============================================================

def generate_html(stocks, indices, currencies, news, actions):
    jst      = pytz.timezone("Asia/Tokyo")
    now      = datetime.now(jst)
    weekdays = ["月曜日", "火曜日", "水曜日", "木曜日", "金曜日", "土曜日", "日曜日"]
    date_str = now.strftime(f"%Y年%m月%d日（{weekdays[now.weekday()]}）%H:%M JST")

    mkt_exps    = market_explanations(indices, currencies)
    tip         = get_daily_tip(indices, currencies, stocks)
    best_c, bwk = best_currency_to_hold(currencies)

    # -------- Stocks --------
    stocks_html = ""
    for ticker, d in stocks.items():
        if d.get("price") is None:
            err = d.get("error", "データ取得エラー")
            stocks_html += f'<div class="stock-card neutral-border"><span class="ticker">{ticker}</span> <span class="company">{d["name"]}</span> <span class="neutral" style="font-size:0.85em">— {err[:60]}</span></div>'
            continue

        sym        = "¥" if d["is_jpy"] else "$"
        pct        = d["change_pct"]
        col        = _sign_color(pct)
        arr        = _arrow(pct)
        target_html = ""
        if d["target_price"] and d["target_dist"] is not None:
            tc = "positive" if d["target_dist"] > 0 else "negative"
            target_html = f'<div class="stock-meta">アナリスト目標: {sym}{d["target_price"]:,} <span class="{tc}">({d["target_dist"]:+.1f}%)</span></div>'
        alert = ""
        if pct <= -10:
            alert = '<div class="alert buy-alert">🔴 -10%以上の急落！予備資金での買い増しシグナル！</div>'
        elif pct <= -5:
            alert = '<div class="alert watch-alert">🟡 -5%以上の下落。-10%で買い増し検討。</div>'

        stocks_html += f"""
<div class="stock-card {col}-border">
  <div class="stock-header">
    <div><span class="ticker">{ticker}</span><span class="company"> {d['name']}</span></div>
    <div class="stock-price {col}">{sym}{d['price']:,.2f} <span class="change">{arr}{abs(d['change']):.2f}（{pct:+.2f}%）</span></div>
  </div>
  {target_html}
  <div class="stock-meta muted">投資額: ¥{d['invested_jpy']:,} | 毎月: ¥{d['monthly_jpy']:,}</div>
  {alert}
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

    # -------- Market explanation --------
    mkt_html = "".join(f'<div class="mkt-exp">{e}</div>' for e in mkt_exps)

    # -------- Currencies --------
    fx_html = ""
    for key, d in currencies.items():
        if d.get("rate") is None:
            fx_html += f'<div class="fx-card"><div class="fx-pair">{key}</div><div class="neutral">－</div></div>'
            continue
        rate = d["rate"]
        wk   = d.get("week_change_pct") or 0
        dc   = d.get("day_change_pct")  or 0
        col  = _sign_color(wk)
        arr  = _arrow(wk)
        adv  = currency_advice(key, rate, dc, wk)
        rate_str = f"{rate:,.2f}" if rate >= 10 else f"{rate:,.4f}"
        hl_html = ""
        if d.get("month_high") and d.get("month_low"):
            mh = d["month_high"]
            ml = d["month_low"]
            mh_s = f"{mh:,.2f}" if mh >= 10 else f"{mh:,.4f}"
            ml_s = f"{ml:,.2f}" if ml >= 10 else f"{ml:,.4f}"
            hl_html = f'<div class="fx-hl">1ヶ月: 高値{mh_s} / 安値{ml_s}</div>'
        big_alert = f'<div class="fx-alert">⚠️ 本日大きく動いています（{dc:+.2f}%）！</div>' if abs(dc) > 2 else ""
        fx_html += f"""
<div class="fx-card">
  <div class="fx-pair">{key}</div>
  <div class="fx-rate">{rate_str}</div>
  <div class="fx-change {col}">{arr} 週間 {wk:+.2f}%　|　本日 {dc:+.2f}%</div>
  {hl_html}
  {big_alert}
  <div class="fx-advice">💡 {adv}</div>
</div>"""

    # Best currency highlight
    best_html = ""
    if best_c and bwk and bwk > 1:
        best_html = f'<div class="best-fx">🏆 今週WISEで最も強い通貨: <strong>{best_c}</strong>（対円 +{bwk:.1f}%）</div>'

    # -------- News --------
    news_html = ""
    for item in news:
        news_html += f"""
<div class="news-item">
  <span class="news-cat">{item['category']}</span>
  <a href="{item['link']}" target="_blank" class="news-title">{item['title']}</a>
  <span class="news-src">{item['source']}</span>
</div>"""
    if not news_html:
        news_html = '<div class="muted" style="padding:10px">ニュースを取得できませんでした。</div>'

    # -------- Actions --------
    action_html = ""
    priority_cls = {"HIGH": "act-high", "MEDIUM": "act-med", "INFO": "act-info"}
    for pri, msg in actions:
        action_html += f'<div class="act-item {priority_cls.get(pri, "act-info")}">{msg}</div>'

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

.stock-card{{background:var(--bg3);border-radius:8px;padding:12px;margin-bottom:8px;border-left:4px solid var(--border)}}
.positive-border{{border-left-color:var(--green)}}
.negative-border{{border-left-color:var(--red)}}
.neutral-border{{border-left-color:var(--border)}}
.stock-header{{display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:6px}}
.ticker{{font-weight:bold;font-size:1.05em;color:var(--blue)}}
.company{{color:var(--muted);font-size:0.85em}}
.stock-price{{font-size:1.1em;font-weight:bold}}
.change{{font-size:0.82em;margin-left:6px}}
.stock-meta{{font-size:0.8em;color:var(--muted);margin-top:4px}}
.muted{{color:var(--muted)}}
.alert{{margin-top:8px;padding:7px 10px;border-radius:6px;font-size:0.88em}}
.buy-alert{{background:rgba(248,81,73,.12);color:var(--red);border:1px solid rgba(248,81,73,.3)}}
.watch-alert{{background:rgba(210,153,34,.12);color:var(--yellow);border:1px solid rgba(210,153,34,.3)}}

.positive{{color:var(--green)}}
.negative{{color:var(--red)}}
.neutral{{color:var(--muted)}}

.idx-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(145px,1fr));gap:8px}}
.index-card{{background:var(--bg3);border-radius:8px;padding:11px;text-align:center;border-left:3px solid var(--border)}}
.index-name{{font-size:0.78em;color:var(--muted);margin-bottom:3px}}
.index-value{{font-size:1.15em;font-weight:bold}}
.index-change{{font-size:0.82em}}
.vix-danger{{background:rgba(248,81,73,.08)}}
.vix-warn{{background:rgba(210,153,34,.08)}}
.vix-calm{{background:rgba(63,185,80,.05)}}

.mkt-exp{{padding:9px 12px;margin-bottom:7px;background:var(--bg3);border-radius:6px;border-left:3px solid var(--blue);font-size:0.9em}}
.mkt-exps{{margin-top:12px}}

.fx-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:8px}}
.fx-card{{background:var(--bg3);border-radius:8px;padding:12px}}
.fx-pair{{font-weight:bold;color:var(--blue);font-size:0.95em}}
.fx-rate{{font-size:1.25em;font-weight:bold;margin:3px 0}}
.fx-change{{font-size:0.82em}}
.fx-hl{{font-size:0.78em;color:var(--dim);margin-top:3px}}
.fx-alert{{margin-top:5px;padding:4px 8px;background:rgba(210,153,34,.15);color:var(--yellow);border-radius:4px;font-size:0.8em}}
.fx-advice{{margin-top:7px;font-size:0.82em;color:var(--muted);line-height:1.45}}
.best-fx{{padding:10px 12px;margin-bottom:10px;background:rgba(88,166,255,.08);border:1px solid rgba(88,166,255,.2);border-radius:8px;font-size:0.9em}}

.news-item{{padding:9px 0;border-bottom:1px solid var(--border);display:flex;flex-direction:column;gap:3px}}
.news-item:last-child{{border-bottom:none}}
.news-cat{{font-size:0.72em;background:rgba(88,166,255,.15);color:var(--blue);padding:2px 8px;border-radius:10px;width:fit-content}}
.news-title{{color:var(--txt);text-decoration:none;font-size:0.88em;line-height:1.4}}
.news-title:hover{{color:var(--blue);text-decoration:underline}}
.news-src{{font-size:0.72em;color:var(--dim)}}

.act-item{{padding:11px 13px;border-radius:8px;margin-bottom:7px;font-size:0.92em}}
.act-high{{background:rgba(248,81,73,.1);border:1px solid rgba(248,81,73,.3);color:var(--red)}}
.act-med{{background:rgba(210,153,34,.1);border:1px solid rgba(210,153,34,.3);color:var(--yellow)}}
.act-info{{background:rgba(88,166,255,.05);border:1px solid rgba(88,166,255,.2);color:var(--muted)}}

.tip-box{{background:linear-gradient(135deg,var(--bg3),var(--bg2));border-radius:8px;padding:15px;border:1px solid rgba(88,166,255,.2)}}
.tip-ttl{{font-weight:bold;color:var(--blue);margin-bottom:7px}}
.tip-body{{font-size:0.88em;line-height:1.65;color:#c9d1d9}}

.footer{{text-align:center;padding:16px;color:var(--dim);font-size:0.75em;border-top:1px solid var(--border);margin-top:20px;line-height:1.8}}

@media(max-width:480px){{
  .idx-grid{{grid-template-columns:repeat(2,1fr)}}
  .fx-grid{{grid-template-columns:1fr}}
  .stock-price{{font-size:1em}}
}}
</style>
</head>
<body>

<div class="hdr">
  <h1>📊 毎朝の投資ダッシュボード</h1>
  <div class="dt">{date_str}</div>
  <div class="sub">ポートフォリオ投資額: ¥110,000 | 毎月積立: ¥50,000 | 予備資金: ¥10,000</div>
</div>

<div class="sec">
  <div class="sec-ttl">📊 株価・保有銘柄</div>
  <div class="sec-body">{stocks_html}</div>
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
  データソース: Yahoo Finance（株価・指数）/ Frankfurter API（為替）/ Google News（ニュース）<br>
  ※このダッシュボードは情報提供のみです。投資判断は自己責任でお願いします。<br>
  最終更新: {date_str}
</div>

<script>
// Auto-refresh every 10 minutes
setTimeout(() => location.reload(), 10 * 60 * 1000);
</script>
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

    print("  ④ ニュース取得中...")
    news = get_news()

    print("  ⑤ アクション・アドバイス生成中...")
    actions = action_recommendations(stocks, indices, currencies)

    print("  ⑥ HTML生成中...")
    html = generate_html(stocks, indices, currencies, news, actions)

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"✅ 完了！ → {out}")


if __name__ == "__main__":
    main()
