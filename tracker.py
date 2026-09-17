from datetime import datetime
import os
import requests
import yfinance as yf

# Liste des actions à surveiller
TICKERS = ["MC.PA", "TTE.PA", "AAPL", "MSFT", "NVDA"]

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

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


def get_recent_news(ticker, max_items=1):
  """Récupère l'actualité à fort impact avec lien cliquable."""
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
            news_text += f"    • [{title}]({link})\n"
          else:
            news_text += f"    • {title}\n"
          count += 1
  except Exception:
    pass

  if not news_text:
    news_text = "    • Aucune dépêche majeure.\n"

  return news_text


def run_tracker():
  message = "📊 **RÉCAPITULATIF BOURSIER DU JOUR**\n"
  message += f"📅 `{datetime.now().strftime('%d/%m/%Y - %H:%M')}`\n\n"

  for symbol in TICKERS:
    try:
      ticker = yf.Ticker(symbol)
      info = ticker.info

      price = info.get("currentPrice") or info.get("regularMarketPrice", 0)
      prev_close = info.get("previousClose", 1)
      change_pct = ((price - prev_close) / prev_close) * 100

      currency = info.get("currency", "USD")
      curr_symbol = "€" if currency == "EUR" else "$"

      sma_status = check_200_weekly_sma(ticker, price)

      # Marges
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

      # FCF
      fcf = info.get("freeCashflow", "N/A")
      if isinstance(fcf, (int, float)):
        fcf = f"{round(fcf / 1e9, 2)} Mrd {curr_symbol}"

      # Valorisations
      fwd_pe = info.get("forwardPE")
      fwd_pe_str = (
          f"{round(fwd_pe, 2)}" if isinstance(fwd_pe, (int, float)) else "N/A"
      )

      # 2. EV/EBITDA
      ev_ebitda = info.get("enterpriseToEbitda")
      ev_ebitda_str = (
          f"{round(ev_ebitda, 2)}"
          if isinstance(ev_ebitda, (int, float))
          else "N/A"
      )

      # 3. Dividend Yield
      div_yield = info.get("dividendYield")
      div_str = (
          f"{round(div_yield * 100, 2)}%"
          if isinstance(div_yield, (int, float))
          else "0%"
      )

      # 4. PEG Ratio
      peg = info.get("pegRatio")
      peg_str = f"{round(peg, 2)}" if isinstance(peg, (int, float)) else "N/A"

      # 5. ROE
      roe = info.get("returnOnEquity")
      roe_str = (
          f"{round(roe * 100, 1)}%" if isinstance(roe, (int, float)) else "N/A"
      )

      next_earnings = get_next_earnings_date(ticker)
      news = get_recent_news(ticker)

      sma_display = (
          f"`{sma_status}`" if "Under" not in sma_status else f"**{sma_status}**"
      )

      status_emoji = "🟢" if change_pct >= 0 else "🔴"
      message += f"{status_emoji} **{symbol}** : `{price:.2f} {curr_symbol}` ({change_pct:+.2f}%)\n"
      message += f"├ **200 W-SMA** : {sma_display}\n"
      message += f"├ **Valo.** : Fwd P/E `{fwd_pe_str}` | EV/EBITDA `{ev_ebitda_str}` | PEG `{peg_str}`\n"
      message += f"├ **Rendement** : Div. `{div_str}` | ROE `{roe_str}`\n"
      message += f"├ **Marges** : Brut `{gross_margin}` | Net `{profit_margin}`\n"
      message += f"├ **FCF** : `{fcf}`\n"
      message += f"├ 📅 **Prochaine pub.** : `{next_earnings}`\n"
      message += f"└ 📰 **News** :\n{news}\n"

    except Exception as e:
      message += f"❌ Erreur sur {symbol}: {str(e)}\n\n"

  send_telegram(message)


if __name__ == "__main__":
  run_tracker()
