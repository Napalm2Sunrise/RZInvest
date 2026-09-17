from datetime import datetime
import os
import requests
import yfinance as yf

TICKERS = ["MC.PA", "TTE.PA", "AAPL", "MSFT", "NVDA"]

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")


def send_telegram(message):
  url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
  # Découpage si le message dépasse la limite de Telegram (4096 caractères)
  if len(message) > 4000:
    for x in range(0, len(message), 4000):
      requests.post(
          url,
          json={
              "chat_id": CHAT_ID,
              "text": message[x : x + 4000],
              "parse_mode": "Markdown",
              "disable_web_page_preview": True,
          },
      )
  else:
    requests.post(
        url,
        json={
            "chat_id": CHAT_ID,
            "text": message,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        },
    )


def get_next_earnings_date(ticker):
  """Filtre les dates pour ne garder que la prochaine publication future."""
  try:
    calendar = ticker.calendar
    if calendar and "Earnings Date" in calendar:
      dates = calendar["Earnings Date"]
      now = datetime.now().date()
      for d in dates:
        d_date = d.date() if isinstance(d, datetime) else d
        if d_date >= now:
          return d_date.strftime("%Y-%m-%d")
  except Exception:
    pass
  return "Non communiquée"


def get_recent_news(ticker, max_items=2):
  """Récupère les derniers titres d'actualités."""
  news_text = ""
  try:
    news_list = ticker.news
    if news_list:
      count = 0
      for item in news_list:
        title = item.get("title")
        link = item.get("link")
        if title and link and count < max_items:
          news_text += f"    • [{title}]({link})\n"
          count += 1
  except Exception:
    pass

  if not news_text:
    news_text = "    • Aucune dépêche récente.\n"
  return news_text


def run_tracker():
  message = "📊 **RÉCAPITULATIF ET ACTUALITÉS DU JOUR**\n\n"

  for symbol in TICKERS:
    try:
      ticker = yf.Ticker(symbol)
      info = ticker.info

      # 1. Cours et Variation
      price = info.get("currentPrice") or info.get("regularMarketPrice", 0)
      prev_close = info.get("previousClose", 1)
      change_pct = ((price - prev_close) / prev_close) * 100

      # 2. Devises
      currency = info.get("currency", "USD")
      curr_symbol = "€" if currency == "EUR" else "$"

      # 3. Ratios et Marges
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

      # 4. Free Cash Flow
      fcf = info.get("freeCashflow", "N/A")
      if isinstance(fcf, (int, float)):
        fcf = f"{round(fcf / 1e9, 2)} Mrd {curr_symbol}"

      # 5. Prochaine date de publication
      next_earnings = get_next_earnings_date(ticker)

      # 6. Actualités récentes
      news = get_recent_news(ticker)

      # Construction du message
      status_emoji = "🟢" if change_pct >= 0 else "🔴"
      message += f"{status_emoji} **{symbol}** : {price:.2f} {curr_symbol} ({change_pct:+.2f}%)\n"
      message += f"├ Marges : Brut `{gross_margin}` | Net `{profit_margin}`\n"
      message += f"├ FCF : `{fcf}` | Forward P/E : `{fwd_pe_str}`\n"
      message += f"├ 📅 Prochaine publication : `{next_earnings}`\n"
      message += f"└ 📰 **Actualités récentes :**\n{news}\n"

    except Exception as e:
      message += f"❌ Erreur sur {symbol}: {str(e)}\n\n"

  send_telegram(message)


if __name__ == "__main__":
  run_tracker()
