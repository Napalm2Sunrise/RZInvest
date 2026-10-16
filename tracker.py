from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus
import json
import math
import os
import re
import time
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo
import requests
import yfinance as yf

# ==============================================================================
# CONFIGURATION DES TICKERS PAR CATÉGORIE
# ==============================================================================
REITS_TICKERS = [
    "AED.BR", "CPINV.BR", "HOMI.BR", "WDP.BR", "PLD", "GMG.AX", "DLR", "EQIX", "WELL"
]

STOCKS_TICKERS = [
    "AAOI", "AMD", "AMKR", "AMZN", "ASML.AS",   
    "AVGO", "AYA.TO", "BKNG", "CPRT", "CRWV", "CSW", "GOOG", "GRAB", "ISRG", "JNJ", 
    "META", "MC.PA", "MSFT", "MU", "NBIS", "NVDA", "ONON", "PEP", "PG", "RMS.PA", "SPCX", "SPGI", "SU.PA", 
    "TMO", "TTE.PA", "TSLA", "UBER", "VRSN", "VRT", "VST"
]

CRYPTO_TICKERS = [
    "BTC-USD", "ETH-USD", "SOL-USD", "HYPE32196-USD", "PUMP-USD", "AAVE-USD", "LINK-USD"
]

# ==============================================================================
# CONFIGURATION DES NEWS
# ==============================================================================
NEWS_MAX_AGE_DAYS = 7        # fenêtre de fraîcheur des news (avant : 24h => trop strict)
MAX_NEWS_PER_TICKER = 6      # nombre max de news conservées par ticker dans data.json
GOOGLE_NEWS_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; RZInvestBot/1.0)"}

# Noms utilisés pour les recherches Google News (un symbole seul est trop ambigu : "PG", "SU", "RET"...)
TICKER_NAMES = {
    # REITs
    "AED.BR": "Aedifica", "CPINV.BR": "Care Property Invest", "HOMI.BR": "Home Invest Belgium",
    "RET.BR": "Retail Estates", "PLD": "Prologis", "GMG.AX": "Goodman Group",
    "DLR": "Digital Realty", "EQIX": "Equinix", "WELL": "Welltower",
    # Stocks
    "AAOI": "Applied Optoelectronics", "AMD": "AMD", "AMKR": "Amkor Technology", "AMZN": "Amazon",
    "ASML.AS": "ASML", "AVGO": "Broadcom", "AYA.TO": "Aya Gold & Silver", "BKNG": "Booking Holdings",
    "CPRT": "Copart", "CSW": "CSW Industrials", "GOOG": "Alphabet Google", "GRAB": "Grab Holdings",
    "ISRG": "Intuitive Surgical", "JNJ": "Johnson & Johnson", "META": "Meta Platforms",
    "MC.PA": "LVMH", "MSFT": "Microsoft", "NBIS": "Nebius", "NVDA": "Nvidia", "ONON": "On Holding",
    "PEP": "PepsiCo", "PG": "Procter & Gamble", "RMS.PA": "Hermès", "SPGI": "S&P Global",
    "SU.PA": "Schneider Electric", "TMO": "Thermo Fisher", "TTE.PA": "TotalEnergies", "TSLA": "Tesla",
    "UBER": "Uber", "VRSN": "VeriSign", "VRT": "Vertiv", "VST": "Vistra",
    # Crypto
    "BTC-USD": "Bitcoin", "ETH-USD": "Ethereum", "SOL-USD": "Solana",
    "HYPE32196-USD": "Hyperliquid", "PUMP-USD": "Pump.fun", "AAVE-USD": "Aave", "LINK-USD": "Chainlink",
}

def get_search_name(symbol, info):
    """Nom utilisé pour la recherche de news (dictionnaire > yfinance > symbole)."""
    name = TICKER_NAMES.get(symbol)
    if name:
        return name
    name = info.get("shortName") or info.get("longName") or symbol.split('.')[0].split('-')[0]
    name = re.sub(r"\b(Inc|Corp|Corporation|Ltd|PLC|SA|NV|Co)\b\.?,?", "", name, flags=re.I)
    return name.strip(" ,.") or symbol

def _fetch_google_news_feed(query, hl, gl, ceid, cutoff_ts):
    """Lit un flux RSS Google News (côté serveur : pas de CORS, pas de proxy tiers)."""
    url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl={hl}&gl={gl}&ceid={ceid}"
    items = []
    try:
        resp = requests.get(url, headers=GOOGLE_NEWS_HEADERS, timeout=15)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        for it in root.iter("item"):
            title = (it.findtext("title") or "").strip()
            link = (it.findtext("link") or "").strip()
            pub = it.findtext("pubDate")
            src_el = it.find("source")
            source = (src_el.text or "").strip() if src_el is not None and src_el.text else ""
            if not title or not link or not pub:
                continue
            try:
                ts = parsedate_to_datetime(pub).timestamp()
            except Exception:
                continue
            if ts < cutoff_ts:
                continue
            suffix = f" - {source}"
            if source and title.endswith(suffix):
                title = title[:-len(suffix)].strip()
            items.append({"title": title, "link": link, "source": source, "_ts": ts})
    except Exception as e:
        print(f"    ⚠️ Erreur Google News RSS ({query}): {e}")
    return items

