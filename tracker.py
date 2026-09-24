import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
import json
import numpy as np
import pytz

# Liste des tickers par catégorie
tickers_by_cat = {
    'stock': ["GOOGL", "AMZN", "MSFT", "META", "BABA", "ASML", "SYK", "AYA.TO"],
    'reit': ["CPINV.BR", "HOMI.BR", "O", "VICI", "WPC"],
    'crypto': ["BTC-USD", "ETH-USD", "SOL-USD", "SUI20947-USD", "HYPE32196-USD"]
}

# Fusion des tickers
all_tickers = []
for cat, t_list in tickers_by_cat.items():
    all_tickers.extend(t_list)

print("Téléchargement des données de marché...")
# Téléchargement groupé de l'historique sur 5 ans (suffisant pour la SMA 200W)
df_hist = yf.download(all_tickers, period="5y", interval="1d", group_by='ticker', auto_adjust=True)

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

brussels_tz = pytz.timezone('Europe/Brussels')
now = datetime.now(brussels_tz)

final_data = []

for cat, t_list in tickers_by_cat.items():
    for ticker in t_list:
        print(f"Traitement de {ticker}...")
        
        # Récupération des données historiques du ticker
        if len(all_tickers) > 1:
            t_data = df_hist[ticker].dropna(how='all')
        else:
            t_data = df_hist.dropna(how='all')
            
        if t_data.empty:
            print(f"Aucune donnée pour {ticker}")
            continue

        close_prices = t_data['Close']
        current_price = close_prices.iloc[-1]
        
        # Variation du jour
        if len(close_prices) > 1:
            prev_price = close_prices.iloc[-2]
            day_change_pct = ((current_price - prev_price) / prev_price) * 100
        else:
            day_change_pct = 0.0

        # Données Hebdomadaires (W-FRI) pour SMA 200 et RSI 14
        weekly_close = close_prices.resample('W-FRI').last().dropna()
        
        # SMA 200W
        if len(weekly_close) >= 200:
            sma200_w = weekly_close.rolling(window=200).mean().iloc[-1]
            diff_sma200_pct = ((current_price - sma200_w) / sma200_w) * 100
        else:
            sma200_w = None
            diff_sma200_pct = None

        # RSI 14W
        if len(weekly_close) >= 15:
            rsi_series = calculate_rsi(weekly_close, period=14)
            rsi_w = rsi_series.iloc[-1]
        else:
            rsi_w = None

        # ATH 52 Semaines
        one_year_ago = close_prices.index[-1] - timedelta(days=365)
        last_52w = close_prices[close_prices.index >= one_year_ago]
        ath_52w = last_52w.max() if not last_52w.empty else current_price
        diff_ath_pct = ((current_price - ath_52w) / ath_52w) * 100

        # Infos fondamentales
        yf_obj = yf.Ticker(ticker)
        info = yf_obj.info if hasattr(yf_obj, 'info') else {}

        currency = "€" if ticker.endswith(".BR") else "$"

        # Ratios
        fwd_pe = info.get('forwardPE')
        ev_ebitda = info.get('enterpriseToEbitda')
        peg_ratio = info.get('pegRatio')
        roe = info.get('returnOnEquity')
        if roe is not None:
            roe = roe * 100  # Conversion en %

        # Historique Financier (Chiffre d'affaires & Marge nette)
        financials_hist = []
        try:
            fin = yf_obj.financials
            if fin is not None and not fin.empty:
                cols = fin.columns[:4]  # 4 dernières années
                for col in cols:
                    year_str = str(col.year) if hasattr(col, 'year') else str(col)[:4]
                    rev = fin.loc['Total Revenue', col] if 'Total Revenue' in fin.index else None
                    net_inc = fin.loc['Net Income', col] if 'Net Income' in fin.index else None
                    
                    margin = (net_inc / rev * 100) if (rev and net_inc and rev != 0) else None
                    
                    financials_hist.append({
                        'year': year_str,
                        'revenue': float(rev) if rev and not np.isnan(rev) else None,
                        'net_margin': float(margin) if margin and not np.isnan(margin) else None
                    })
        except Exception as e:
            print(f"Erreur lors de la récupération des financials pour {ticker}: {e}")

        # Calendrier des Earnings (Pub.)
        earnings_dates = []
        try:
            calendar = yf_obj.calendar
            if calendar is not None:
                if isinstance(calendar, dict) and 'Earnings Date' in calendar:
                    earnings_dates = [d.strftime('%Y-%m-%d') for d in calendar['Earnings Date']]
                elif isinstance(calendar, pd.DataFrame) and 'Earnings Date' in calendar.index:
                    earnings_dates = [d.strftime('%Y-%m-%d') for d in calendar.loc['Earnings Date']]
        except Exception as e:
             print(f"Erreur lors de la récupération du calendrier pour {ticker}: {e}")

        final_data.append({
            'ticker': ticker,
            'category': cat,
            'currency': currency,
            'price': float(current_price),
            'day_change_pct': float(day_change_pct),
            'sma200_w': float(sma200_w) if sma200_w and not np.isnan(sma200_w) else None,
            'diff_sma200_pct': float(diff_sma200_pct) if diff_sma200_pct and not np.isnan(diff_sma200_pct) else None,
            'rsi_w': float(rsi_w) if rsi_w and not np.isnan(rsi_w) else None,
            'ath_52w': float(ath_52w),
            'diff_ath_pct': float(diff_ath_pct),
            'fwd_pe': float(fwd_pe) if fwd_pe and not np.isnan(fwd_pe) else None,
            'ev_ebitda': float(ev_ebitda) if ev_ebitda and not np.isnan(ev_ebitda) else None,
            'peg_ratio': float(peg_ratio) if peg_ratio and not np.isnan(peg_ratio) else None,
            'roe': float(roe) if roe and not np.isnan(roe) else None,
            'financials_hist': financials_hist,
            'earnings_dates': earnings_dates
        })

output_json = {
    'updated_at': now.strftime('%d/%m/%Y à %H:%M'),
    'data': final_data
}

with open('data.json', 'w', encoding='utf-8') as f:
    json.dump(output_json, f, ensure_ascii=False, indent=2)

print("Export data.json terminé avec succès !")
