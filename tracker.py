from datetime import datetime
import json
import math
import os
import time
import urllib.request
from zoneinfo import ZoneInfo
import yfinance as yf

# ==============================================================================
# CONFIGURATION
# ==============================================================================
TICKERS = [
    "AED.BR", "CPINV.BE", "HOMI.BR", "RET.BR", "AMKR", "ASML.AS",   
    "AVGO", "AYA.TO", "BKNG", "CPRT", "CSW", "GEV", "GOOG", "ISRG", 
    "META", "MC.PA", "MSFT", "NVDA", "ONON", "SPCX", "SPGI", "SU.PA", 
    "TTE.PA", "TSLA", "VRSN"
]

FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "")

def clean_val(val, fmt="{:.1f}%"):
    """Nettoie les valeurs NaN, None ou Inf."""
    if val is None:
        return "N/A"
    try:
        f_val = float(val)
        if math.isnan(f_val) or math.isinf(f_val):
            return "N/A"
        return fmt.format(f_val)
    except Exception:
        return "N/A"

def check_200_weekly_sma(ticker, current_price):
    """Calcul exact de la 200 Weekly SMA."""
    try:
        hist_daily = ticker.history(period="max", interval="1d", auto_adjust=False, back_adjust=False)
        if not hist_daily.empty and len(hist_daily) >= 1000:
            hist_weekly = hist_daily['Close'].resample('W-FRI').last().dropna()
            if len(hist_weekly) >= 200:
                sma_series = hist_weekly.rolling(window=200).mean()
                sma_200 = sma_series.iloc[-1]
                if sma_200 > 0 and current_price > 0:
                    raw_pct = ((current_price - sma_200) / sma_200) * 100
                    pct = round(raw_pct, 1)
                    if current_price < sma_200:
                        return f"Under {pct}% 🔥", pct
                    else:
                        return f"Above +{pct}%", pct
    except Exception as e:
        print(f"Erreur calcul SMA200: {e}")
    return "N/A", None

def get_next_earnings_date(ticker, belgium_tz):
    try:
        calendar = ticker.calendar
        now = datetime.now(belgium_tz).date()
        if isinstance(calendar, dict) and "Earnings Date" in calendar:
            for d in calendar["Earnings Date"]:
                d_date = d.date() if isinstance(d, datetime) else d
                if d_date >= now:
                    return d_date.strftime("%d/%m/%Y")
    except Exception:
        pass
    return "N/A"

def get_quarterly_history(symbol, ticker, info):
    """
    Récupère l'historique trimestriel fiable via Yahoo Finance avec comparaison YoY exacte.
    """
    quarters = []
    history = {
        "Croit. CA.": [],
        "Marge Net %": [],
        "Fwd P/E": [],
        "EV/EBITDA": [],
        "ROE": [],
        "PEG": []
    }

    try:
        q_fin = ticker.quarterly_financials
        q_bs = ticker.quarterly_balance_sheet
        
        if q_fin is not None and not q_fin.empty:
            cols = list(q_fin.columns)
            
            # Map des trimestres pour un calcul YoY exact
            data_by_period = {}
            for col in cols:
                dt = col.to_pydatetime() if hasattr(col, "to_pydatetime") else col
                q_num = (dt.month - 1) // 3 + 1
                key = (dt.year, q_num)
                
                rev = float(q_fin.loc['Total Revenue', col]) if 'Total Revenue' in q_fin.index and not math.isnan(q_fin.loc['Total Revenue', col]) else None
                net_inc = float(q_fin.loc['Net Income', col]) if 'Net Income' in q_fin.index and not math.isnan(q_fin.loc['Net Income', col]) else None
                
                equity = None
                if q_bs is not None and not q_bs.empty and col in q_bs.columns:
                    if 'Stockholders Equity' in q_bs.index and not math.isnan(q_bs.loc['Stockholders Equity', col]):
                        equity = float(q_bs.loc['Stockholders Equity', col])

                data_by_period[key] = {
                    "label": f"Q{q_num}-{dt.year}",
                    "revenue": rev,
                    "net_income": net_inc,
                    "equity": equity
                }

            sorted_keys = sorted(data_by_period.keys(), reverse=True)[:10]

            for (yr, q_num) in sorted_keys:
                item = data_by_period[(yr, q_num)]
                quarters.append(item["label"])

                # --- 1. CROISSANCE CA (Comparaison exacte avec l'année N-1) ---
                prev_year_key = (yr - 1, q_num)
                if prev_year_key in data_by_period and data_by_period[prev_year_key]["revenue"]:
                    rev_curr = item["revenue"]
                    rev_prev = data_by_period[prev_year_key]["revenue"]
                    if rev_curr and rev_prev and rev_prev > 0:
                        growth = ((rev_curr - rev_prev) / rev_prev) * 100
                        history["Croit. CA."].append(clean_val(growth, "{:+.1f}%"))
                    else:
                        history["Croit. CA."].append("N/A")
                else:
                    history["Croit. CA."].append("N/A")

                # --- 2. MARGE NETTE % ---
                if item["revenue"] and item["net_income"] and item["revenue"] > 0:
                    margin = (item["net_income"] / item["revenue"]) * 100
                    history["Marge Net %"].append(clean_val(margin, "{:.1f}%"))
                else:
                    history["Marge Net %"].append("N/A")

                # --- 3. ROE HISTORIQUE TRIMESTRIEL ---
                if item["net_income"] and item["equity"] and item["equity"] > 0:
                    roe_val = (item["net_income"] * 4 / item["equity"]) * 100  # Annualisé
                    history["ROE"].append(clean_val(roe_val, "{:.1f}%"))
                else:
                    history["ROE"].append("N/A")

                # Ratios de valorisation historiques non fournis par API gratuites sans historique de prix
                history["Fwd P/E"].append("N/A")
                history["EV/EBITDA"].append("N/A")
                history["PEG"].append("N/A")

            if len(quarters) > 0:
                return quarters, history

    except Exception as e:
        print(f"    ⚠️ Erreur Yahoo Finance sur {symbol} : {e}")

    return quarters, history