def fetch_google_news_for_ticker(search_name, cat, cutoff_ts):
    """Google News FR d'abord, puis EN en complément si peu de résultats."""
    days = NEWS_MAX_AGE_DAYS
    if cat == "crypto":
        q_fr = f'"{search_name}" crypto when:{days}d'
        q_en = f'"{search_name}" crypto when:{days}d'
    else:
        q_fr = f'"{search_name}" (bourse OR action OR résultats OR stock) when:{days}d'
        q_en = f'"{search_name}" (stock OR shares OR earnings) when:{days}d'

    items = _fetch_google_news_feed(q_fr, "fr", "FR", "FR:fr", cutoff_ts)
    if len(items) < 3:
        items += _fetch_google_news_feed(q_en, "en-US", "US", "US:en", cutoff_ts)
    time.sleep(0.3)  # politesse envers Google
    return items

def fetch_yahoo_news(ticker, symbol, cutoff_ts):
    """News Yahoo Finance via yfinance (avec repli sur yf.Search)."""
    items = []
    raw = []
    try:
        raw = ticker.news or []
    except Exception as e:
        print(f"    ⚠️ Erreur ticker.news sur {symbol}: {e}")
    if not raw:
        try:
            raw = yf.Search(symbol, news_count=10).news or []
        except Exception:
            raw = []

    for item in raw:
        try:
            content = item.get("content", item) or item
            title = content.get("title") or item.get("title", "")
            summary = content.get("summary") or item.get("summary") or ""
            pub_time = content.get("pubDate") or item.get("providerPublishTime")

            if isinstance(pub_time, str):
                try:
                    pub_time = datetime.fromisoformat(pub_time.replace("Z", "+00:00")).timestamp()
                except Exception:
                    pub_time = None
            if not pub_time or not title or pub_time < cutoff_ts:
                continue

            link = (
                (content.get("clickThroughUrl") or {}).get("url")
                or (content.get("canonicalUrl") or {}).get("url")
                or item.get("link")
            )
            provider = (content.get("provider") or {}).get("displayName") or item.get("publisher") or ""
            if not summary and provider:
                summary = f"Source : {provider}"
            items.append({"title": title, "summary": summary, "link": link, "source": provider, "_ts": float(pub_time)})
        except Exception:
            continue
    return items

def build_ticker_news(symbol, cat, ticker, info, cutoff_ts, tz):
    """Fusionne Yahoo + Google News, dédoublonne, trie par date et formate pour data.json."""
    search_name = get_search_name(symbol, info)
    merged = fetch_yahoo_news(ticker, symbol, cutoff_ts) + fetch_google_news_for_ticker(search_name, cat, cutoff_ts)

    seen = set()
    unique = []
    for n in sorted(merged, key=lambda x: x["_ts"], reverse=True):
        key = re.sub(r"[^a-z0-9]", "", n["title"].lower())[:60]
        if key in seen:
            continue
        seen.add(key)
        unique.append(n)

    result = []
    for n in unique[:MAX_NEWS_PER_TICKER]:
        summary = n.get("summary") or (f"Source : {n['source']}" if n.get("source") else "")
        summary = summary[:200] + "..." if len(summary) > 200 else summary
        result.append({
            "ticker": symbol,
            "category": cat,
            "title": n["title"],
            "summary": summary,
            "link": n.get("link"),
            "date": datetime.fromtimestamp(n["_ts"], tz=tz).isoformat()
        })
    return result

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

def calculate_ma_cross_weekly(hist_daily):
    """Calcul du Cross 50W / 200W SMA et du % d'écart entre la 50W et 200W."""
    try:
        if hist_daily is not None and not hist_daily.empty:
            hist_weekly = hist_daily.resample('W-FRI').last().dropna()
            if len(hist_weekly) >= 200:
                sma_50 = float(hist_weekly.rolling(window=50).mean().iloc[-1])
                sma_200 = float(hist_weekly.rolling(window=200).mean().iloc[-1])
                
                if sma_50 > 0 and sma_200 > 0:
                    diff_pct = round(((sma_50 - sma_200) / sma_200) * 100, 1)
                    if sma_50 >= sma_200:
                        return f"Bullish Cross (50/200W) +{diff_pct}%", diff_pct, "bullish"
                    else:
                        return f"Bearish Cross (50/200W) {diff_pct}%", diff_pct, "bearish"
    except Exception as e:
        print(f"    ⚠️ Erreur calcul MA Cross: {e}")
    return "N/A", None, "neutral"

