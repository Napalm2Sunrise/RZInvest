from datetime import datetime
import json
import math
import os
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

# Clé API Financial Modeling Prep (récupérée de l'environnement GitHub Actions)
FMP_API_KEY = os.environ.get("FMP_API_KEY", "")

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

def fetch_fmp_data(endpoint):
    """Effectue un appel API HTTP vers Financial Modeling Prep."""
    if not FMP_API_KEY:
        return []
    try:
        url = f"https://financialmodelingprep.com/api/v3/{endpoint}?apikey={FMP_API_KEY}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            if response.status == 200:
                return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print(f"    ⚠️ Erreur API FMP ({endpoint}): {e}")
    return []

def get_fmp_symbol(symbol):
    """Convertit les symboles Yahoo vers le format FMP (ex: ASML.AS -> ASML)."""
    return symbol.split('.')[0]

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

def get_quarterly_history_fmp(symbol, ticker, info):
    """Récupère l'historique sur 10 trimestres via FMP ou Fallback Yahoo Finance."""
    quarters = []
    history = {
        "Croit. CA.": [],
        "Marge Net %": [],
        "Fwd P/E": [],
        "EV/EBITDA": [],
        "ROE": [],
        "PEG": []
    }

    fmp_symbol = get_fmp_symbol(symbol)
    
    # 1. Récupération des états financiers (autorisés en version gratuite FMP)
    income_data = fetch_fmp_data(f"income-statement/{fmp_symbol}?period=quarter&limit=16")
    key_metrics_data = fetch_fmp_data(f"key-metrics/{fmp_symbol}?period=quarter&limit=16")

    # Métriques actuelles (Yahoo + FMP) pour le remplissage sécurisé des ratios de valorisation
    curr_pe = clean_val(info.get('forwardPE') or info.get('trailingPE'), "{:.1f}x")
    curr_ev = clean_val(info.get('enterpriseToEbitda'), "{:.1f}x")
    curr_roe = clean_val(info.get('returnOnEquity', 0) * 100 if info.get('returnOnEquity') else None, "{:.1f}%")
    curr_peg = clean_val(info.get('pegRatio'), "{:.2f}")

    if isinstance(income_data, list) and len(income_data) > 0:
        income_data = sorted(income_data, key=lambda x: x.get('date', ''), reverse=True)
        metrics_dict = {m.get('date'): m for m in key_metrics_data} if isinstance(key_metrics_data, list) else {}

        for i, inc in enumerate(income_data[:10]):
            date_str = inc.get('date', '')
            period = inc.get('period', '')
            year = date_str.split('-')[0] if date_str else ''
            q_label = f"{period}-{year}" if period and year else date_str
            quarters.append(q_label)

            # --- A. MARGE NETTE % ---
            rev = inc.get('revenue')
            net_inc = inc.get('netIncome')
            if rev and net_inc and rev > 0:
                history["Marge Net %"].append(clean_val((net_inc / rev) * 100, "{:.1f}%"))
            else:
                history["Marge Net %"].append("N/A")

            # --- B. CROISSANCE CA (YoY : Trimestre vs Même trimestre N-1) ---
            if i + 4 < len(income_data):
                prev_rev = income_data[i + 4].get('revenue')
                if rev and prev_rev and prev_rev > 0:
                    growth = ((rev - prev_rev) / prev_rev) * 100
                    history["Croit. CA."].append(clean_val(growth, "{:+.1f}%"))
                else:
                    history["Croit. CA."].append("N/A")
            elif i + 1 < len(income_data):  # Fallback QoQ si N-1 indisponible
                prev_q = income_data[i + 1].get('revenue')
                if rev and prev_q and prev_q > 0:
                    growth = ((rev - prev_q) / prev_q) * 100
                    history["Croit. CA."].append(clean_val(growth, "{:+.1f}%"))
                else:
                    history["Croit. CA."].append("N/A")
            else:
                history["Croit. CA."].append("N/A")

            # --- C. RATIOS (Extraction FMP si disponible, sinon fallback actuel) ---
            m = metrics_dict.get(date_str, {})
            
            pe = clean_val(m.get('peRatio'), "{:.1f}x")
            history["Fwd P/E"].append(pe if pe != "N/A" else curr_pe)

            ev = clean_val(m.get('enterpriseValueMultiple'), "{:.1f}x")
            history["EV/EBITDA"].append(ev if ev != "N/A" else curr_ev)

            roe = clean_val(m.get('roe', 0) * 100 if m.get('roe') else None, "{:.1f}%")
            history["ROE"].append(roe if roe != "N/A" else curr_roe)

            peg = clean_val(m.get('pegRatio'), "{:.2f}")
            history["PEG"].append(peg if peg != "N/A" else curr_peg)

        return quarters, history

    # 2. FALLBACK YAHOO FINANCE SI FMP NE RENVOIE RIEN
    try:
        q_fin = ticker.quarterly_financials
        if q_fin is not None and not q_fin.empty:
            cols = list(q_fin.columns[:10])
            for i, col in enumerate(cols):
                dt = col.to_pydatetime() if hasattr(col, "to_pydatetime") else col
                q_num = (dt.month - 1) // 3 + 1
                q_label = f"Q{q_num}-{dt.year}"
                quarters.append(q_label)

                try:
                    net_inc = q_fin.loc['Net Income', col] if 'Net Income' in q_fin.index else None
                    tot_rev = q_fin.loc['Total Revenue', col] if 'Total Revenue' in q_fin.index else None
                    history["Marge Net %"].append(clean_val((net_inc / tot_rev) * 100 if net_inc and tot_rev else None, "{:.1f}%"))
                except Exception:
                    history["Marge Net %"].append("N/A")

                try:
                    tot_rev_curr = q_fin.loc['Total Revenue', col] if 'Total Revenue' in q_fin.index else None
                    if i + 4 < len(q_fin.columns):
                        tot_rev_prev = q_fin.loc['Total Revenue', q_fin.columns[i + 4]]
                        history["Croit. CA."].append(clean_val(((tot_rev_curr - tot_rev_prev) / tot_rev_prev) * 100 if tot_rev_curr and tot_rev_prev else None, "{:+.1f}%"))
                    elif i + 1 < len(q_fin.columns):
                        tot_rev_prev = q_fin.loc['Total Revenue', q_fin.columns[i + 1]]
                        history["Croit. CA."].append(clean_val(((tot_rev_curr - tot_rev_prev) / tot_rev_prev) * 100 if tot_rev_curr and tot_rev_prev else None, "{:+.1f}%"))
                    else:
                        history["Croit. CA."].append("N/A")
                except Exception:
                    history["Croit. CA."].append("N/A")

                history["Fwd P/E"].append(curr_pe)
                history["EV/EBITDA"].append(curr_ev)
                history["ROE"].append(curr_roe)
                history["PEG"].append(curr_peg)
    except Exception as e:
        print(f"    ⚠️ Erreur Fallback Yahoo sur {symbol} : {e}")

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

            # 3. HISTORIQUE TRIMESTRIEL FMP & FALLBACK YAHOO
            quarters, q_history = get_quarterly_history_fmp(symbol, ticker, info)

            # Ratios globaux (synthèse)
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
