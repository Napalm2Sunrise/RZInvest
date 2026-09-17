import os
import requests
import yfinance as yf

# Indiquez vos actions ici (symboles Yahoo Finance, ex: MC.PA pour LVMH, AAPL pour Apple)
TICKERS = ["MC.PA", "TTE.PA", "AAPL", "MSFT", "NVDA"]

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")


def send_telegram(message):
  url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
  requests.post(
      url, json={"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
  )


def run_tracker():
  message = "📊 **RÉCAPITULATIF FIN DE JOURNÉE**\n\n"

  for symbol in TICKERS:
    try:
      ticker = yf.Ticker(symbol)
      info = ticker.info

      # 1. Calcul du prix et de la variation
      price = info.get("currentPrice") or info.get("regularMarketPrice", 0)
      prev_close = info.get("previousClose", 1)
      change_pct = ((price - prev_close) / prev_close) * 100

      # 2. Indicateurs clés
      fwd_pe = info.get("forwardPE", "N/A")
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
      fcf = info.get("freeCashflow", "N/A")
      if isinstance(fcf, (int, float)):
        fcf = f"{round(fcf / 1e9, 2)} Mrd $"

      # Alignement du texte
      status_emoji = "🟢" if change_pct >= 0 else "🔴"
      message += f"{status_emoji} **{symbol}** : {price:.2f} ({change_pct:+.2f}%)\n"
      message += f"├ Marges : Brut `{gross_margin}` | Net `{profit_margin}`\n"
      message += f"├ FCF : `{fcf}` | Forward P/E : `{fwd_pe}`\n"

      # 3. Alerte calendrier résultats
      calendar = ticker.calendar
      if calendar and "Earnings Date" in calendar:
        message += (
          f"└ 📅 Prochaines publications : {calendar['Earnings Date'][0]}\n"
        )

      message += "\n"
    except Exception as e:
      message += f"❌ Erreur sur {symbol}: {str(e)}\n\n"

  send_telegram(message)


if __name__ == "__main__":
  run_tracker()
