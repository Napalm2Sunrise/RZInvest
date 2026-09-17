from datetime import datetime
import os
import requests
import yfinance as yf

# Liste de vos actions à surveiller
TICKERS = ["MC.PA", "TTE.PA", "AAPL", "MSFT", "NVDA"]

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

# Mots-clés pour filtrer uniquement les actualités à fort impact
IMPORTANT_KEYWORDS = [
    # Résultats & Finance
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
    # Stratégie & Événements majeurs
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
    # Mouvements de marché majeurs
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
  """Envoie le message formaté sur Telegram."""
  url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
  requests.post(
      url,
      json={
          "chat_id": CHAT_ID,
          "text": message,
          "parse_mode": "Markdown",
          "disable_web_page_preview": True,
      },
  )


def check_200_weekly_sma(ticker, current_price):
  """Calcule si le prix est au-dessus ou en dessous de la SMA 200 semaines."""
  try:
    # Récupération de l'historique hebdomadaire sur 5 ans (~260 semaines)
    hist = ticker.history(period="5y", interval="1wk")
    if len(hist) >= 200:
      # Calcul de la moyenne des 200 dernières clôtures hebdomadaires
      sma_200 = hist["Close"].tail(200).mean()
      if current_price < sma_200:
        return "Under 🔥"
      else:
        return "Above"
  except Exception:
    pass
  return "N/A"


def get_next_earnings_date(ticker):
  """Récupère la prochaine date de publication future."""
  try:
    calendar = ticker.calendar
    now = datetime.now().date()

    if isinstance(calendar, dict) and "Earnings Date" in calendar:
      for d in calendar["Earnings Date"]:
        d_date = d.date() if isinstance(d, datetime) else d
        if d_date >= now:
          return d_date.strftime("%Y-%m-%d")

    earnings_epoch = ticker.info.get("earningsTimestamp") or ticker.info.get(
        "earningsTimestampStart"
    )
    if earnings_epoch:
      e_date = datetime.fromtimestamp(earnings_epoch).date()
      if e_date >= now:
        return e_date.strftime("%Y-%m-%d")
  except Exception:
    pass
  return "À déterminer"


def get_recent_news(ticker, max_items=2):
  """Récupère uniquement les actualités à fort impact (filtre intelligent)."""
  news_text = ""
  try:
    news_list = ticker.news
    if news_list:
      count = 0
      for item in news_list:
        content = item.get("content", item)
        title = content.get("title") or item.get("title", "")
        title_lower = title.lower()

        link = None
        if "clickThroughUrl" in content and content["clickThroughUrl"]:
          link = content["clickThroughUrl"].get("url")
        elif "canonicalUrl" in content and content["canonicalUrl"]:
          link = content["canonicalUrl"].get("url")
        elif "link" in item:
          link = item["link"]

        is_important = any(kw in title_lower for kw in IMPORTANT_KEYWORDS)

        if is_important and count < max_items:
          if link:
            news_text += f"    • 🔥 [{title}]({link})\n"
          else:
            news_text += f"    • 🔥 {title}\n"
          count += 1
  except Exception:
    pass

  if not news_text:
    news_text = "    • Aucune dépêche majeure aujourd'hui.\n"

  return news_text


def run_tracker():
  message = "📊 **RÉCAPITULATIF ET ACTUALITÉS DU JOUR**\n\n"

  for symbol in TICKERS:
    try:
      ticker = yf.Ticker(symbol)
      info = ticker.info

      # 1. Cours et Variation du jour
      price = info.get("currentPrice") or info.get("regularMarketPrice", 0)
      prev_close = info.get("previousClose", 1)
      change_pct = ((price - prev_close) / prev_close) * 100

      # 2. Devises (§ ou €)
      currency = info.get("currency", "USD")
      curr_symbol = "€" if currency == "EUR" else "$"

      # 3. SMA 200 Hebdomadaire
      sma_status = check_200_weekly_sma(ticker, price)

      # 4. Ratios et Marges
      fwd_pe = info.get("forwardPE")
      fwd_pe_str = (
          f"{round(fwd_pe, 2)}" if isinstance(fwd_pe, (int, float)) else "N/A"
      )

      gross_margin = (
          f"{round(info.get('grossMargins', 0) * 100, 1)}%"
          if info.get("grossMargins")
          else "N/A"
      )
      profit_margin = (
          f"{round(info.get('profitMargins', 0) * 100, 1)}%"
          if info.get("profitMargins")
          else "N/A"
      )

      # 5. Free Cash Flow
      fcf = info.get("freeCashflow", "N/A")
      if isinstance(fcf, (int, float)):
        fcf = f"{round(fcf / 1e9, 2)} Mrd {curr_symbol}"

      # 6. Prochaine date de publication
      next_earnings = get_next_earnings_date(ticker)

      # 7. Actualités filtrées
      news = get_recent_news(ticker)

      # Construction du message Markdown
      status_emoji = "🟢" if change_pct >= 0 else "🔴"
      message += f"{status_emoji} **{symbol}** : {price:.2f} {curr_symbol} ({change_pct:+.2f}%)\n"
      message += f"├ 200 weekly sma : `{sma_status}`\n"
      message += f"├ Marges : Brut `{gross_margin}` | Net `{profit_margin}`\n"
      message += f"├ FCF : `{fcf}` | Forward P/E : `{fwd_pe_str}`\n"
      message += f"├ 📅 Prochaine publication : `{next_earnings}`\n"
      message += f"└ 📰 **Actualités majeures :**\n{news}\n"

    except Exception as e:
      message += f"❌ Erreur sur {symbol}: {str(e)}\n\n"

  send_telegram(message)


if __name__ == "__main__":
  run_tracker()
