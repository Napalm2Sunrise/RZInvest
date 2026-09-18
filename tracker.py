from datetime import datetime
import json
import os
import requests
import yfinance as yf

TICKERS = [
    "AED.BR", "CPINV.BE", "HOMI.BR", "RET.BR", "AMKR", "ASML.AS",   
    "AVGO", "AYA.TO", "BKNG", "CPRT", "CSW", "GEV", "GOOG", "ISRG", 
    "META", "MC.PA", "MSFT", "NVDA", "ONON", "SPCX", "SPGI", "SU.PA", 
    "TTE.PA", "TSLA", "VRSN"
]

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

IMPORTANT_KEYWORDS = [
    "result", "earnings", "revenue", "profit", "margin", "guidance", "dividend",
    "fcf", "cash flow", "quarter", "q1", "q2", "q3", "q4", "bénéfice",
    "chiffre d'affaires", "résultat", "dividende", "buyout", "acquisition",
    "merger", "takeover", "sec", "investigation", "lawsuit", "ceo", "cfo",
    "layoff", "restructuring", "rachat", "procès", "démission", "licenciement"
]

def check_200_weekly_sma(ticker, current_price):
    try:
        hist = ticker.history(period="5y", interval="1wk")
        if len(hist) >= 200:
            sma_200 = hist["Close"].tail(200).mean()
            return "Under 🔥" if current_price < sma_200 else "Above"
    except Exception:
        pass
    return "N/A"

def get_next_earnings_date(ticker):
    try:
        calendar = ticker.calendar
        now = datetime.now().date()
        if isinstance(calendar, dict) and "Earnings Date" in calendar:
            for d in calendar["Earnings Date"]:
                d_date = d.date() if isinstance(d, datetime) else d
                if d_date >= now:
                    return d_date.strftime("%d/%m/%Y")
    except Exception:
        pass
    return "N/A"

def generate_dashboard_data():
    prices_data = []
    news_data = []
    fundamentals_data = []

    now_ts = datetime.now().timestamp()
    cutoff_ts = now_ts - (72 * 3600 if datetime.now().weekday() == 0 else 24 * 3600)

    for symbol in TICKERS:
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info or {}

            # 1. PRIX
            price = info.get("currentPrice") or info.get("regularMarketPrice") or 0.0
            prev_close = info.get("previousClose") or price
            change_pct = ((price - prev_close) / prev_close) * 100 if prev_close > 0 else 0.0
            currency = "€" if any(symbol.endswith(ext) for ext in [".BR", ".BE", ".PA"]) else "$"

            prices_data.append({
                "ticker": symbol,
                "price": round(price, 2),
                "change": round(change_pct, 2),
                "currency": currency,
                "sma200": check_200_weekly_sma(ticker, price),
                "earnings": get_next_earnings_date(ticker)
            })

            # 2. NEWS
            news_list = ticker.news or []
            for item in news_list:
                content = item.get("content", item)
                title = content.get("title") or item.get("title", "")
                summary = content.get("summary") or item.get("summary") or ""
                pub_time = content.get("pubDate") or item.get("providerPublishTime", 0)

                if isinstance(pub_time, str):
                    try: pub_time = datetime.fromisoformat(pub_time.replace("Z", "+00:00")).timestamp()
                    except: pub_time = now_ts

                if pub_time >= cutoff_ts:
                    link = content.get("clickThroughUrl", {}).get("url") or item.get("link")
                    news_data.append({
                        "ticker": symbol,
                        "title": title,
                        "summary": summary[:200] + "..." if len(summary) > 200 else summary,
                        "link": link,
                        "date": datetime.fromtimestamp(pub_time).strftime("%H:%M")
                    })

            # 3. RATIOS
            fundamentals_data.append({
                "ticker": symbol,
                "rev_growth": f"{(info.get('revenueGrowth') or 0)*100:+.1f}%",
                "pe": f"{info.get('forwardPE', 0):.1f}x",
                "ev": f"{info.get('enterpriseToEbitda', 0):.1f}x",
                "roe": f"{(info.get('returnOnEquity') or 0)*100:.1f}%"
            })

        except Exception as e:
            print(f"Erreur sur {symbol}: {e}")

    # Enregistrement dans le fichier JSON pour la Mini App
    output = {
        "updated_at": datetime.now().strftime("%d/%m/%Y à %H:%M"),
        "prices": prices_data,
        "news": news_data,
        "fundamentals": fundamentals_data
    }

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("data.json généré avec succès !")

if __name__ == "__main__":
    generate_dashboard_data()
