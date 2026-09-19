import os
import logging
import threading
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
        "👋 PinnOdds Analiz Botuna Hoş Geldiniz!\n\n"
        "Komutlar:\n"
        "/maclar - Yaklaşan maçları, 1X2 ve Alt/Üst oranları ile olasılık yüzdelerini getirir.\n"
        "/ara takım_adı - İstediğiniz takımı arar (Örn: /ara Puebla).\n"
        "/durum - Botun çalışma durumunu gösterir."
    )

async def durum(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Bot Render üzerinde 7/24 aktif çalışıyor!")

def calculate_prob(odd):
    try:
        val = float(odd)
        if val > 1.0:
            return f"%{round((1 / val) * 100, 1)}"
    except (ValueError, TypeError):
        pass
    return "-"

def get_event_details(event_id):
    """Prematch Event endpoint'inden 1X2 ve Alt/Üst oranlarını eksiksiz çeker"""
    import requests
    url = f"https://pinnodds.com/kit/v1/prematch/event?event_id={event_id}"
    headers = {"x-portal-apikey": PINNODDS_API_KEY}
    
    odds = {
        "1": "-", "X": "-", "2": "-",
        "o15": "-", "u15": "-",
        "o25": "-", "u25": "-",
        "o35": "-", "u35": "-"
    }
    
    try:
        res = requests.get(url, headers=headers, timeout=6)
        if res.status_code == 200:
            data = res.json()
            periods = data.get("periods", {})
            p0 = periods.get("num_0", periods.get("0", {}))
            if not p0 and isinstance(periods, dict) and len(periods) > 0:
                p0 = list(periods.values())[0]

            if isinstance(p0, dict):
                # 1X2 Oranları
                ml = p0.get("moneyline", {})
                if isinstance(ml, dict):
                    odds["1"] = ml.get("home", ml.get("1", "-"))
                    odds["X"] = ml.get("draw", ml.get("x", "-"))
                    odds["2"] = ml.get("away", ml.get("2", "-"))

                # Alt / Üst Oranları
                totals = p0.get("totals", {})
                if isinstance(totals, dict):
                    for line, tdata in totals.items():
                        line_str = str(line)
                        if isinstance(tdata, dict):
                            o_val = tdata.get("over", "-")
                            u_val = tdata.get("under", "-")
                            if line_str in ["1.5", "15"]:
                                odds["o15"], odds["u15"] = o_val, u_val
                            elif line_str in ["2.5", "25"]:
                                odds["o25"], odds["u25"] = o_val, u_val
                            elif line_str in ["3.5", "35"]:
                                odds["o35"], odds["u35"] = o_val, u_val
    except Exception:
        pass

    return odds

def fetch_matches():
    import requests
    headers = {"x-portal-apikey": PINNODDS_API_KEY}
    url = "https://pinnodds.com/kit/v1/prematch/fixtures?sport_id=1"
    
    res = requests.get(url, headers=headers, timeout=10)
    if res.status_code != 200:
        return None, res.status_code

    events = res.json().get("events", [])
    now = datetime.now(timezone.utc)
    valid_events = []

    for ev in events:
        starts_at = ev.get("starts_at", ev.get("starts", ""))
        match_dt = None
        if starts_at:
            try:
                clean_time = starts_at.replace("Z", "+00:00")
                match_dt = datetime.fromisoformat(clean_time)
            except Exception:
                pass
        
        if match_dt and match_dt < now:
            continue
        
        ev["parsed_dt"] = match_dt
        valid_events.append(ev)

    valid_events.sort(key=lambda x: x["parsed_dt"] if x["parsed_dt"] else datetime.max.replace(tzinfo=timezone.utc))
    return valid_events, 200

def format_card(match):
    home = match.get("home", "Ev Sahibi")
    away = match.get("away", "Deplasman")
    league = match.get("league_name", "Futbol Ligi")
    event_id = match.get("id")
    
    time_str = "Saat Bilinmiyor"
    if match.get("parsed_dt"):
        time_str = match["parsed_dt"].strftime("%H:%M (%d.%m.%Y)")

    # Detay endpoint'inden oranları al
    odds = get_event_details(event_id)
    
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
        await update.message.reply_text("❌ API anahtarı yok.")
        return

    await update.message.reply_text("⏳ En yakın maçlar ve 1X2/Alt-Üst oranları çekiliyor...")
    try:
        events, status = fetch_matches()
        if status != 200 or not events:
            await update.message.reply_text("⚠️ Başlamamış maç bulunamadı.")
            return

        msg = "⚽ **YAKLAŞAN MAÇLAR VE ORANLAR** ⚽\n"
        msg += "───────────────────\n\n"

        for match in events[:5]:
            msg += format_card(match) + "\n"

        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Hata: {str(e)}")

async def ara(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not PINNODDS_API_KEY:
        await update.message.reply_text("❌ API anahtarı yok.")
        return

    if not context.args:
        await update.message.reply_text("⚠️ Takım adı yazın. Örnek: `/ara Puebla`", parse_mode="Markdown")
        return

    query = " ".join(context.args).lower()
    await update.message.reply_text(f"🔍 '{query}' aranıyor...")

    try:
        events, status = fetch_matches()
        if status != 200 or not events:
            await update.message.reply_text("⚠️ Maç bulunamadı.")
            return

        matches = [ev for ev in events if query in str(ev.get("home", "")).lower() or query in str(ev.get("away", "")).lower()]

        if not matches:
            await update.message.reply_text(f"🔍 '{query}' için başlamamış maç bulunamadı.")
            return

        msg = f"🔎 **ARAMA SONUÇLARI ({query.upper()})** 🔎\n"
        msg += "───────────────────\n\n"

        for match in matches[:5]:
            msg += format_card(match) + "\n"

        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Hata: {str(e)}")

def main():
    if not TELEGRAM_BOT_TOKEN:
        print("HATA: TELEGRAM_BOT_TOKEN bulunamadı!")
        return

    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("durum", durum))
    app.add_handler(CommandHandler("oranlar", maclar))
    app.add_handler(CommandHandler("maclar", maclar))
    app.add_handler(CommandHandler("ara", ara))

    print("Bot başlatılıyor...")
    app.run_polling(drop_pending_updates=True, stop_signals=None)

if __name__ == "__main__":
    main()
