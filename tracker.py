from datetime import datetime, timedelta
import json
import os
import sys
import time
import pandas as pd
import requests
import yfinance as yf
from playwright.sync_api import sync_playwright

TICKERS = [
    "AED.BR",
    "CPINV.BE",
    "HOMI.BR",
    "RET.BR",
    "AMKR",
    "ASML.AS",   
    "AVGO",
    "AYA.TO",
    "BKNG",
    "CPRT",
    "CSW",
    "GEV",
    "GOOG",
    "ISRG",
    "META",
    "MC.PA",
    "MSFT",
    "NVDA",
    "ONON",
    "SPCX",
    "SPGI",
    "SU.PA",
    "TTE.PA",
    "TSLA",
    "VRSN", 
]

MACRO_EVENTS = {
    "FED (Réunion)": "2026-10-28",
    "CPI US": "2026-10-14",
    "Core PCE": "2026-09-30",
    "NFP": "2026-10-02",
}

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
CACHE_FILE = "sent_news.json"

IMPORTANT_KEYWORDS = [
    "result", "earnings", "revenue", "profit", "margin", "guidance", "dividend",
    "fcf", "cash flow", "quarter", "q1", "q2", "q3", "q4", "bénéfice",
    "chiffre d'affaires", "résultat", "dividende", "buyout", "acquisition",
    "merger", "takeover", "sec", "investigation", "lawsuit", "ceo", "cfo",
    "layoff", "restructuring", "rachat", "procès", "démission", "licenciement",
    "upgrade", "downgrade", "record", "plunge", "surge", "crash", "chute", "envolée",
]


def send_telegram(message):
    """Envoie le message formaté en Markdown sur Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    response = requests.post(
        url,
        json={
            "chat_id": CHAT_ID,
            "text": message,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        },
    )
    return response.ok


def send_telegram_photo(photo_path, caption=""):
    """Envoie une image stockée sur le serveur vers Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    with open(photo_path, 'rb') as photo:
        payload = {'chat_id': CHAT_ID, 'caption': caption, 'parse_mode': 'Markdown'}
        files = {'photo': photo}
        response = requests.post(url, data=payload, files=files)
    return response.ok


def load_sent_news():
    """Charge l'historique des news envoyées depuis un fichier JSON."""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_sent_news(data):
    """Sauvegarde l'historique des news envoyées."""
    with open(CACHE_FILE, "w") as f:
        json.dump(data, f, indent=2)


def check_200_weekly_sma(ticker, current_price):
    """Calcule si le prix est au-dessus ou sous la Moyenne Mobile 200 Semaines."""
    try:
        hist = ticker.history(period="5y", interval="1wk")
        if len(hist) >= 200:
            sma_200 = hist["Close"].tail(200).mean()
            if current_price < sma_200:
                return "Under 🔥"
            else:
                return "Above"
    except Exception:
        pass
    return "N/A"


def get_next_earnings_date(ticker):
    """Récupère la prochaine date de publication d'une entreprise."""
    try:
        calendar = ticker.calendar
        now = datetime.now().date()
        target_date = None

        if isinstance(calendar, dict) and "Earnings Date" in calendar:
            for d in calendar["Earnings Date"]:
                d_date = d.date() if isinstance(d, datetime) else d
                if d_date >= now:
                    target_date = d_date
                    break

        if not target_date:
            earnings_epoch = ticker.info.get("earningsTimestamp") or ticker.info.get(
                "earningsTimestampStart"
            )
            if earnings_epoch:
                e_date = datetime.fromtimestamp(earnings_epoch).date()
                if e_date >= now:
                    target_date = e_date

        if target_date:
            formatted_date = target_date.strftime("%d/%m/%Y")
            days_diff = (target_date - now).days
            if 0 <= days_diff <= 5:
                return f"{formatted_date} 🔥"
            return formatted_date

    except Exception:
        pass

    return "À déterminer"


def format_event_date(date_str):
    """Formate la date macroéconomique et ajoute l'icône 🔥 si elle a lieu dans les 5 jours."""
    try:
        event_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        now = datetime.now().date()
        formatted_date = event_date.strftime("%d/%m/%Y")
        days_diff = (event_date - now).days

        if 0 <= days_diff <= 5:
            return f"{formatted_date} 🔥"
        return formatted_date
    except Exception:
        return date_str