def calculate_macd_weekly(hist_daily):
    """Calcul du MACD Hebdomadaire (12, 26, 9)."""
    try:
        if hist_daily is not None and not hist_daily.empty:
            hist_weekly = hist_daily.resample('W-FRI').last().dropna()
            if len(hist_weekly) >= 35:
                ema12 = hist_weekly.ewm(span=12, adjust=False).mean()
                ema26 = hist_weekly.ewm(span=26, adjust=False).mean()
                macd_line = ema12 - ema26
                signal_line = macd_line.ewm(span=9, adjust=False).mean()

                last_macd = float(macd_line.iloc[-1])
                last_signal = float(signal_line.iloc[-1])

                if last_macd >= last_signal:
                    return "MACD-W Bullish", "bullish"
                else:
                    return "MACD-W Bearish", "bearish"
    except Exception as e:
        print(f"    ⚠️ Erreur calcul MACD-W: {e}")
    return "N/A", "neutral"

def calculate_rsi14_weekly(hist_daily):
    """Calcul du RSI 14 périodes sur bougies hebdomadaires."""
    try:
        if hist_daily is not None and not hist_daily.empty:
            hist_weekly = hist_daily.resample('W-FRI').last().dropna()
            if len(hist_weekly) >= 15:
                delta = hist_weekly.diff()
                gain = delta.where(delta > 0, 0.0)
                loss = -delta.where(delta < 0, 0.0)

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
            last_52w = hist_daily.tail(252)
            ath_52w = float(last_52w.max())
            if ath_52w > 0 and current_price > 0:
                pct = ((current_price - ath_52w) / ath_52w) * 100
                return round(pct, 1)
    except Exception as e:
        print(f"    ⚠️ Erreur calcul ATH 52W: {e}")
    return "N/A"

def calculate_fcf_yield(ticker, info):
    """Calcul du Free Cash Flow Yield % (FCF / Market Cap)."""
    try:
        fcf = info.get('freeCashflow')
        market_cap = info.get('marketCap')
        
        if fcf is None or market_cap is None or market_cap <= 0:
            cf = getattr(ticker, 'cashflow', None)
            if cf is not None and not cf.empty:
                col = cf.columns[0]
                ocf = get_financial_item(cf, ['Operating Cash Flow', 'Total Cash From Operating Activities'], col)
                capex = get_financial_item(cf, ['Capital Expenditure', 'Capital Expenditures'], col)
                if ocf is not None and capex is not None:
                    fcf = ocf + capex  # capex est généralement négatif dans les ETs

        if fcf is not None and market_cap and market_cap > 0:
            yield_pct = (fcf / market_cap) * 100
            return round(yield_pct, 1)
    except Exception as e:
        print(f"    ⚠️ Erreur calcul FCF Yield: {e}")
    return "N/A"

def get_all_earnings_dates(ticker_obj, symbol, belgium_tz, category):
    """Récupère toutes les dates de résultats."""
    if category == "crypto":
        return "N/A", []

    earnings_list = []
    next_earnings_str = "N/A"
    now_date = datetime.now(belgium_tz).date()
    cutoff_past_date = now_date - timedelta(days=30)
    
    clean_ticker = symbol.split('.')[0].lower()
    earnings_url = f"https://stockanalysis.com/stocks/{clean_ticker}/financials/?p=quarterly"

    try:
        dates_found = []
        df_earnings = None
        try:
            df_earnings = ticker_obj.get_earnings_dates(limit=12)
        except Exception:
            pass

        if df_earnings is not None and not df_earnings.empty:
            for idx in df_earnings.index:
                d_val = idx.date() if hasattr(idx, 'date') else idx
                dates_found.append(d_val)
        else:
            calendar = getattr(ticker_obj, 'calendar', None)
            if isinstance(calendar, dict) and "Earnings Date" in calendar:
                for d in calendar["Earnings Date"]:
                    d_val = d.date() if isinstance(d, datetime) else d
                    dates_found.append(d_val)

        dates_found = sorted(list(set(dates_found)))

        for d_date in dates_found:
            if cutoff_past_date <= d_date:
                is_past = d_date < now_date
                earnings_list.append({
                    "ticker": symbol,
                    "category": category,
                    "date": d_date.strftime("%Y-%m-%d"),
                    "date_formatted": d_date.strftime("%d/%m/%Y"),
                    "is_past": is_past,
                    "link": earnings_url
                })

        future_dates = [d for d in dates_found if d >= now_date]
        if future_dates:
            next_earnings_str = future_dates[0].strftime("%d/%m/%Y")

    except Exception as e:
        print(f"    ⚠️ Erreur récupération publications pour {symbol}: {e}")

    return next_earnings_str, earnings_list

def get_financial_item(df, possible_keys, col):
    """Extrait une ligne spécifique du compte de résultat ou du bilan/cashflow."""
    if df is None or df.empty or col not in df.columns:
        return None
    for key in possible_keys:
        if key in df.index:
            val = df.loc[key, col]
            if val is not None and not math.isnan(val):
                return float(val)
    return None

