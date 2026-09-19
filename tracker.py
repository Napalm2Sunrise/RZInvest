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

# Clé API Finnhub (récupérée de l'environnement GitHub Actions)
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "")

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

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

def fetch_finnhub_data(endpoint):
    """Effectue un appel API HTTP vers Finnhub."""
    if not FINNHUB_API_KEY:
        return None
    try:
        sep = "&" if "?" in endpoint else "?"
        url = f"https://finnhub.io/api/v1/{endpoint}{sep}token={FINNHUB_API_KEY}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            if response.status == 200:
                return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print(f"    ⚠️ Erreur API Finnhub ({endpoint}): {e}")
    return None

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
    """Récupère l'historique sur 10 trimestres via Finnhub ou Fallback Yahoo Finance."""
    quarters = []
    history = {
        "Croit. CA.": [],
        "Marge Net %": [],
        "Fwd P/E": [],
        "EV/EBITDA": [],
        "ROE": [],
        "PEG": []
    }

    # Métriques actuelles (Yahoo) pour remplissage des ratios
    curr_pe = clean_val(info.get('forwardPE') or info.get('trailingPE'), "{:.1f}x")
    curr_ev = clean_val(info.get('enterpriseToEbitda'), "{:.1f}x")
    curr_roe = clean_val(info.get('returnOnEquity', 0) * 100 if info.get('returnOnEquity') else None, "{:.1f}%")
    curr_peg = clean_val(info.get('pegRatio'), "{:.2f}")

    # 1. TENTATIVE VIA FINNHUB
    finnhub_data = fetch_finnhub_data(f"stock/financials-reported?symbol={symbol}&freq=quarterly")
    
    if finnhub_data and isinstance(finnhub_data.get("data"), list) and len(finnhub_data["data"]) > 0:
        reports = sorted(finnhub_data["data"], key=lambda x: x.get("endDate", ""), reverse=True)
        
        for i, rep in enumerate(reports[:10]):
            year = rep.get("year")
            quarter = rep.get("quarter")
            q_label = f"Q{quarter}-{year}" if quarter and year else rep.get("endDate", "N/A")
            quarters.append(q_label)

            # Extraction des données financières Finnhub
            ic_reports = rep.get("report", {}).get("ic", [])
            revenue = None
            net_income = None

            for concept in ic_reports:
                concept_name = concept.get("concept", "").lower()
                val = concept.get("value")
                if val is not None:
                    if "revenues" in concept_name or "salesrevenue net" in concept_name or "revenuefromcontractwithcustomer" in concept_name:
                        revenue = float(val)
                    elif "netincomeloss" in concept_name or "profitloss" in concept_name:
                        net_income = float(val)

            # Marge Nette
            if revenue and net_income and revenue > 0:
                history["Marge Net %"].append(clean_val((net_income / revenue) * 100, "{:.1f}%"))
            else:
                history["Marge Net %"].append("N/A")

            # Croissance CA (YoY vs Q-4)
            if i + 4 < len(reports):
                prev_ic = reports[i + 4].get("report", {}).get("ic", [])
                prev_rev = None
                for c in prev_ic:
                    c_name = c.get("concept", "").lower()
                    if "revenues" in c_name or "salesrevenue net" in c_name or "revenuefromcontractwithcustomer" in c_name:
                        prev_rev = float(c.get("value", 0))
                        break
                if revenue and prev_rev and prev_rev > 0:
                    growth = ((revenue - prev_rev) / prev_rev) * 100
                    history["Croit. CA."].append(clean_val(growth, "{:+.1f}%"))
                else:
                    history["Croit. CA."].append("N/A")
            else:
                history["Croit. CA."].append("N/A")

            # Ratios
            history["Fwd P/E"].append(curr_pe)
            history["EV/EBITDA"].append(curr_ev)
            history["ROE"].append(curr_roe)
            history["PEG"].append(curr_peg)

        if len(quarters) > 0:
            return quarters, history

    # 2. FALLBACK YAHOO FINANCE (Si Finnhub ne renvoie pas de données)
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
                    if net_inc is not None and tot_rev is not None and tot_rev > 0:
                        history["Marge Net %"].append(clean_val((net_inc / tot_rev) * 100, "{:.1f}%"))
                    else:
                        history["Marge Net %"].append("N/A")
                except Exception:
                    history["Marge Net %"].append("N/A")

                try:
                    tot_rev_curr = q_fin.loc['Total Revenue', col] if 'Total Revenue' in q_fin.index else None
                    if i + 4 < len(q_fin.columns):
                        tot_rev_prev = q_fin.loc['Total Revenue', q_fin.columns[i + 4]]
                        growth = ((tot_rev_curr - tot_rev_prev) / tot_rev_prev) * 100 if tot_rev_curr and tot_rev_prev else None
                        history["Croit. CA."].append(clean_val(growth, "{:+.1f}%"))
                    elif i + 1 < len(q_fin.columns):
                        tot_rev_prev = q_fin.loc['Total Revenue', q_fin.columns[i + 1]]
                        growth = ((tot_rev_curr - tot_rev_prev) / tot_rev_prev) * 100 if tot_rev_curr and tot_rev_prev else None
                        history["Croit. CA."].append(clean_val(growth, "{:+.1f}%"))
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

            # 3. HISTORIQUE TRIMESTRIEL
            quarters, q_history = get_quarterly_history(symbol, ticker, info)

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
