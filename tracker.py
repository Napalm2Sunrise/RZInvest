from datetime import datetime
import os
from PIL import Image, ImageDraw, ImageFont
import requests
import yfinance as yf

# 1. LISTE DES ACTIONS À SURVEILLER
TICKERS = ["MC.PA", "TTE.PA", "AAPL", "MSFT", "NVDA"]

# 2. IDENTIFIANTS TELEGRAM (RÉCUPÉRÉS DEPUIS GITHUB SECRETS)
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

# 3. MOTS-CLÉS POUR FILTRER LES ACTUALITÉS IMPORTANTES
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
    "bénéfice",
    "chiffre d'affaires",
    "résultat",
    "buyout",
    "acquisition",
    "merger",
    "sec",
    "ceo",
    "cfo",
    "layoff",
    "upgrade",
    "downgrade",
]


def send_telegram_photo(image_path, caption=""):
  """Envoie l'image générée ET la légende texte avec liens sur Telegram."""
  url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
  with open(image_path, "rb") as photo:
    requests.post(
        url,
        data={"chat_id": CHAT_ID, "caption": caption, "parse_mode": "Markdown"},
        files={"photo": photo},
    )


def check_200_weekly_sma(ticker, current_price):
  """Calcule si le prix est au-dessus ou sous la Moyenne Mobile 200 Semaines."""
  try:
    hist = ticker.history(period="5y", interval="1wk")
    if len(hist) >= 200:
      sma_200 = hist["Close"].tail(200).mean()
      return "Under 🔥" if current_price < sma_200 else "Above"
  except Exception:
    pass
  return "N/A"


def get_next_earnings_date(ticker):
  """Trouve la prochaine date de résultats."""
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
  return "A determiner"


def generate_image(data):
  """Dessine la carte d'analyse financière sous forme d'image PNG."""
  width = 800
  height = 120 + len(data) * 160
  bg_color = (20, 24, 33)  # Fond sombre
  card_color = (30, 36, 48)  # Fond des cartes

  img = Image.new("RGB", (width, height), color=bg_color)
  draw = ImageDraw.Draw(img)

  # Chargement des polices de caractères
  try:
    font_title = ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 22
    )
    font_bold = ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 15
    )
    font_normal = ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 13
    )
  except Exception:
    font_title = font_bold = font_normal = ImageFont.load_default()

  # En-tête de l'image
  draw.text(
      (30, 25),
      "RÉCAPITULATIF BOURSIER DU JOUR",
      fill=(255, 255, 255),
      font=font_title,
  )
  draw.text(
      (30, 55),
      datetime.now().strftime("%d/%m/%Y - %H:%M"),
      fill=(140, 150, 165),
      font=font_normal,
  )

  y = 90
  for item in data:
    # Boîte pour chaque action
    draw.rectangle([25, y, width - 25, y + 145], fill=card_color)

    # Barre latérale verte (hausse) ou rouge (baisse)
    bar_color = (
        (46, 204, 113) if item["change_pct"] >= 0 else (231, 76, 60)
    )  # Vert / Rouge
    draw.rectangle([25, y, 32, y + 145], fill=bar_color)

    # Ligne 1 : Symbole, Prix et Variation
    header_text = f"{item['symbol']} : {item['price']:.2f} {item['curr_symbol']} ({item['change_pct']:+.2f}%)"
    draw.text((45, y + 12), header_text, fill=(255, 255, 255), font=font_bold)

    # Ligne 2 : 200 Weekly SMA et Prochaine publication
    sma_color = (
        (241, 196, 15) if "Under" in item["sma_status"] else (180, 190, 200)
    )
    draw.text(
        (45, y + 42),
        f"200 W-SMA: {item['sma_status']}",
        fill=sma_color,
        font=font_bold,
    )
    draw.text(
        (350, y + 42),
        f"Prochaine pub.: {item['next_earnings']}",
        fill=(180, 190, 200),
        font=font_normal,
    )

    # Ligne 3 : Marges, FCF et Forward P/E
    marge_text = f"Marges : Brut {item['gross_margin']} | Net {item['profit_margin']}   -   FCF : {item['fcf']}   -   Fwd P/E : {item['fwd_pe_str']}"
    draw.text(
        (45, y + 70), marge_text, fill=(160, 175, 195), font=font_normal
    )

    # Ligne 4 : Titre résumé de l'actualité
    news_title = item["news_title"] if item["news_title"] else "Aucune dépêche majeure."
    if len(news_title) > 80:
      news_title = news_title[:77] + "..."
    draw.text(
        (45, y + 102),
        f"News : {news_title}",
        fill=(220, 225, 230),
        font=font_normal,
    )

    y += 160

  output_path = "summary.png"
  img.save(output_path)
  return output_path


def run_tracker():
  data = []
  clickable_links = ""

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

      fcf = info.get("freeCashflow", "N/A")
      if isinstance(fcf, (int, float)):
        fcf = f"{round(fcf / 1e9, 2)} Mrd {curr_symbol}"

      next_earnings = get_next_earnings_date(ticker)

      # Récupération de l'actualité + lien cliquable
      news_title = ""
      news_link = None
      if ticker.news:
        for item in ticker.news:
          content = item.get("content", item)
          title = content.get("title") or item.get("title", "")

          link = None
          if "clickThroughUrl" in content and content["clickThroughUrl"]:
            link = content["clickThroughUrl"].get("url")
          elif "canonicalUrl" in content and content["canonicalUrl"]:
            link = content["canonicalUrl"].get("url")
          elif "link" in item:
            link = item["link"]

          if any(kw in title.lower() for kw in IMPORTANT_KEYWORDS):
            news_title = title
            news_link = link
            break

      # Si on a trouvé un article important, on prépare le lien cliquable pour Telegram
      if news_title and news_link:
        clickable_links += f"• **{symbol}** : [{news_title}]({news_link})\n"

      data.append({
          "symbol": symbol,
          "price": price,
          "change_pct": change_pct,
          "curr_symbol": curr_symbol,
          "sma_status": sma_status,
          "fwd_pe_str": fwd_pe_str,
          "gross_margin": gross_margin,
          "profit_margin": profit_margin,
          "fcf": fcf,
          "next_earnings": next_earnings,
          "news_title": news_title,
      })
    except Exception as e:
      print(f"Erreur sur {symbol}: {e}")

  # Génération de l'image et envoi sur Telegram avec la légende textuelle
  if data:
    image_path = generate_image(data)
    caption_text = "📊 **RÉCAPITULATIF BOURSIER DU JOUR**\n\n"
    if clickable_links:
      caption_text += (
          "🔗 **Dépêches importantes (liens cliquables) :**\n"
          + clickable_links
      )
    else:
      caption_text += "📰 Aucune dépêche majeure aujourd'hui."

    send_telegram_photo(image_path, caption=caption_text)


if __name__ == "__main__":
  run_tracker()