def send_prices():
    """1. Prix, Evolution, 200 W-SMA & Prochaines publications."""
    header = "📈 **SUIVI DES COURS & DATES**\n"
    header += f"📅 `{datetime.now().strftime('%d/%m/%Y - %H:%M')}`\n\n"

    header += "🏛️ **CALENDRIER MACROÉCONOMIQUE**\n"
    for event_name, event_date_str in MACRO_EVENTS.items():
        formatted_d = format_event_date(event_date_str)
        header += f"├ **{event_name}** : `{formatted_d}`\n"
    header += "\n" + "─" * 20 + "\n\n"

    current_message = header
    batch_count = 0

    for symbol in TICKERS:
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info

            price = (
                info.get("currentPrice")
                or info.get("regularMarketPrice")
                or info.get("ask")
                or info.get("bid")
            )

            if not price or price == 0:
                hist = ticker.history(period="5d")
                if not hist.empty:
                    price = float(hist["Close"].iloc[-1])
                else:
                    price = 0.0

            prev_close = info.get("previousClose") or price
            if prev_close > 0 and price > 0:
                change_pct = ((price - prev_close) / prev_close) * 100
            else:
                change_pct = 0.0

            currency = info.get("currency", "USD")
            if any(symbol.endswith(ext) for ext in [".BR", ".BE", ".PA"]) or currency == "EUR":
                curr_symbol = "€"
            else:
                curr_symbol = "$"

            sma_status = check_200_weekly_sma(ticker, price)
            next_earnings = get_next_earnings_date(ticker)

            sma_display = (
                f"`{sma_status}`" if "Under" not in sma_status else f"**{sma_status}**"
            )

            status_emoji = "🟢" if change_pct >= 0 else "🔴"

            item_text = (
                f"{status_emoji} **{symbol}** : `{price:.2f} {curr_symbol}`"
                f" ({change_pct:+.2f}%)\n"
            )
            item_text += f"├ **200 W-SMA** : {sma_display}\n"
            item_text += f"└ 📅 **Prochaine pub.** : `{next_earnings}`\n\n"

            current_message += item_text
            batch_count += 1

            if batch_count >= 10:
                send_telegram(current_message)
                current_message = ""
                batch_count = 0
                time.sleep(1)

        except Exception as e:
            current_message += f"❌ Erreur sur {symbol}: {str(e)}\n\n"

    if current_message:
        send_telegram(current_message)


def send_news():
    """2. News récentes : regroupe les actualités par blocs pour limiter les messages."""
    sent_cache = load_sent_news()
    now_ts = datetime.now().timestamp()

    cutoff_ts = now_ts - (72 * 3600 if datetime.now().weekday() == 0 else 24 * 3600)
    
    pending_articles = []

    for symbol in TICKERS:
        try:
            ticker = yf.Ticker(symbol)
            news_list = ticker.news or []

            for item in news_list:
                content = item.get("content", item)
                title = content.get("title") or item.get("title", "")
                summary = content.get("summary") or item.get("summary") or content.get("description") or ""
                pub_time = content.get("pubDate") or item.get("providerPublishTime", 0)

                if isinstance(pub_time, str):
                    try:
                        pub_time = datetime.fromisoformat(
                            pub_time.replace("Z", "+00:00")
                        ).timestamp()
                    except Exception:
                        pub_time = now_ts

                if pub_time < cutoff_ts:
                    continue

                link = None
                if "clickThroughUrl" in content and content["clickThroughUrl"]:
                    link = content["clickThroughUrl"].get("url")
                elif "canonicalUrl" in content and content["canonicalUrl"]:
                    link = content["canonicalUrl"].get("url")
                elif "link" in item:
                    link = item["link"]

                news_id = link or title

                if news_id in sent_cache:
                    continue

                title_lower = title.lower()
                summary_lower = summary.lower()
                is_important = any(kw in title_lower or kw in summary_lower for kw in IMPORTANT_KEYWORDS)

                if is_important:
                    # Construction du bloc texte d'un article
                    art_text = f"📰 **{symbol}** — *Actualité Majeure*\n"
                    art_text += f"📌 **{title}**\n"
                    if summary:
                        art_text += f"📝 {summary}\n"
                    if link:
                        art_text += f"🔗 [Lire l'article]({link})\n"
                    
                    pending_articles.append((news_id, art_text))

        except Exception:
            pass

    if not pending_articles:
        send_telegram("📰 **ACTUALITÉS** : Aucune nouvelle dépêche majeure récente.")
        return

    # Regroupement par paquets de 3 actualités par message
    BATCH_SIZE = 3
    for i in range(0, len(pending_articles), BATCH_SIZE):
        batch = pending_articles[i:i + BATCH_SIZE]
        
        # En-tête du message groupé
        message = f"📰 **REVUE DE PRESSE ({len(batch)} news)**\n\n"
        message += "\n─" * 15 + "\n\n"
        message += "\n\n".join([item[1] for item in batch])

        if send_telegram(message):
            # Marquer comme envoyées seulement si l'envoi a réussi
            for news_id, _ in batch:
                sent_cache[news_id] = now_ts
            time.sleep(1)

    save_sent_news(sent_cache)