def get_annual_history(ticker, info, category):
    """Génère l'historique financier annuel."""
    if category == "crypto":
        return [], {}

    current_year = datetime.now().year
    years_labels = [f"{current_year} (TTM)"]
    history = {
        "Croit. CA.": [],
        "Marge Net %": [],
        "Fwd P/E": [],
        "EV/EBITDA": [],
        "ROE": [],
        "PEG": [],
        "FCF Yield %": []
    }

    rev_growth = info.get('revenueGrowth')
    fwd_pe = info.get('forwardPE') or info.get('trailingPE')
    ev_ebitda = info.get('enterpriseToEbitda')
    roe = info.get('returnOnEquity')
    peg = info.get('pegRatio')
    profit_margin = info.get('profitMargins')
    fcf_yield_ttm = calculate_fcf_yield(ticker, info)

    history["Croit. CA."].append(clean_val(rev_growth * 100 if rev_growth is not None else None, "{:+.1f}%"))
    history["Marge Net %"].append(clean_val(profit_margin * 100 if profit_margin is not None else None, "{:.1f}%"))
    history["Fwd P/E"].append(clean_val(fwd_pe, "{:.1f}x"))
    history["EV/EBITDA"].append(clean_val(ev_ebitda, "{:.1f}x"))
    history["ROE"].append(clean_val(roe * 100 if roe is not None else None, "{:.1f}%"))
    history["PEG"].append(clean_val(peg, "{:.2f}"))
    history["FCF Yield %"].append(clean_val(fcf_yield_ttm, "{:.1f}%"))

    try:
        fin = getattr(ticker, 'income_stmt', None)
        if fin is None or fin.empty:
            fin = ticker.financials

        bs = getattr(ticker, 'balance_sheet', None)
        cf = getattr(ticker, 'cashflow', None)

        if fin is not None and not fin.empty:
            cols = list(fin.columns)
            sorted_cols = sorted(cols, key=lambda c: c.year if hasattr(c, "year") else int(str(c)[:4]), reverse=True)

            data_by_year = {}
            for col in sorted_cols:
                yr = col.year if hasattr(col, "year") else int(str(col)[:4])

                rev = get_financial_item(fin, ['Total Revenue', 'Operating Revenue', 'Revenue'], col)
                net_inc = get_financial_item(fin, ['Net Income', 'Net Income Common Stockholders', 'Net Income From Continuing Operation Net Minority Interest'], col)
                equity = get_financial_item(bs, ['Stockholders Equity', 'Total Stockholder Equity', 'Common Stock Equity'], col)
                
                ocf = get_financial_item(cf, ['Operating Cash Flow', 'Total Cash From Operating Activities'], col)
                capex = get_financial_item(cf, ['Capital Expenditure', 'Capital Expenditures'], col)
                fcf_val = None
                if ocf is not None and capex is not None:
                    fcf_val = ocf + capex

                data_by_year[yr] = {
                    "revenue": rev,
                    "net_income": net_inc,
                    "equity": equity,
                    "fcf": fcf_val
                }

            past_years = [y for y in sorted(data_by_year.keys(), reverse=True) if y < current_year]

            for yr in past_years[:4]:
                years_labels.append(str(yr))
                item = data_by_year[yr]

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

                if item["revenue"] and item["net_income"] and item["revenue"] > 0:
                    margin = (item["net_income"] / item["revenue"]) * 100
                    history["Marge Net %"].append(clean_val(margin, "{:.1f}%"))
                else:
                    history["Marge Net %"].append("N/A")

                if item["net_income"] and prev_yr in data_by_year and data_by_year[prev_yr]["equity"] and item["equity"]:
                    eq_end = item["equity"]
                    eq_start = data_by_year[prev_yr]["equity"]
                    avg_equity = (eq_end + eq_start) / 2.0
                    if avg_equity > 0:
                        roe_val = (item["net_income"] / avg_equity) * 100
                        history["ROE"].append(clean_val(roe_val, "{:.1f}%"))
                    else:
                        history["ROE"].append("N/A")
                elif item["net_income"] and item["equity"] and item["equity"] > 0:
                    roe_val = (item["net_income"] / item["equity"]) * 100
                    history["ROE"].append(clean_val(roe_val, "{:.1f}%"))
                else:
                    history["ROE"].append("N/A")

                mcap = info.get('marketCap')
                if item["fcf"] is not None and mcap and mcap > 0:
                    fy = (item["fcf"] / mcap) * 100
                    history["FCF Yield %"].append(clean_val(fy, "{:.1f}%"))
                else:
                    history["FCF Yield %"].append("N/A")

                history["Fwd P/E"].append("N/A")
                history["EV/EBITDA"].append("N/A")
                history["PEG"].append("N/A")

    except Exception as e:
        print(f"    ⚠️ Erreur données annuelles : {e}")

    return years_labels, history

# ==============================================================================
# PUBLICATIONS MACRO (FED, CPI, CORE CPI, PCE, PPI) - TOUJOURS AFFICHÉES
# ==============================================================================
# Dates officielles : BLS (CPI, PPI), BEA (PCE), Federal Reserve (FOMC).
# Format : (date de publication "AAAA-MM-JJ", mois de référence "AAAA-MM").
# Pour le FOMC, la date est celle de la décision (2e jour de la réunion).
# ➜ À compléter chaque année quand les agences publient leur nouveau calendrier.
MACRO_PAST_DAYS = 30   # même règle que les résultats d'entreprises : 30 jours d'historique
NY_TZ = ZoneInfo("America/New_York")
MACRO_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; RZInvestBot/1.0)"}

