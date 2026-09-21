from datetime import datetime
import json
import math
import os
import time
from zoneinfo import ZoneInfo
import yfinance as yf

# ==============================================================================
# CONFIGURATION
# ==============================================================================
TICKERS = [
    "AED.BR", "CPINV.BE", "HOMI.BR", "RET.BR", "AAOI", "AMD", "AMKR", "AMZN", "ASML.AS",   
    "AVGO", "AYA.TO", "BKNG", "CPRT", "CSW", "GEV", "GOOG", "ISRG", 
    "META", "MC.PA", "MSFT", "NVDA", "ONON", "RMS.PA", "SPCX", "SPGI", "SU.PA", 
    "TTE.PA", "TSLA", "VRSN"
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

def check_200_weekly_sma_from_hist(hist_daily, current_price):
    """Calcul de la 200 Weekly SMA basé sur l'historique daily pré-chargé."""
    try:
        if hist_daily is not None and not hist_daily.empty and len(hist_daily) >= 200:
            hist_weekly = hist_daily.resample('W-FRI').last().dropna()
            if len(hist_weekly) >= 200:
                sma_series = hist_weekly.rolling(window=200).mean()
                sma_200 = float(sma_series.iloc[-1])
                if sma_200 > 0 and current_price > 0:
                    raw_pct = ((current_price - sma_200) / sma_200) * 100
                    pct = round(raw_pct, 1)
                    if current_price < sma_200:
                        return f"200 W-SMA Under {pct}% 🔥", pct, True
                    else:
                        return f"200 W-SMA Above +{pct}%", pct, False
    except Exception as e:
        print(f"    ⚠️ Erreur calcul SMA200: {e}")
    return "N/A", None, False

def calculate_rsi14_weekly(hist_daily):
    """Calcul du RSI 14 périodes sur bougies hebdomadaires."""
    try:
        if hist_daily is not None and not hist_daily.empty:
            hist_weekly = hist_daily.resample('W-FRI').last().dropna()
            if len(hist_weekly) >= 15:
                delta = hist_weekly.diff()
                gain = delta.where(delta > 0, 0.0)
                loss = -delta.where(delta < 0, 0.0)

                # Calcul des moyennes mobiles lissées (EMA / Wilder)
                avg_gain = gain.ewm(alpha=1/14, adjust=False).mean()
                avg_loss = loss.ewm(alpha=1/14, adjust=False).mean()

                last_gain = avg_gain.iloc[-1]
                last_loss = avg_loss.iloc[-1]

                if last_loss == 0:
                    return 100.0
                
                rs = last_gain / last_loss
                rsi = 100 - (100 / (1 + rs))
                return round(float(rsi), 1)
    except Exception as e:
        print(f"    ⚠️ Erreur calcul RSI14 Weekly: {e}")
    return "N/A"

def calculate_ath_52w_pct(hist_daily, current_price):
    """Calcul du % d'écart entre le prix actuel et le plus haut des 52 dernières semaines."""
    try:
        if hist_daily is not None and not hist_daily.empty:
            # 52 semaines ~ 252 jours boursiers
            last_52w = hist_daily.tail(252)
            ath_52w = float(last_52w.max())
            if ath_52w > 0 and current_price > 0:
                pct = ((current_price - ath_52w) / ath_52w) * 100
                return round(pct, 1)
    except Exception as e:
        print(f"    ⚠️ Erreur calcul ATH 52W: {e}")
    return "N/A"

def get_next_earnings_date(ticker, belgium_tz):
    """Récupère la prochaine date de résultats."""
    try:
        calendar = ticker.calendar
        now = datetime.now(belgium_tz).date()
        if isinstance(calendar, dict) and "Earnings Date" in calendar:
            for d in calendar["Earnings Date"]:
                d_date = d.date() if isinstance(d, datetime) else d
                if d_date >= now:
                    return d_date.strftime("%d/%m/%Y")
        elif hasattr(calendar, 'get') and calendar.get("Earnings Date") is not None:
            dates = calendar.get("Earnings Date")
            for d in dates:
                d_date = d.date() if isinstance(d, datetime) else d
                if d_date >= now:
                    return d_date.strftime("%d/%m/%Y")
    except Exception:
        pass
    return "N/A"

def get_financial_item(df, possible_keys, col):
    """Helper pour extraire une ligne financière en testant plusieurs libellés possibles."""
    if df is None or df.empty or col not in df.columns:
        return None
    for key in possible_keys:
        if key in df.index:
            val = df.loc[key, col]
            if not math.isnan(val):
                return float(val)
    return None

def get_annual_history(ticker, info):
    """
    Construit la vue annuelle dynamique : Année en cours (TTM) + Années précédentes clôturées.
    """
    current_year = datetime.now().year
    years_labels = [f"{current_year} (TTM)"]
    history = {
        "Croit. CA.": [],
        "Marge Net %": [],
        "Fwd P/E": [],
        "EV/EBITDA": [],
        "ROE": [],
        "PEG": []
    }

    # 1. VALEURS POUR L'ANNÉE EN COURS (TTM / ACTUELLES)
    rev_growth = info.get('revenueGrowth')
    fwd_pe = info.get('forwardPE') or info.get('trailingPE')
    ev_ebitda = info.get('enterpriseToEbitda')
    roe = info.get('returnOnEquity')
    peg = info.get('pegRatio')
    profit_margin = info.get('profitMargins')

    history["Croit. CA."].append(clean_val(rev_growth * 100 if rev_growth is not None else None, "{:+.1f}%"))
    history["Marge Net %"].append(clean_val(profit_margin * 100 if profit_margin is not None else None, "{:.1f}%"))
    history["Fwd P/E"].append(clean_val(fwd_pe, "{:.1f}x"))
    history["EV/EBITDA"].append(clean_val(ev_ebitda, "{:.1f}x"))
    history["ROE"].append(clean_val(roe * 100 if roe is not None else None, "{:.1f}%"))
    history["PEG"].append(clean_val(peg, "{:.2f}"))

    # 2. VALEURS HISTORIQUES (Exclure l'année en cours et supérieures pour éviter le doublon avec TTM)
    try:
        fin = getattr(ticker, 'income_stmt', None)
        if fin is None or fin.empty:
            fin = ticker.financials

        bs = getattr(ticker, 'balance_sheet', None)

        if fin is not None and not fin.empty:
            cols = list(fin.columns)
            sorted_cols = sorted(cols, key=lambda c: c.year if hasattr(c, "year") else int(str(c)[:4]), reverse=True)

            data_by_year = {}
            for col in sorted_cols:
                yr = col.year if hasattr(col, "year") else int(str(col)[:4])

                rev = get_financial_item(fin, ['Total Revenue', 'Operating Revenue', 'Revenue'], col)
                net_inc = get_financial_item(fin, ['Net Income', 'Net Income Common Stockholders', 'Net Income From Continuing Operation Net Minority Interest'], col)
                equity = get_financial_item(bs, ['Stockholders Equity', 'Total Stockholder Equity', 'Common Stock Equity'], col)

                data_by_year[yr] = {
                    "revenue": rev,
                    "net_income": net_inc,
                    "equity": equity
                }

            # Filtrage : ne garder que les années STRICTEMENT antérieures à l'année courante
            past_years = [y for y in sorted(data_by_year.keys(), reverse=True) if y < current_year]

            for yr in past_years[:4]:
                years_labels.append(str(yr))
                item = data_by_year[yr]

                # Croissance CA YoY vs Année précédente
                prev_yr = yr - 1
                if prev_yr in data_by_year and data_by_year[prev_yr]["revenue"]:
                    rev_curr = item["revenue"]
                    rev_prev = data_by_year[prev_yr]["revenue"]
                    if rev_curr and rev_prev and rev_prev > 0:
                        growth = ((rev_curr - rev_prev) / rev_prev) * 100
                        history["Croit. CA."].append(clean_val(growth, "{:+.1f}%"))
                    else:
                        history["Croit. CA."].append("N/A")
                else:
                    history["Croit. CA."].append("N/A")

                # Marge Nette %
                if item["revenue"] and item["net_income"] and item["revenue"] > 0:
                    margin = (item["net_income"] / item["revenue"]) * 100
                    history["Marge Net %"].append(clean_val(margin, "{:.1f}%"))
                else:
                    history["Marge Net %"].append("N/A")

                # ROE %
                if item["net_income"] and item["equity"] and item["equity"] > 0:
                    roe_val = (item["net_income"] / item["equity"]) * 100
                    history["ROE"].append(clean_val(roe_val, "{:.1f}%"))
                else:
                    history["ROE"].append("N/A")

                # Ratios non-disponibles dans l'historique gratuit
                history["Fwd P/E"].append("N/A")
                history["EV/EBITDA"].append("N/A")
                history["PEG"].append("N/A")

    except Exception as e:
        print(f"    ⚠️ Erreur données annuelles : {e}")

    return years_labels, history

def generate_dashboard_data():
    prices_data = []
    news_data = []
    fundamentals_data = []

    belgium_tz = ZoneInfo("Europe/Brussels")
    now_be = datetime.now(belgium_tz)
    now_ts = now_be.timestamp()
    # MODIFICATION : Limiter strictement aux news publiées il y a moins de 24h
    cutoff_ts = now_ts - (24 * 3600)

    print(f"📊 Téléchargement groupé pour {len(TICKERS)} tickers...")
    
    # 1. Requête groupée pour les historiques daily (SMA200, RSI14 & ATH 52W)
    batch_hist = {}
    try:
        download_data = yf.download(TICKERS, period="5y", interval="1d", group_by="ticker", auto_adjust=False, progress=False)
        for symbol in TICKERS:
            if len(TICKERS) > 1:
                if symbol in download_data and 'Close' in download_data[symbol]:
                    batch_hist[symbol] = download_data[symbol]['Close'].dropna()
            else:
                if 'Close' in download_data:
                    batch_hist[symbol] = download_data['Close'].dropna()
    except Exception as e:
        print(f"⚠️ Erreur lors du téléchargement groupé yf.download: {e}")

    # 2. Initialisation Tickers groupés
    tickers_objs = yf.Tickers(" ".join(TICKERS))

    for symbol in TICKERS:
        try:
            print(f"   ➜ Traitement : {symbol}")
            ticker = tickers_objs.tickers.get(symbol) or yf.Ticker(symbol)
            info = {}
            try:
                info = ticker.info or {}
            except Exception:
                pass

            # PRIX, SMA 200 WEEKLY, RSI 14 WEEKLY & ATH 52W
            price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
            
            hist_close = batch_hist.get(symbol)
            if not price or price == 0.0:
                fast_info = getattr(ticker, 'fast_info', {})
                price = fast_info.get("last_price") or fast_info.get("previous_close")
            if not price or math.isnan(price):
                if hist_close is not None and not hist_close.empty:
                    price = float(hist_close.iloc[-1])
                else:
                    price = 0.0

            prev_close = info.get("previousClose") or price
            change_pct = ((price - prev_close) / prev_close) * 100 if prev_close and prev_close > 0 else 0.0
            currency = "€" if any(symbol.endswith(ext) for ext in [".BR", ".BE", ".PA", ".AS"]) else "$"

            sma200_str, sma200_pct, is_under = check_200_weekly_sma_from_hist(hist_close, price)
            rsi14_w = calculate_rsi14_weekly(hist_close)
            ath_52w_pct = calculate_ath_52w_pct(hist_close, price)

            prices_data.append({
                "ticker": symbol,
                "price": round(price, 2) if price else 0.0,
                "change": round(change_pct, 2) if change_pct else 0.0,
                "currency": currency,
                "sma200": sma200_str,
                "sma200_pct": sma200_pct,
                "is_under": is_under,
                "rsi14_weekly": rsi14_w,
                "ath_52w_pct": ath_52w_pct,
                "earnings": get_next_earnings_date(ticker, belgium_tz)
            })

            # NEWS
            try:
                news_list = ticker.news or []
                # MODIFICATION : Limiter à 4 news max par ticker
                ticker_news_count = 0
                for item in news_list:
                    if ticker_news_count >= 3:
                        break

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
                            "date": pub_dt.isoformat()
                        })
                        ticker_news_count += 1
            except Exception as e:
                print(f"    ⚠️ Erreur news sur {symbol}: {e}")

            # HISTORIQUE ANNUEL
            years, annual_history = get_annual_history(ticker, info)

            rev_growth = info.get('revenueGrowth')
            fwd_pe = info.get('forwardPE') or info.get('trailingPE')
            ev_ebitda = info.get('enterpriseToEbitda')
            roe = info.get('returnOnEquity')
            peg = info.get('pegRatio')
            profit_margin = info.get('profitMargins')

            fundamentals_data.append({
                "ticker": symbol,
                "rev_growth": clean_val(rev_growth * 100 if rev_growth is not None else None, "{:+.1f}%"),
                "pe": clean_val(fwd_pe, "{:.1f}x"),
                "ev": clean_val(ev_ebitda, "{:.1f}x"),
                "roe": clean_val(roe * 100 if roe is not None else None, "{:.1f}%"),
                "peg": clean_val(peg, "{:.2f}"),
                "net_margin": clean_val(profit_margin * 100 if profit_margin is not None else None, "{:.1f}%"),
                "quarters": years,
                "history": annual_history
            })

        except Exception as e:
            print(f"⚠️ Erreur globale sur {symbol}: {e}")

    output = {
        "updated_at": now_be.strftime("%d/%m/%Y à %H:%M"),
        "prices": prices_data,
        "news": news_data,
        "fundamentals": fundamentals_data
    }

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✅ data.json généré avec succès avec toutes les données des {len(TICKERS)} tickers !")

if __name__ == "__main__":
    generate_dashboard_data()
