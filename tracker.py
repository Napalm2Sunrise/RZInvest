from datetime import datetime, timedelta
import json
import os
import sys
import time
import requests
import yfinance as yf

TICKERS = [
    "AED.BR",
    "CPINV.BE",
    "HOMI.BR",
    "RET.BR",
    "AMKR",
    "AVGO",
    "AYA.TO",
    "BKNG",
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

            # Si yfinance ne renvoie rien dans info, on prend le dernier prix de l'historique
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
            # Forcer € si le ticker se termine par .BR, .BE ou .PA
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

            # Paquets de 10 actions
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
    """2. News récentes (< 24h ouvrées et sans doublons)."""
    header = "📰 **DERNIÈRES ACTUALITÉS MAJEURES**\n"
    header += f"📅 `{datetime.now().strftime('%d/%m/%Y - %H:%M')}`\n\n"

    sent_cache = load_sent_news()
    now_ts = datetime.now().timestamp()

    # 24h en jours ouvrés = 24h en semaine, 72h si weekend inclus
    cutoff_ts = now_ts - (72 * 3600 if datetime.now().weekday() == 0 else 24 * 3600)

    news_found = False
    full_message = header

    for symbol in TICKERS:
        try:
            ticker = yf.Ticker(symbol)
            news_list = ticker.news or []
            symbol_news = ""

            for item in news_list:
                content = item.get("content", item)
                title = content.get("title") or item.get("title", "")
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
                is_important = any(kw in title_lower for kw in IMPORTANT_KEYWORDS)

                if is_important:
                    if link:
                        symbol_news += f"  • [{title}]({link})\n"
                    else:
                        symbol_news += f"  • {title}\n"

                    sent_cache[news_id] = now_ts

            if symbol_news:
                full_message += f"🔹 **{symbol}** :\n{symbol_news}\n"
                news_found = True

        except Exception:
            pass

    save_sent_news(sent_cache)

    if news_found:
        send_telegram(full_message)
    else:
        send_telegram(header + "Aucune nouvelle dépêche majeure récente.")


def send_fundamentals():
    """3. Analyse Fondamentale complète (Croissance, Valo, Rendement, Marges, FCF)."""
    header = "📊 **BUREAU D'ANALYSE FONDAMENTALE (HEBDO)**\n"
    header += f"📅 `{datetime.now().strftime('%d/%m/%Y')}`\n\n"
    send_telegram(header)
    time.sleep(0.5)

    current_message = ""
    batch_count = 0

    for symbol in TICKERS:
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info

            # Récupération du prix pour calculer le dividend yield
            price = (
                info.get("currentPrice")
                or info.get("regularMarketPrice")
                or info.get("ask")
                or info.get("bid")
            )
            if not price or price == 0:
                hist = ticker.history(period="5d")
                price = float(hist["Close"].iloc[-1]) if not hist.empty else 1.0

            currency = info.get("currency", "USD")
            if any(symbol.endswith(ext) for ext in [".BR", ".BE", ".PA"]) or currency == "EUR":
                curr_symbol = "€"
            else:
                curr_symbol = "$"

            # 1. Forward P/E
            fwd_pe = info.get("forwardPE")
            fwd_pe_str = f"`{round(fwd_pe, 2)}`" if isinstance(fwd_pe, (int, float)) else "`N/A`"

            # 2. EV/EBITDA
            ev_ebitda = info.get("enterpriseToEbitda")
            ev_ebitda_str = f"`{round(ev_ebitda, 2)}`" if isinstance(ev_ebitda, (int, float)) else "`N/A`"

            # 3. PEG Ratio
            peg = info.get("pegRatio")
            peg_str = f"`{round(peg, 2)}`" if isinstance(peg, (int, float)) else "`N/A`"

            # 4. Dividend Yield
            div_rate = info.get("dividendRate")
            div_yield = info.get("dividendYield")
            div_pct = 0.0
            if isinstance(div_rate, (int, float)) and price > 0:
                div_pct = (div_rate / price) * 100
            elif isinstance(div_yield, (int, float)):
                div_pct = div_yield * 100 if div_yield < 0.2 else div_yield
            div_str = f"`{round(div_pct, 2)}%`"

            # 5. ROE
            roe = info.get("returnOnEquity")
            roe_str = f"`{round(roe * 100, 1)}%`" if isinstance(roe, (int, float)) else "`N/A`"

            # 6. Marges
            gross = info.get("grossMargins")
            gross_str = f"`{round(gross * 100, 1)}%`" if isinstance(gross, (int, float)) else "`N/A`"

            profit = info.get("profitMargins")
            profit_str = f"`{round(profit * 100, 1)}%`" if isinstance(profit, (int, float)) else "`N/A`"

            # 7. Revenue Growth
            rev_growth = info.get("revenueGrowth")
            rev_growth_str = f"`{round(rev_growth * 100, 1)}%`" if isinstance(rev_growth, (int, float)) else "`N/A`"

            # 8. FCF
            fcf = info.get("freeCashflow", "N/A")
            if isinstance(fcf, (int, float)):
                fcf_str = f"`{round(fcf / 1e9, 2)} Mrd {curr_symbol}`"
            else:
                fcf_str = "`N/A`"

            item_text = f"🏢 **{symbol}**\n"
            item_text += f"├ **Croissance CA** : {rev_growth_str}\n"
            item_text += f"├ **Valo.** : Fwd P/E {fwd_pe_str} | EV/EBITDA {ev_ebitda_str} | PEG {peg_str}\n"
            item_text += f"├ **Rendement** : Div. {div_str} | ROE {roe_str}\n"
            item_text += f"├ **Marges** : Brut {gross_str} | Net {profit_str}\n"
            item_text += f"└ **FCF** : {fcf_str}\n\n"

            current_message += item_text
            batch_count += 1

            if batch_count >= 5:
                send_telegram(current_message)
                current_message = ""
                batch_count = 0
                time.sleep(1)

        except Exception as e:
            current_message += f"❌ Erreur sur {symbol}: {str(e)}\n\n"

    if current_message:
        send_telegram(current_message)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        mode = sys.argv[1]
        if mode == "prices":
            send_prices()
        elif mode == "news":
            send_news()
        elif mode == "fundamentals":
            send_fundamentals()
