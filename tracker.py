import os
import json
from datetime import datetime
from zoneinfo import ZoneInfo
import yfinance as yf

# Liste des tickers à suivre
TICKERS = ["AED.BR", "CPINV.BE", "HOMI.BR", "ASML.AS", "KLAC"]

def fetch_data():
    prices_data = []
    news_data = []
    fundamentals_data = []

    for ticker_symbol in TICKERS:
        try:
            ticker = yf.Ticker(ticker_symbol)
            info = ticker.info

            # 1. Récupération des cours
            current_price = info.get("currentPrice") or info.get("regularMarketPrice", 0)
            previous_close = info.get("previousClose", current_price)
            
            change = current_price - previous_close if previous_close else 0
            change_percent = (change / previous_close * 100) if previous_close else 0

            prices_data.append({
                "symbol": ticker_symbol,
                "price": round(current_price, 2),
                "change": round(change, 2),
                "change_percent": round(change_percent, 2),
                "currency": info.get("currency", "EUR")
            })

            # 2. Récupération des ratios/fondamentaux
            fundamentals_data.append({
                "symbol": ticker_symbol,
                "pe_ratio": round(info.get("forwardPE", 0) or info.get("trailingPE", 0) or 0, 2),
                "dividend_yield": round((info.get("dividendYield", 0) or 0) * 100, 2),
                "market_cap": info.get("marketCap", 0)
            })

            # 3. Récupération des actualités récentes
            ticker_news = ticker.news
            if ticker_news:
                for item in ticker_news[:2]:  # Garde les 2 plus récentes par ticker
                    title = item.get("title")
                    link = item.get("link")
                    if title and link:
                        news_data.append({
                            "symbol": ticker_symbol,
                            "title": title,
                            "publisher": item.get("publisher", "Source inconnue"),
                            "link": link
                        })

        except Exception as e:
            print(f"Erreur lors de la récupération pour {ticker_symbol}: {e}")

    # Gestion du fuseau horaire belge (Europe/Brussels)
    belgium_tz = ZoneInfo("Europe/Brussels")
    now_be = datetime.now(belgium_tz)

    dashboard_data = {
        "updated_at": now_be.strftime("%d/%m/%Y à %H:%M"),
        "prices": prices_data,
        "news": news_data,
        "fundamentals": fundamentals_data
    }

    # Export en fichier JSON pour le frontend GitHub Pages
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(dashboard_data, f, ensure_ascii=False, indent=2)

    print(f"✅ data.json mis à jour avec succès à {now_be.strftime('%H:%M')} (Heure belge)")

if __name__ == "__main__":
    fetch_data()