# Résultats (Results) : séries publiques FRED, sans clé API
FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}&cosd=2024-01-01"
# Attentes (Expected) : calendriers économiques (Finnhub si ton plan l'autorise, sinon flux Forex Factory)
FINNHUB_ECON_URL = "https://finnhub.io/api/v1/calendar/economic"
FF_CALENDAR_URLS = [
    "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
    "https://nfs.faireconomy.media/ff_calendar_nextweek.json",
]

FOMC_RELEASES = [
    ("2026-01-28", None), ("2026-03-18", None), ("2026-04-29", None), ("2026-06-17", None),
    ("2026-07-29", None), ("2026-09-16", None), ("2026-10-28", None), ("2026-12-09", None),
]

CPI_RELEASES = [
    ("2026-01-13", "2025-12"), ("2026-02-13", "2026-01"), ("2026-03-11", "2026-02"),
    ("2026-04-10", "2026-03"), ("2026-05-12", "2026-04"), ("2026-06-10", "2026-05"),
    ("2026-07-14", "2026-06"), ("2026-08-12", "2026-07"), ("2026-09-11", "2026-08"),
    ("2026-10-14", "2026-09"), ("2026-11-10", "2026-10"), ("2026-12-10", "2026-11"),
]

PPI_RELEASES = [
    ("2026-01-14", "2025-11"), ("2026-01-30", "2025-12"), ("2026-02-27", "2026-01"),
    ("2026-03-18", "2026-02"), ("2026-04-14", "2026-03"), ("2026-05-13", "2026-04"),
    ("2026-06-11", "2026-05"), ("2026-07-15", "2026-06"), ("2026-08-13", "2026-07"),
    ("2026-09-10", "2026-08"), ("2026-10-15", "2026-09"), ("2026-11-13", "2026-10"),
    ("2026-12-15", "2026-11"),
]

PCE_RELEASES = [
    ("2026-02-20", "2025-12"), ("2026-03-13", "2026-01"), ("2026-04-09", "2026-02"),
    ("2026-04-30", "2026-03"), ("2026-05-28", "2026-04"), ("2026-06-25", "2026-05"),
    ("2026-07-30", "2026-06"), ("2026-08-26", "2026-07"), ("2026-09-30", "2026-08"),
    ("2026-10-29", "2026-09"), ("2026-11-25", "2026-10"),
    # Décembre 2026 (données de novembre) : date BEA à ajouter dès qu'elle est confirmée
]

# "match" = regex (fullmatch, minuscules) appliquée au titre de l'événement dans les calendriers externes.
# "series" = série FRED utilisée pour calculer le résultat (NSA pour les variations annuelles CPI/PPI, comme le BLS).
MACRO_EVENTS = [
    {
        "key": "FOMC", "name": "Réunion FED (FOMC)", "icon": "🏛️", "time_et": (14, 0),
        "link": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
        "releases": FOMC_RELEASES,
        "metrics": [
            {"label": "Taux directeur (fourchette)", "kind": "fed",
             "match": r"federal funds rate|fed interest rate decision|interest rate decision"},
        ],
    },
    {
        "key": "CPI", "name": "CPI (US)", "icon": "🛒", "time_et": (8, 30),
        "link": "https://www.bls.gov/cpi/", "releases": CPI_RELEASES,
        "metrics": [
            {"label": "CPI YoY", "kind": "yoy", "series": "CPIAUCNS",
             "match": r"cpi y/y|cpi yoy|inflation rate yoy"},
            {"label": "CPI MoM", "kind": "mom", "series": "CPIAUCSL",
             "match": r"cpi m/m|cpi mom|inflation rate mom"},
        ],
    },
    {
        "key": "CORE_CPI", "name": "Core CPI (US)", "icon": "🎯", "time_et": (8, 30),
        "link": "https://www.bls.gov/cpi/", "releases": CPI_RELEASES,
        "metrics": [
            {"label": "Core CPI YoY", "kind": "yoy", "series": "CPILFENS",
             "match": r"core cpi y/y|core cpi yoy|core inflation rate yoy"},
            {"label": "Core CPI MoM", "kind": "mom", "series": "CPILFESL",
             "match": r"core cpi m/m|core cpi mom|core inflation rate mom"},
        ],
    },
    {
        "key": "PCE", "name": "PCE (US)", "icon": "💳", "time_et": (8, 30),
        "link": "https://www.bea.gov/data/personal-consumption-expenditures-price-index",
        "releases": PCE_RELEASES,
        "metrics": [
            {"label": "PCE YoY", "kind": "yoy", "series": "PCEPI",
             "match": r"pce price index y/y|pce price index yoy|pce prices? yoy|pce y/y"},
            {"label": "PCE MoM", "kind": "mom", "series": "PCEPI",
             "match": r"pce price index m/m|pce price index mom|pce prices? mom|pce m/m"},
            {"label": "Core PCE YoY", "kind": "yoy", "series": "PCEPILFE",
             "match": r"core pce price index y/y|core pce price index yoy|core pce prices? yoy|core pce y/y"},
            {"label": "Core PCE MoM", "kind": "mom", "series": "PCEPILFE",
             "match": r"core pce price index m/m|core pce price index mom|core pce prices? mom|core pce m/m"},
        ],
    },
    {
        "key": "PPI", "name": "PPI (US)", "icon": "🏭", "time_et": (8, 30),
        "link": "https://www.bls.gov/ppi/", "releases": PPI_RELEASES,
        "metrics": [
            {"label": "PPI YoY", "kind": "yoy", "series": "WPUFD4",
             "match": r"ppi y/y|ppi yoy|producer price index yoy"},
            {"label": "PPI MoM", "kind": "mom", "series": "PPIFIS",
             "match": r"ppi m/m|ppi mom|producer price index mom"},
        ],
    },
]

