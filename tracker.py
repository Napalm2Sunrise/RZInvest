from datetime import datetime, timedelta
import json
import os
import sys
import time
import matplotlib.pyplot as plt
import pandas as pd
import requests
import yfinance as yf

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

# Calendrier des prochaines publications macroéconomiques majeures (Format : AAAA-MM-JJ)
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
    "result",
    "earnings",
    "revenue",
    "profit",
    "margin",
    "guidance",
    "dividend",
    "fcf",
    "cash flow",
    "quarter",
    "q1",
    "q2",
    "q3",
    "q4",
    "bénéfice",
    "chiffre d'affaires",
    "résultat",
    "dividende",
    "buyout",
    "acquisition",
    "merger",
    "takeover",
    "sec",
    "investigation",
    "lawsuit",
    "ceo",
    "cfo",
    "layoff",
    "restructuring",
    "rachat",
    "procès",
    "démission",
    "licenciement",
    "upgrade",
    "downgrade",
    "record",
    "plunge",
    "surge",
    "crash",
    "chute",
    "envolée",
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

    # Ajout du bloc macroéconomique dans le premier message
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

            # Récupération sécurisée du prix actuel
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
    """2. News récentes : envoie chaque article sous forme de résumé individuel."""
    sent_cache = load_sent_news()
    now_ts = datetime.now().timestamp()

    # 24h en jours ouvrés = 24h en semaine, 72h si weekend inclus
    cutoff_ts = now_ts - (72 * 3600 if datetime.now().weekday() == 0 else 24 * 3600)

    news_count = 0

    for symbol in TICKERS:
        try:
            ticker = yf.Ticker(symbol)
            news_list = ticker.news or []

            for item in news_list:
                content = item.get("content", item)
                title = content.get("title") or item.get("title", "")
                summary = content.get("summary") or item.get("summary") or content.get("description") or ""
                pub_time = content.get("pubDate") or item.get("providerPublishTime", 0)

                # Si la date est en ISO string, conversion
                if isinstance(pub_time, str):
                    try:
                        pub_time = datetime.fromisoformat(
                            pub_time.replace("Z", "+00:00")
                        ).timestamp()
                    except Exception:
                        pub_time = now_ts

                # Règle 1 : Moins de 24h ouvrées
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

                # Règle 2 : Ne pas se répéter
                if news_id in sent_cache:
                    continue

                title_lower = title.lower()
                summary_lower = summary.lower()
                is_important = any(kw in title_lower or kw in summary_lower for kw in IMPORTANT_KEYWORDS)

                if is_important:
                    news_message = f"📰 **{symbol}** — *Actualité Majeure*\n\n"
                    news_message += f"📌 **{title}**\n\n"
                    if summary:
                        news_message += f"📝 **Résumé** :\n{summary}\n\n"
                    if link:
                        news_message += f"🔗 [Lire l'article complet]({link})"

                    send_telegram(news_message)
                    sent_cache[news_id] = now_ts
                    news_count += 1
                    time.sleep(1)  # Petite pause pour respecter l'API Telegram

        except Exception:
            pass

    save_sent_news(sent_cache)

    if news_count == 0:
        send_telegram("📰 **ACTUALITÉS** : Aucune nouvelle dépêche majeure récente.")


def send_fundamentals():
    """3. Analyse Fondamentale : génère un tableau en image avec code couleur dynamique."""
    data = []
    cell_colors = []

    for symbol in TICKERS:
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info

            # Initialisation des valeurs par défaut
            rev_str, pe_str, ev_str, peg_str, div_str, roe_str, profit_str = ["N/A"] * 7
            c_rev, c_pe, c_ev, c_peg, c_div, c_roe, c_prof = ['#ffffff'] * 7

            # 1. Croissance CA
            rev_growth = info.get("revenueGrowth")
            if isinstance(rev_growth, (int, float)):
                rev_str = f"{rev_growth * 100:+.1f}%"
                c_rev = '#d1fae5' if rev_growth >= 0.1 else ('#fef3c7' if rev_growth >= 0 else '#fee2e2')

            # 2. Forward P/E
            fwd_pe = info.get("forwardPE")
            if isinstance(fwd_pe, (int, float)):
                pe_str = f"{fwd_pe:.1f}"
                c_pe = '#d1fae5' if fwd_pe < 20 else ('#fef3c7' if fwd_pe <= 35 else '#fee2e2')

            # 3. EV/EBITDA
            ev_ebitda = info.get("enterpriseToEbitda")
            if isinstance(ev_ebitda, (int, float)):
                ev_str = f"{ev_ebitda:.1f}"
                c_ev = '#d1fae5' if ev_ebitda < 12 else ('#fef3c7' if ev_ebitda <= 20 else '#fee2e2')

            # 4. PEG
            peg = info.get("pegRatio")
            if isinstance(peg, (int, float)):
                peg_str = f"{peg:.2f}"
                c_peg = '#d1fae5' if peg < 1.0 else ('#fef3c7' if peg <= 2.0 else '#fee2e2')

            # 5. Dividende
            div_yield = info.get("dividendYield")
            if isinstance(div_yield, (int, float)):
                div_val = div_yield * 100 if div_yield < 1.0 else div_yield
                div_str = f"{div_val:.2f}%"
                c_div = '#d1fae5' if div_val >= 3.0 else ('#fef3c7' if div_val >= 1.5 else '#ffffff')
            else:
                div_str = "0.00%"

            # 6. ROE
            roe = info.get("returnOnEquity")
            if isinstance(roe, (int, float)):
                roe_val = roe * 100
                roe_str = f"{roe_val:.1f}%"
                c_roe = '#d1fae5' if roe_val >= 15 else ('#fef3c7' if roe_val >= 8 else '#fee2e2')

            # 7. Marge Nette
            profit = info.get("profitMargins")
            if isinstance(profit, (int, float)):
                prof_val = profit * 100
                profit_str = f"{prof_val:.1f}%"
                c_prof = '#d1fae5' if prof_val >= 15 else ('#fef3c7' if prof_val >= 5 else '#fee2e2')

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

            cell_colors.append(['#ffffff', c_rev, c_pe, c_ev, c_peg, c_div, c_roe, c_prof])

        except Exception as e:
            continue

    if not data:
        send_telegram("❌ Erreur lors de la récupération des données fondamentales.")
        return

    df = pd.DataFrame(data)

    fig, ax = plt.subplots(figsize=(10, len(df) * 0.45 + 1.2), dpi=200)
    ax.axis('off')
    ax.axis('tight')

    # Construction securisee des couleurs
    header_colors = ['#1e293b'] * len(df.columns)
    full_colors = [header_colors] + cell_colors

    table = ax.table(
        cellText=df.values,
        colLabels=df.columns,
        cellColours=full_colors,
        cellLoc='center',
        loc='center'
    )

    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1.2, 1.5)

    # Texte blanc pour l'en-tête
    for col_idx in range(len(df.columns)):
        cell = table[(0, col_idx)]
        cell.get_text().set_color('white')
        cell.get_text().set_weight('bold')

    plt.title(f"📊 BUREAU D'ANALYSE FONDAMENTALE ({datetime.now().strftime('%d/%m/%Y')})", 
              fontsize=12, fontweight='bold', pad=15)

    image_filename = "fundamentals.png"
    plt.savefig(image_filename, bbox_inches='tight', pad_inches=0.2)
    plt.close()

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