def generate_dashboard_data():
    prices_data = []
    news_data = []
    fundamentals_data = []

    belgium_tz = ZoneInfo("Europe/Brussels")
    now_be = datetime.now(belgium_tz)
    now_ts = now_be.timestamp()
    cutoff_ts = now_ts - (72 * 3600 if now_be.weekday() == 0 else 24 * 3600)

    print(f"📊 Mise à jour des données pour {len(TICKERS)} tickers...")

    for symbol in TICKERS:
        try:
            print(f"    ➜ Traitement : {symbol}")
            ticker = yf.Ticker(symbol)
            info = ticker.info or {}

            # 1. PRIX & SMA 200 WEEKLY
            price = info.get("currentPrice") or info.get("regularMarketPrice") or 0.0
            prev_close = info.get("previousClose") or price
            change_pct = ((price - prev_close) / prev_close) * 100 if prev_close > 0 else 0.0
            currency = "€" if any(symbol.endswith(ext) for ext in [".BR", ".BE", ".PA", ".AS"]) else "$"

            sma200_str, sma200_pct = check_200_weekly_sma(ticker, price)

            prices_data.append({
                "ticker": symbol,
                "price": round(price, 2),
                "change": round(change_pct, 2),
                "currency": currency,
                "sma200": sma200_str,
                "sma200_pct": sma200_pct,
                "earnings": get_next_earnings_date(ticker, belgium_tz)
            })

            # 2. NEWS
            news_list = ticker.news or []
            for item in news_list:
                content = item.get("content", item)
                title = content.get("title") or item.get("title", "")
                summary = content.get("summary") or item.get("summary") or ""
                pub_time = content.get("pubDate") or item.get("providerPublishTime", 0)

                if isinstance(pub_time, str):
                    try:
                        pub_time = datetime.fromisoformat(pub_time.replace("Z", "+00:00")).timestamp()
                    except Exception:
                        pub_time = now_ts

                if pub_time >= cutoff_ts:
                    link = content.get("clickThroughUrl", {}).get("url") or item.get("link")
                    pub_dt = datetime.fromtimestamp(pub_time, tz=belgium_tz)
                    news_data.append({
                        "ticker": symbol,
                        "title": title,
                        "summary": summary[:200] + "..." if len(summary) > 200 else summary,
                        "link": link,
                        "date": pub_dt.strftime("%H:%M")
                    })

            # 3. HISTORIQUE TRIMESTRIEL
            quarters, q_history = get_quarterly_history(symbol, ticker, info)

            rev_growth = info.get('revenueGrowth')
            fwd_pe = info.get('forwardPE')
            ev_ebitda = info.get('enterpriseToEbitda')
            roe = info.get('returnOnEquity')
            peg = info.get('pegRatio')
            profit_margin = info.get('profitMargins')

            fundamentals_data.append({
                "ticker": symbol,
                "rev_growth": clean_val(rev_growth * 100 if rev_growth else None, "{:+.1f}%"),
                "pe": clean_val(fwd_pe, "{:.1f}x"),
                "ev": clean_val(ev_ebitda, "{:.1f}x"),
                "roe": clean_val(roe * 100 if roe else None, "{:.1f}%"),
                "peg": clean_val(peg, "{:.2f}"),
                "net_margin": clean_val(profit_margin * 100 if profit_margin else None, "{:.1f}%"),
                "quarters": quarters,
                "history": q_history
            })

        except Exception as e:
            print(f"⚠️ Erreur sur {symbol}: {e}")

    output = {
        "updated_at": now_be.strftime("%d/%m/%Y à %H:%M"),
        "prices": prices_data,
        "news": news_data,
        "fundamentals": fundamentals_data
    }

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✅ data.json généré avec succès à {now_be.strftime('%H:%M')} (Heure belge) !")

if __name__ == "__main__":
    generate_dashboard_data()