def _to_float(val):
    """Convertit '0.3%', 0.3, '3.75%' ... en float (None si vide ou illisible)."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return None if math.isnan(val) else float(val)
    m = re.search(r"-?\d+(?:\.\d+)?", str(val).replace(",", "."))
    return float(m.group()) if m else None

def format_macro_value(kind, value):
    """Formate une valeur macro pour l'affichage."""
    if value is None:
        return None
    if kind == "fed":
        # La fourchette de la Fed fait toujours 25 points de base : on affiche borne basse – borne haute
        return f"{value - 0.25:.2f}–{value:.2f}%"
    value = round(value, 1)
    if value == 0:
        value = 0.0  # évite "-0.0%"
    return f"{value:+.1f}%"

def fetch_fred_series(series, cache):
    """Télécharge une série FRED (CSV public, sans clé) -> {'AAAA-MM-JJ': valeur}."""
    if series in cache:
        return cache[series]
    data = {}
    try:
        resp = requests.get(FRED_CSV_URL.format(series=series), headers=MACRO_HEADERS, timeout=20)
        resp.raise_for_status()
        for line in resp.text.strip().splitlines()[1:]:
            parts = line.split(",")
            if len(parts) < 2:
                continue
            d, v = parts[0].strip(), parts[1].strip()
            if not v or v == ".":
                continue
            try:
                data[d] = float(v)
            except ValueError:
                continue
    except Exception as e:
        print(f"    ⚠️ Erreur FRED ({series}): {e}")
    cache[series] = data
    return data

def compute_macro_actual(metric, ref_month, release_date, cache):
    """Calcule le résultat publié (YoY / MoM / taux Fed) à partir des séries FRED."""
    kind = metric["kind"]

    if kind == "fed":
        upper = fetch_fred_series("DFEDTARU", cache)
        lower = fetch_fred_series("DFEDTARL", cache)
        # La Fed annonce à 14h00 ET pour une application le lendemain : on lit la fourchette en vigueur après la décision
        for offset in range(1, 5):
            d = (release_date + timedelta(days=offset)).strftime("%Y-%m-%d")
            if d in upper and d in lower:
                return format_macro_value("fed", upper[d])
        return None

    if not ref_month:
        return None
    values = fetch_fred_series(metric["series"], cache)
    y, m = int(ref_month[:4]), int(ref_month[5:7])
    current = values.get(f"{y}-{m:02d}-01")
    if current is None:
        return None
    if kind == "mom":
        py, pm = (y, m - 1) if m > 1 else (y - 1, 12)
        base = values.get(f"{py}-{pm:02d}-01")
    else:
        base = values.get(f"{y - 1}-{m:02d}-01")
    if not base:
        return None
    return format_macro_value(kind, (current / base - 1) * 100)

