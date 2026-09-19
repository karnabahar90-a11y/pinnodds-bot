import os
import logging
import threading
import requests
from datetime import datetime, timezone
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PINNODDS_API_KEY = os.getenv("PINNODDS_API_KEY")

app_flask = Flask(__name__)

@app_flask.route('/')
def health_check():
    return "Bot is running!", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host="0.0.0.0", port=port, use_reloader=False)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 PinnOdds Bot Aktif!\n\n"
        "Komutlar:\n"
        "/maclar - Maçları, oranları ve yüzdelikleri listeler.\n"
        "/ara [takım] - Takım arar."
    )

async def durum(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Bot aktif çalışıyor.")

def calculate_prob(odd):
    try:
        val = float(odd)
        if val > 1.0:
            return f"%{round((1 / val) * 100, 1)}"
    except (ValueError, TypeError):
        pass
    return "-"

def extract_odds_safely(ev):
    odds = {
        "1": "-", "X": "-", "2": "-",
        "o15": "-", "u15": "-",
        "o25": "-", "u25": "-",
        "o35": "-", "u35": "-"
    }

    # 1. Doğrudan event seviyesindeki alanlar
    for k in ["home_price", "home_odds", "price_home", "home_win", "1"]:
        if k in ev and ev[k] not in [None, ""]: odds["1"] = str(ev[k])
    for k in ["draw_price", "draw_odds", "price_draw", "draw", "x", "X"]:
        if k in ev and ev[k] not in [None, ""]: odds["X"] = str(ev[k])
    for k in ["away_price", "away_odds", "price_away", "away_win", "2"]:
        if k in ev and ev[k] not in [None, ""]: odds["2"] = str(ev[k])

    # 2. periods -> num_0 veya 0 (Pinnacle standart yapısı)
    periods = ev.get("periods", {})
    if isinstance(periods, dict):
        p0 = periods.get("num_0", periods.get("0", {}))
        if isinstance(p0, dict):
            # Moneyline (1X2) kontrolü
            ml = p0.get("money_line", p0.get("moneyline", p0.get("1x2", {})))
            if isinstance(ml, dict):
                if odds["1"] == "-": odds["1"] = str(ml.get("home", ml.get("1", "-")))
                if odds["X"] == "-": odds["X"] = str(ml.get("draw", ml.get("x", "-")))
                if odds["2"] == "-": odds["2"] = str(ml.get("away", ml.get("2", "-")))
            
            # Eğer money_line doğrudan p0 içinde home/draw/away olarak duruyorsa
            if odds["1"] == "-" and "home" in p0: odds["1"] = str(p0.get("home"))
            if odds["X"] == "-" and "draw" in p0: odds["X"] = str(p0.get("draw"))
            if odds["2"] == "-" and "away" in p0: odds["2"] = str(p0.get("away"))

            # Totals (Alt/Üst) kontrolü
            totals = p0.get("totals", p0.get("over_under", {}))
            if isinstance(totals, dict):
                for line, tdata in totals.items():
                    if isinstance(tdata, dict):
                        o = tdata.get("over", tdata.get("o", "-"))
                        u = tdata.get("under", tdata.get("u", "-"))
                        if str(line) in ["1.5", "15"]: odds["o15"], odds["u15"] = str(o), str(u)
                        if str(line) in ["2.5", "25"]: odds["o25"], odds["u25"] = str(o), str(u)
                        if str(line) in ["3.5", "35"]: odds["o35"], odds["u35"] = str(o), str(u)

    # 3. markets anahtarı altındaki olası yapılar
    markets = ev.get("markets", {})
    if isinstance(markets, dict):
        ml = markets.get("moneyline", markets.get("money_line", markets.get("1x2", {})))
        if isinstance(ml, dict):
            if odds["1"] == "-": odds["1"] = str(ml.get("home", ml.get("1", "-")))
            if odds["X"] == "-": odds["X"] = str(ml.get("draw", ml.get("x", "-")))
            if odds["2"] == "-": odds["2"] = str(ml.get("away", ml.get("2", "-")))

    return odds

def fetch_data():
    headers = {"x-portal-apikey": PINNODDS_API_KEY}
    url = "https://pinnodds.com/kit/v1/prematch/fixtures?sport_id=1"
    
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code != 200:
            return None
        events = res.json().get("events", [])
        
        now = datetime.now(timezone.utc)
        valid = []
        for ev in events:
            starts_at = ev.get("starts_at", ev.get("starts", ""))
            match_dt = None
            if starts_at:
                try:
                    match_dt = datetime.fromisoformat(starts_at.replace("Z", "+00:00"))
                except:
                    pass
            if match_dt and match_dt < now:
                continue
            ev["parsed_dt"] = match_dt
            valid.append(ev)
            
        valid.sort(key=lambda x: x["parsed_dt"] if x["parsed_dt"] else datetime.max.replace(tzinfo=timezone.utc))
        return valid
    except:
        return None

def build_card(match):
    home = match.get("home", match.get("home_team", "Ev Sahibi"))
    away = match.get("away", match.get("away_team", "Deplasman"))
    league = match.get("league_name", match.get("league", "Futbol Ligi"))
    
    time_str = "Bilinmiyor"
    if match.get("parsed_dt"):
        time_str = match["parsed_dt"].strftime("%H:%M (%d.%m.%Y)")

    odds = extract_odds_safely(match)
    
    p1 = calculate_prob(odds["1"])
    px = calculate_prob(odds["X"])
    p2 = calculate_prob(odds["2"])

    card = f"⏰ **Saat:** {time_str}\n"
    card += f"🏆 **{league}**\n"
    card += f"⚔️ **{home} vs {away}**\n\n"
    card += f"📊 **Kazanma Olasılık Yüzdeleri:**\n"
    card += f"• Ev Sahibi: **{p1}** | Beraberlik: **{px}** | Deplasman: **{p2}**\n\n"
    card += f"1️⃣ **MS (1X2) Oranları:**\n"
    card += f"• MS 1: {odds['1']} | MS X: {odds['X']} | MS 2: {odds['2']}\n\n"
    card += f"⚽ **Alt / Üst Oranları:**\n"
    card += f"• 1.5 Alt: {odds['u15']} | 1.5 Üst: {odds['o15']}\n"
    card += f"• 2.5 Alt: {odds['u25']} | 2.5 Üst: {odds['o25']}\n"
    card += f"• 3.5 Alt: {odds['u35']} | 3.5 Üst: {odds['o35']}\n"
    card += "───────────────────\n"
    return card

async def maclar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not PINNODDS_API_KEY:
        await update.message.reply_text("❌ API anahtarı eksik.")
        return

    await update.message.reply_text("⏳ Maçlar ve oranlar yükleniyor...")
    events = fetch_data()
    if not events:
        await update.message.reply_text("⚠️ Maç verisi alınamadı.")
        return

    msg = "⚽ **YAKLAŞAN MAÇLAR** ⚽\n───────────────────\n\n"
    for m in events[:5]:
        msg += build_card(m) + "\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def ara(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ Takım adı yazın (Örn: /ara Puebla)")
        return
    query = " ".join(context.args).lower()
    events = fetch_data()
    if not events:
        await update.message.reply_text("⚠️ Maç bulunamadı.")
        return
    
    matches = [m for m in events if query in str(m.get("home", "")).lower() or query in str(m.get("away", "")).lower()]
    if not matches:
        await update.message.reply_text(f"🔍 '{query}' için maç bulunamadı.")
        return

    msg = f"🔎 **ARAMA: {query.upper()}**\n───────────────────\n\n"
    for m in matches[:5]:
        msg += build_card(m) + "\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

def main():
    if not TELEGRAM_BOT_TOKEN:
        return
    t = threading.Thread(target=run_flask, daemon=True)
    t.start()
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("durum", durum))
    app.add_handler(CommandHandler("maclar", maclar))
    app.add_handler(CommandHandler("ara", ara))
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