def get_color_class(metric_type, val_str):
    """Détermine la couleur des badges en fonction des valeurs."""
    try:
        val = float(str(val_str).replace('%', '').replace('+', '').strip())
        if metric_type == 'pe':
            return 'bg-green' if val < 25 else ('bg-yellow' if val <= 50 else 'bg-red')
        elif metric_type == 'ev':
            return 'bg-green' if val < 15 else ('bg-yellow' if val <= 30 else 'bg-red')
        elif metric_type == 'peg':
            return 'bg-green' if val < 1.2 else ('bg-yellow' if val <= 2.2 else 'bg-red')
        elif metric_type == 'croit':
            return 'bg-green' if val >= 10 else ('bg-yellow' if val >= 0 else 'bg-red')
        elif metric_type in ['marge', 'roe']:
            return 'bg-green' if val >= 15 else ('bg-yellow' if val >= 5 else 'bg-red')
        elif metric_type == 'div':
            return 'bg-green' if val >= 3.0 else ('bg-yellow' if val >= 1.0 else '')
    except Exception:
        pass
    return ''


def generate_html_dashboard(df):
    """Génère l'image dashboard moderne HTML/CSS via Playwright."""
    date_str = datetime.now().strftime("%d/%m/%Y")

    def clean_num(val):
        try:
            return float(str(val).replace('%', '').replace('+', '').strip())
        except Exception:
            return None

    # Calculs pour les KPIs globaux
    croit_series = df['Croit. CA'].apply(clean_num).dropna()
    ev_series = df['EV/EBITDA'].apply(clean_num).dropna()
    marge_series = df['Marge N.'].apply(clean_num).dropna()
    roe_series = df['ROE'].apply(clean_num).dropna()
    div_series = df['Div.'].apply(clean_num).dropna()

    croit_mean = croit_series.mean() if not croit_series.empty else 0
    ev_mean = ev_series.median() if not ev_series.empty else 0
    marge_mean = marge_series.mean() if not marge_series.empty else 0
    roe_mean = roe_series.mean() if not roe_series.empty else 0
    div_mean = div_series.mean() if not div_series.empty else 0

    # Tri pour le Top ROE du bas
    roe_data = []
    for _, row in df.iterrows():
        val = clean_num(row['ROE'])
        if val is not None:
            roe_data.append((row['Ticker'], val))
    roe_data.sort(key=lambda x: x[1], reverse=True)
    top_roe = roe_data[:3]

    top_roe_html = ""
    for idx, (ticker, val) in enumerate(top_roe, 1):
        top_roe_html += f"""
        <div class="top-item">
            <span>{idx}. {ticker}</span>
            <span style="color:#34d399">{val:.1f}%</span>
        </div>
        """

    # Construction des lignes du tableau
    table_rows = ""
    for _, row in df.iterrows():
        table_rows += f"""
        <tr>
            <td class="ticker">{row['Ticker']}</td>
            <td><span class="badge {get_color_class('croit', row['Croit. CA'])}">{row['Croit. CA']}</span></td>
            <td><span class="badge {get_color_class('pe', row['Fwd P/E'])}">{row['Fwd P/E']}</span></td>
            <td><span class="badge {get_color_class('ev', row['EV/EBITDA'])}">{row['EV/EBITDA']}</span></td>
            <td><span class="badge {get_color_class('peg', row['PEG'])}">{row['PEG']}</span></td>
            <td><span class="badge {get_color_class('div', row['Div.'])}">{row['Div.']}</span></td>
            <td><span class="badge {get_color_class('roe', row['ROE'])}">{row['ROE']}</span></td>
            <td><span class="badge {get_color_class('marge', row['Marge N.'])}">{row['Marge N.']}</span></td>
        </tr>
        """

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
      <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ background-color: #06090e; color: #f8fafc; font-family: 'Inter', sans-serif; padding: 24px; width: 900px; }}
        .header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 12px; }}
        .title {{ font-size: 22px; font-weight: 800; color: #ffffff; letter-spacing: 0.5px; }}
        .subtitle {{ font-size: 11px; color: #64748b; text-transform: uppercase; letter-spacing: 1px; margin-top: 2px; }}
        .date-badge {{ background: #1e293b; color: #38bdf8; padding: 6px 12px; border-radius: 6px; font-size: 12px; font-weight: 700; border: 1px solid rgba(56, 189, 248, 0.2); }}
        .kpi-grid {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; margin-bottom: 20px; }}
        .kpi-card {{ background: rgba(15, 23, 42, 0.6); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 10px; padding: 12px; text-align: center; }}
        .kpi-title {{ font-size: 10px; color: #94a3b8; text-transform: uppercase; font-weight: 600; margin-bottom: 4px; }}
        .kpi-val {{ font-size: 16px; font-weight: 800; color: #34d399; }}
        .table-card {{ background: rgba(15, 23, 42, 0.8); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 12px; padding: 16px; margin-bottom: 20px; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th {{ color: #64748b; font-size: 10px; text-transform: uppercase; padding: 8px 4px; border-bottom: 1px solid rgba(255, 255, 255, 0.08); text-align: center; }}
        td {{ padding: 6px 4px; text-align: center; font-size: 12px; font-weight: 600; }}
        .ticker {{ text-align: left; color: #38bdf8; font-weight: 700; padding-left: 8px; }}
        .badge {{ padding: 3px 6px; border-radius: 4px; font-size: 11px; display: inline-block; width: 85%; color: #94a3b8; }}
        .bg-green {{ background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(52, 211, 153, 0.3); }}
        .bg-yellow {{ background: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid rgba(251, 191, 36, 0.3); }}
        .bg-red {{ background: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(248, 113, 113, 0.3); }}
        .bottom-grid {{ display: grid; grid-template-columns: 2fr 1fr; gap: 15px; }}
        .bottom-card {{ background: rgba(15, 23, 42, 0.6); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 10px; padding: 12px; }}
        .bottom-title {{ font-size: 11px; font-weight: 700; color: #38bdf8; margin-bottom: 8px; text-transform: uppercase; }}
        .top-item {{ display: flex; justify-content: space-between; font-size: 11px; padding: 4px 0; border-bottom: 1px solid rgba(255,255,255,0.03); font-weight: 600; }}
      </style>
    </head>
    <body>
      <div class="header">
        <div>
          <div class="title">BUREAU D'ANALYSE FONDAMENTALE</div>
          <div class="subtitle">Analyse Fondamentale des Valeurs En Portefeuille</div>
        </div>
        <div class="date-badge">{date_str}</div>
      </div>
      <div class="kpi-grid">
        <div class="kpi-card"><div class="kpi-title">Croissance CA</div><div class="kpi-val">+{croit_mean:.1f}%</div></div>
        <div class="kpi-card"><div class="kpi-title">EV/EBITDA Med.</div><div class="kpi-val" style="color:#fbbf24">{ev_mean:.1f}x</div></div>
        <div class="kpi-card"><div class="kpi-title">Marge Nette</div><div class="kpi-val">{marge_mean:.1f}%</div></div>
        <div class="kpi-card"><div class="kpi-title">ROE Moyen</div><div class="kpi-val">{roe_mean:.1f}%</div></div>
        <div class="kpi-card"><div class="kpi-title">Dividende Moy.</div><div class="kpi-val" style="color:#38bdf8">{div_mean:.2f}%</div></div>
      </div>
      <div class="table-card">
        <table>
          <thead>
            <tr>
              <th style="text-align:left; padding-left:8px;">Ticker</th>
              <th>Croit. CA</th><th>Fwd P/E</th><th>EV/EBITDA</th><th>PEG</th><th>Div.</th><th>ROE</th><th>Marge N.</th>
            </tr>
          </thead>
          <tbody>{table_rows}</tbody>
        </table>
      </div>
      <div class="bottom-grid">
        <div class="bottom-card">
          <div class="bottom-title">📌 POINTS CLÉS</div>
          <div style="font-size: 11px; color: #94a3b8; line-height: 1.6;">
            • <b>Avis global :</b> Vert = Niveaux attractifs / Jaune = Neutre / Rouge = Vigilance.<br>
            • <b>Immobilier / REITs :</b> Marge Nette et Croissance CA à interpréter avec précaution.<br>
            • <b>Mises à jour :</b> Rapport hebdomadaire exécuté automatiquement via GitHub Actions.
          </div>
        </div>
        <div class="bottom-card">
          <div class="bottom-title">🏆 TOP ROE</div>
          <div>{top_roe_html}</div>
        </div>
      </div>
    </body>
    </html>
    """

    image_filename = "fundamentals.png"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 930, "height": 1300})
        page.set_content(html_content)
        page.screenshot(path=image_filename, full_page=True)
        browser.close()

    return image_filename


def send_fundamentals():
    """3. Analyse Fondamentale : rendu propre avec Playwright."""
    data = []

    for symbol in TICKERS:
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info or {}

            rev_str, pe_str, ev_str, peg_str, div_str, roe_str, profit_str = ["N/A"] * 7

            # 1. Croissance CA
            rev_growth = info.get("revenueGrowth")
            if isinstance(rev_growth, (int, float)):
                rev_str = f"{rev_growth * 100:+.1f}%"

            # 2. Forward P/E
            fwd_pe = info.get("forwardPE")
            if isinstance(fwd_pe, (int, float)) and fwd_pe > 0:
                pe_str = f"{fwd_pe:.1f}"

            # 3. EV/EBITDA
            ev_ebitda = info.get("enterpriseToEbitda")
            if isinstance(ev_ebitda, (int, float)) and ev_ebitda > 0:
                ev_str = f"{ev_ebitda:.1f}"

            # 4. PEG
            peg = info.get("pegRatio")
            if isinstance(peg, (int, float)) and peg > 0:
                peg_str = f"{peg:.2f}"

            # 5. Dividende
            div_yield = info.get("dividendYield")
            if isinstance(div_yield, (int, float)):
                div_val = div_yield * 100 if div_yield < 1.0 else div_yield
                if div_val < 20.0:
                    div_str = f"{div_val:.2f}%"
                else:
                    div_str = f"{div_val / 100:.2f}%"
            else:
                div_str = "0.00%"

            # 6. ROE
            roe = info.get("returnOnEquity")
            if isinstance(roe, (int, float)):
                roe_str = f"{roe * 100:.1f}%"

            # 7. Marge Nette
            profit = info.get("profitMargins")
            if isinstance(profit, (int, float)):
                profit_str = f"{profit * 100:.1f}%"

            data.append({
                "Ticker": symbol,
                "Croit. CA": rev_str,
                "Fwd P/E": pe_str,
                "EV/EBITDA": ev_str,
                "PEG": peg_str,
                "Div.": div_str,
                "ROE": roe_str,
                "Marge N.": profit_str
            })

        except Exception:
            continue

    if not data:
        send_telegram("❌ Erreur lors de la récupération des données fondamentales.")
        return

    df = pd.DataFrame(data)
    image_filename = generate_html_dashboard(df)
    send_telegram_photo(image_filename, caption="📊 **Analyse Fondamentale Hebdomadaire**")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        mode = sys.argv[1]
        if mode == "prices":
            send_prices()
        elif mode == "news":
            send_news()
        elif mode == "fundamentals":
            send_fundamentals()
