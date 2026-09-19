from datetime import datetime
import json
import math
import os
from zoneinfo import ZoneInfo
import yfinance as yf

# ==============================================================================
# TICKERS
# ==============================================================================
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

def get_quarterly_history(ticker, info):
    """Récupère les données historiques réelles sur 10 trimestres."""
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
        if q_fin is not None and not q_fin.empty:
            # Récupère jusqu'à 10 trimestres
            cols = list(q_fin.columns[:10])

            # Ratios statiques actuels
            fwd_pe_now = clean_val(info.get('forwardPE'), "{:.1f}x")
            ev_ebitda_now = clean_val(info.get('enterpriseToEbitda'), "{:.1f}x")
            roe_now = clean_val(info.get('returnOnEquity', 0) * 100, "{:.1f}%")
            peg_now = clean_val(info.get('pegRatio'), "{:.2f}")

            for i, col in enumerate(cols):
                # Formatage du nom du trimestre (ex: Q1-2026)
                dt = col.to_pydatetime() if hasattr(col, "to_pydatetime") else col
                q_num = (dt.month - 1) // 3 + 1
                q_label = f"Q{q_num}-{dt.year}"
                quarters.append(q_label)

                # 1. Calcul Marge Nette % (Trimester par Trimester)
                try:
                    net_inc = q_fin.loc['Net Income', col] if 'Net Income' in q_fin.index else None
                    tot_rev = q_fin.loc['Total Revenue', col] if 'Total Revenue' in q_fin.index else None

                    if net_inc is not None and tot_rev is not None and tot_rev != 0:
                        margin = (net_inc / tot_rev) * 100
                        history["Marge Net %"].append(clean_val(margin, "{:.1f}%"))
                    else:
                        history["Marge Net %"].append("N/A")
                except Exception:
                    history["Marge Net %"].append("N/A")

                # 2. Calcul Croissance CA YoY (Comparé à N-4)
                try:
                    tot_rev_current = q_fin.loc['Total Revenue', col] if 'Total Revenue' in q_fin.index else None
                    if i + 4 < len(q_fin.columns):
                        prev_col = q_fin.columns[i + 4]
                        tot_rev_prev = q_fin.loc['Total Revenue', prev_col]
                        if tot_rev_current and tot_rev_prev and tot_rev_prev != 0:
                            growth = ((tot_rev_current - tot_rev_prev) / tot_rev_prev) * 100
                            history["Croit. CA."].append(clean_val(growth, "{:+.1f}%"))
                        else:
                            history["Croit. CA."].append("N/A")
                    else:
                        # Si on n'a pas N-4 pour ce trimestre spécifique, indiquer N/A au lieu d'une fausse répétition
                        history["Croit. CA."].append("N/A")
                except Exception:
                    history["Croit. CA."].append("N/A")

                # 3. Ratios statiques actuels (affichés uniquement sur le dernier trimestre disponible i == 0)
                if i == 0:
                    history["Fwd P/E"].append(fwd_pe_now)
                    history["EV/EBITDA"].append(ev_ebitda_now)
                    history["ROE"].append(roe_now)
                    history["PEG"].append(peg_now)
                else:
                    # N/A pour les trimestres passés car non fournis dans les API Yahoo historiques
                    history["Fwd P/E"].append("N/A")
                    history["EV/EBITDA"].append("N/A")
                    history["ROE"].append("N/A")
                    history["PEG"].append("N/A")

    except Exception as e:
        print(f"    ⚠️ Impossible de charger l'historique trimestriel : {e}")

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

            # 3. RATIOS & HISTORIQUE TRIMESTRIEL
            rev_growth = info.get('revenueGrowth')
            fwd_pe = info.get('forwardPE')
            ev_ebitda = info.get('enterpriseToEbitda')
            roe = info.get('returnOnEquity')
            peg = info.get('pegRatio')
            profit_margin = info.get('profitMargins')

            quarters, q_history = get_quarterly_history(ticker, info)

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
