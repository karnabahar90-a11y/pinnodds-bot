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
        "/maclar - Maçları ve oranları listeler.\n"
        "/ara [takım] - Belirli bir takımı arar."
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
    """PinnOdds objesindeki olası tüm 1X2 ve Alt/Üst anahtarlarını güvenle tarar"""
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

    # 2. 'markets' veya 'periods' içindeki olası yapılar
    for container_key in ["markets", "periods", "prices", "odds"]:
        container = ev.get(container_key)
        if isinstance(container, dict):
            for sub_k, sub_v in container.items():
                if isinstance(sub_v, dict):
                    # Moneyline arama
                    for mk_key in ["moneyline", "1x2", "win_draw_win"]:
                        if mk_key in sub_v and isinstance(sub_v[mk_key], dict):
                            ml = sub_v[mk_key]
                            if odds["1"] == "-": odds["1"] = str(ml.get("home", ml.get("1", "-")))
                            if odds["X"] == "-": odds["X"] = str(ml.get("draw", ml.get("x", "-")))
                            if odds["2"] == "-": odds["2"] = str(ml.get("away", ml.get("2", "-")))
                    
                    # Totals arama
                    for tot_key in ["totals", "over_under"]:
                        if tot_key in sub_v and isinstance(sub_v[tot_key], dict):
                            for line, tdata in sub_v[tot_key].items():
                                if isinstance(tdata, dict):
                                    o = tdata.get("over", tdata.get("o", "-"))
                                    u = tdata.get("under", tdata.get("u", "-"))
                                    if str(line) in ["1.5", "15"]: odds["o15"], odds["u15"] = str(o), str(u)
                                    if str(line) in ["2.5", "25"]: odds["o25"], odds["u25"] = str(o), str(u)
                                    if str(line) in ["3.5", "35"]: odds["o35"], odds["u35"] = str(o), str(u)

        elif isinstance(container, list):
            for item in container:
                if isinstance(item, dict):
                    name = str(item.get("name", item.get("type", ""))).lower()
                    if "moneyline" in name or "1x2" in name:
                        if odds["1"] == "-": odds["1"] = str(item.get("home", item.get("price_1", "-")))
                        if odds["X"] == "-": odds["X"] = str(item.get("draw", item.get("price_x", "-")))
                        if odds["2"] == "-": odds["2"] = str(item.get("away", item.get("price_2", "-")))

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

    await update.message.reply_text("⏳ Maçlar yükleniyor...")
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