def fetch_external_macro_calendar():
    """Calendriers économiques US (Finnhub puis Forex Factory) -> liste normalisée {date, title, expected, actual}."""
    events = []

    # 1) Finnhub (si la clé existe ET que le plan donne accès au calendrier économique)
    finnhub_key = os.environ.get("FINNHUB_API_KEY")
    if finnhub_key:
        try:
            resp = requests.get(FINNHUB_ECON_URL, params={"token": finnhub_key}, headers=MACRO_HEADERS, timeout=20)
            if resp.status_code in (401, 403):
                print("    ℹ️ Calendrier économique Finnhub non accessible avec cette clé (plan premium) : ignoré")
            else:
                resp.raise_for_status()
                for it in (resp.json().get("economicCalendar") or []):
                    if str(it.get("country", "")).upper() != "US":
                        continue
                    t = str(it.get("time") or "")
                    try:
                        dt_utc = datetime.strptime(t[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=ZoneInfo("UTC"))
                        d = dt_utc.astimezone(NY_TZ).strftime("%Y-%m-%d")
                    except Exception:
                        d = t[:10]
                    events.append({
                        "date": d,
                        "title": str(it.get("event") or "").strip().lower(),
                        "expected": _to_float(it.get("estimate")),
                        "actual": _to_float(it.get("actual")),
                    })
        except Exception as e:
            print(f"    ⚠️ Erreur calendrier Finnhub: {e}")

    # 2) Forex Factory (semaine en cours + suivante, gratuit)
    for url in FF_CALENDAR_URLS:
        try:
            resp = requests.get(url, headers=MACRO_HEADERS, timeout=20)
            resp.raise_for_status()
            for it in resp.json():
                if it.get("country") != "USD":
                    continue
                events.append({
                    "date": str(it.get("date") or "")[:10],   # déjà exprimée en heure de New York
                    "title": str(it.get("title") or "").strip().lower(),
                    "expected": _to_float(it.get("forecast")),
                    "actual": _to_float(it.get("actual")),
                })
        except Exception as e:
            print(f"    ⚠️ Erreur calendrier Forex Factory ({url.rsplit('/', 1)[-1]}): {e}")

    return events

def lookup_external(external, date_str, pattern):
    """Cherche dans les calendriers externes l'événement correspondant (même jour + titre)."""
    first_match = None
    for e in external:
        if e["date"] != date_str or not re.fullmatch(pattern, e["title"]):
            continue
        if e["expected"] is not None:
            return e
        if first_match is None:
            first_match = e
    return first_match

def build_macro_events(now_be, prev_macro, belgium_tz):
    """Construit la liste des publications macro (passées sur 30 jours + à venir) avec Expected / Results."""
    now_date = now_be.date()
    cutoff_date = now_date - timedelta(days=MACRO_PAST_DAYS)

    # Valeurs déjà connues (data.json précédent) : on ne perd jamais un Expected / Results déjà capturé
    prev_index = {}
    for ev in (prev_macro or []):
        prev_index[(ev.get("key"), ev.get("date"))] = {m.get("label"): m for m in ev.get("metrics", [])}

    fred_cache = {}
    external = fetch_external_macro_calendar()
    events = []

    for cfg in MACRO_EVENTS:
        for date_str, ref_month in cfg["releases"]:
            rel_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            if rel_date < cutoff_date:
                continue

            hh, mm = cfg["time_et"]
            release_dt = datetime(rel_date.year, rel_date.month, rel_date.day, hh, mm, tzinfo=NY_TZ).astimezone(belgium_tz)
            released = now_be >= release_dt
            old_metrics = prev_index.get((cfg["key"], date_str), {})

            metrics_out = []
            for metric in cfg["metrics"]:
                old = old_metrics.get(metric["label"], {})
                hit = lookup_external(external, date_str, metric["match"])

                # EXPECTED : mis à jour jusqu'à la publication, figé ensuite
                expected = old.get("expected")
                if hit and hit["expected"] is not None and (not released or expected is None):
                    expected = format_macro_value(metric["kind"], hit["expected"])

                # RESULTS : figé dès qu'il est capturé (1re valeur publiée)
                actual = old.get("actual")
                if actual is None and released:
                    actual = compute_macro_actual(metric, ref_month, rel_date, fred_cache)
                    if actual is None and hit and hit["actual"] is not None:
                        actual = format_macro_value(metric["kind"], hit["actual"])

                metrics_out.append({"label": metric["label"], "expected": expected, "actual": actual})

            has_actual = any(m["actual"] is not None for m in metrics_out)
            events.append({
                "key": cfg["key"],
                "name": cfg["name"],
                "icon": cfg["icon"],
                "date": date_str,
                "date_formatted": rel_date.strftime("%d/%m/%Y"),
                "time_be": release_dt.strftime("%H:%M"),
                "is_past": bool(released or has_actual),
                "ref_month": f"{ref_month[5:7]}/{ref_month[:4]}" if ref_month else None,
                "metrics": metrics_out,
                "link": cfg["link"],
            })

    events.sort(key=lambda x: (x["date"], x["time_be"]))
    return events

def generate_dashboard_data():
    all_targets = []
    category_map = {}

    for t in REITS_TICKERS:
        all_targets.append(t)
        category_map[t] = "reit"

    for t in STOCKS_TICKERS:
        all_targets.append(t)
        category_map[t] = "stock"

    for t in CRYPTO_TICKERS:
        all_targets.append(t)
        category_map[t] = "crypto"

    prices_data = []
    news_data = []
    fundamentals_data = []
    all_earnings_data = []

    # Publications macro déjà présentes dans le data.json précédent
    prev_macro = []
    try:
        with open("data.json", "r", encoding="utf-8") as f:
            prev_macro = json.load(f).get("macro", []) or []
    except Exception:
        prev_macro = []

    belgium_tz = ZoneInfo("Europe/Brussels")
    now_be = datetime.now(belgium_tz)
    now_ts = now_be.timestamp()
    cutoff_ts = now_ts - (NEWS_MAX_AGE_DAYS * 24 * 3600)

    print(f"📊 Téléchargement groupé pour {len(all_targets)} tickers...")
    
    batch_hist = {}
    try:
        download_data = yf.download(all_targets, period="5y", interval="1d", group_by="ticker", auto_adjust=False, progress=False)
        for symbol in all_targets:
            if len(all_targets) > 1:
                if symbol in download_data and 'Close' in download_data[symbol]:
                    batch_hist[symbol] = download_data[symbol]['Close'].dropna()
            else:
                if 'Close' in download_data:
                    batch_hist[symbol] = download_data['Close'].dropna()
    except Exception as e:
        print(f"⚠️ Erreur lors du téléchargement groupé yf.download: {e}")

    tickers_objs = yf.Tickers(" ".join(all_targets))

    for symbol in all_targets:
        try:
            cat = category_map[symbol]
            print(f"   ➜ Traitement [{cat.upper()}] : {symbol}")
            ticker = tickers_objs.tickers.get(symbol) or yf.Ticker(symbol)
            info = {}
            try:
                info = ticker.info or {}
            except Exception:
                pass

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

            if cat == "crypto":
                currency = "$"
            else:
                currency = "€" if any(symbol.endswith(ext) for ext in [".BR", ".BE", ".PA", ".AS"]) else "$"

            sma200_str, sma200_pct, is_under = check_200_weekly_sma_from_hist(hist_close, price)
            rsi14_w = calculate_rsi14_weekly(hist_close)
            ath_52w_pct = calculate_ath_52w_pct(hist_close, price)
            
            # MA Cross & MACD-W
            ma_cross_str, ma_cross_pct, ma_cross_type = calculate_ma_cross_weekly(hist_close)
            macd_w_str, macd_w_type = calculate_macd_weekly(hist_close)
            fcf_yield_val = calculate_fcf_yield(ticker, info)
            
            next_pub_str, ticker_pubs = get_all_earnings_dates(ticker, symbol, belgium_tz, cat)
            all_earnings_data.extend(ticker_pubs)

            prices_data.append({
                "ticker": symbol,
                "category": cat,
                "price": round(price, 2) if price else 0.0,
                "change": round(change_pct, 2) if change_pct else 0.0,
                "currency": currency,
                "sma200": sma200_str,
                "sma200_pct": sma200_pct,
                "is_under": is_under,
                "rsi14_weekly": rsi14_w,
                "ath_52w_pct": ath_52w_pct,
                "ma_cross_str": ma_cross_str,
                "ma_cross_pct": ma_cross_pct,
                "ma_cross_type": ma_cross_type,
                "macd_w_str": macd_w_str,
                "macd_w_type": macd_w_type,
                "fcf_yield": fcf_yield_val,
                "earnings": next_pub_str
            })

            # NEWS (Yahoo Finance + Google News, fenêtre de NEWS_MAX_AGE_DAYS jours)
            try:
                ticker_news = build_ticker_news(symbol, cat, ticker, info, cutoff_ts, belgium_tz)
                news_data.extend(ticker_news)
                print(f"      📰 {len(ticker_news)} news")
            except Exception as e:
                print(f"    ⚠️ Erreur news sur {symbol}: {e}")

            # HISTORIQUE ANNUEL / FONDAMENTAUX
            if cat != "crypto":
                years, annual_history = get_annual_history(ticker, info, cat)

                rev_growth = info.get('revenueGrowth')
                fwd_pe = info.get('forwardPE') or info.get('trailingPE')
                ev_ebitda = info.get('enterpriseToEbitda')
                roe = info.get('returnOnEquity')
                peg = info.get('pegRatio')
                profit_margin = info.get('profitMargins')

                fundamentals_data.append({
                    "ticker": symbol,
                    "category": cat,
                    "rev_growth": clean_val(rev_growth * 100 if rev_growth is not None else None, "{:+.1f}%"),
                    "pe": clean_val(fwd_pe, "{:.1f}x"),
                    "ev": clean_val(ev_ebitda, "{:.1f}x"),
                    "roe": clean_val(roe * 100 if roe is not None else None, "{:.1f}%"),
                    "peg": clean_val(peg, "{:.2f}"),
                    "net_margin": clean_val(profit_margin * 100 if profit_margin is not None else None, "{:.1f}%"),
                    "fcf_yield": clean_val(fcf_yield_val, "{:.1f}%"),
                    "quarters": years,
                    "history": annual_history
                })

        except Exception as e:
            print(f"⚠️ Erreur globale sur {symbol}: {e}")

    all_earnings_data.sort(key=lambda x: x["date"])

    # PUBLICATIONS MACRO (FED, CPI, CORE CPI, PCE, PPI) - indépendantes des catégories / tickers
    try:
        print("🏛️ Calcul des publications macro (FED, CPI, Core CPI, PCE, PPI)...")
        macro_data = build_macro_events(now_be, prev_macro, belgium_tz)
        print(f"   ➜ {len(macro_data)} publications macro")
    except Exception as e:
        print(f"⚠️ Erreur publications macro: {e}")
        macro_data = prev_macro

    output = {
        "updated_at": now_be.strftime("%d/%m/%Y à %H:%M"),
        "prices": prices_data,
        "news": news_data,
        "fundamentals": fundamentals_data,
        "earnings": all_earnings_data,
        "macro": macro_data
    }

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✅ data.json généré avec succès avec toutes les données des {len(all_targets)} tickers !")

if __name__ == "__main__":
    generate_dashboard_data()
