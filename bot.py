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
        "👋 PinnOdds Analiz Botu Aktif!\n\n"
        "Komutlar:\n"
        "/maclar - Yaklaşan maçları, 1X2, Alt/Üst ve yüzde olasılıklarını getirir.\n"
        "/ara takım_adı - Maç arar (Örn: /ara Puebla).\n"
        "/durum - Bot durumunu gösterir."
    )

async def durum(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Bot 7/24 aktif çalışıyor!")

def calculate_prob(odd):
    """Orandan yüzde olasılık hesabı"""
    try:
        val = float(odd)
        if val > 1.0:
            return f"%{round((1 / val) * 100, 1)}"
    except (ValueError, TypeError):
        pass
    return "-"

def parse_markets_direct(markets_data):
    """PinnOdds API'sinin 'markets' objesini doğrudan ayrıştırır"""
    odds = {
        "1": "-", "X": "-", "2": "-",
        "o15": "-", "u15": "-",
        "o25": "-", "u25": "-",
        "o35": "-", "u35": "-"
    }
    
    if not isinstance(markets_data, dict):
        return odds

    # 1. Moneyline / 1X2 (MS) Oranları
    moneyline = markets_data.get("moneyline", markets_data.get("1x2", {}))
    if isinstance(moneyline, dict):
        odds["1"] = moneyline.get("home", moneyline.get("1", "-"))
        odds["X"] = moneyline.get("draw", moneyline.get("x", "-"))
        odds["2"] = moneyline.get("away", moneyline.get("2", "-"))

    # 2. Totals / Alt-Üst Oranları
    totals = markets_data.get("totals", {})
    if isinstance(totals, dict):
        for line, data in totals.items():
            line_str = str(line)
            if isinstance(data, dict):
                over_val = data.get("over", "-")
                under_val = data.get("under", "-")
                
                if line_str in ["1.5", "15"]:
                    odds["o15"], odds["u15"] = over_val, under_val
                elif line_str in ["2.5", "25"]:
                    odds["o25"], odds["u25"] = over_val, under_val
                elif line_str in ["3.5", "35"]:
                    odds["o35"], odds["u35"] = over_val, under_val

    return odds

def fetch_and_process_matches():
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
        
        # Başlamış maçları filtrele
        if match_dt and match_dt < now:
            continue
        
        ev["parsed_dt"] = match_dt
        valid_events.append(ev)

    # Saat sırasına diz (En yakın maç üstte)
    valid_events.sort(key=lambda x: x["parsed_dt"] if x["parsed_dt"] else datetime.max.replace(tzinfo=timezone.utc))
    return valid_events, 200

def get_single_event_odds(event_id, ev_fallback):
    """Tekil maç detayından veya ana obje üzerindeki markets'ten oranları çeker"""
    headers = {"x-portal-apikey": PINNODDS_API_KEY}
    url = f"https://pinnodds.com/kit/v1/prematch/event?event_id={event_id}"
    
    try:
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            data = res.json()
            # API yanıtındaki 'markets' veya 'periods' verisi
            mk = data.get("markets", {})
            if not mk and "periods" in data:
                p0 = data["periods"].get("num_0", data["periods"].get("0", {}))
                mk = p0
            return parse_markets_direct(mk)
    except Exception:
        pass

    # Yedek: Fikstür objesinin kendi içindeki markets
    return parse_markets_direct(ev_fallback.get("markets", {}))

def format_card(match):
    home = match.get("home", "Ev Sahibi")
    away = match.get("away", "Deplasman")
    league = match.get("league_name", match.get("league", "Futbol Ligi"))
    event_id = match.get("id")
    
    time_str = "Saat Bilinmiyor"
    if match.get("parsed_dt"):
        time_str = match["parsed_dt"].strftime("%H:%M (%d.%m.%Y)")

    # Oranları Çek
    odds = get_single_event_odds(event_id, match)
    
    # Yüzde Olasılık Hesabı
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
        await update.message.reply_text("❌ API anahtarı tanımlı değil.")
        return

    await update.message.reply_text("⏳ Yaklaşan maçlar ve oranlar çekiliyor...")
    try:
        events, status = fetch_and_process_matches()
        if status != 200 or not events:
            await update.message.reply_text("⚠️ Maç bulunamadı.")
            return

        msg = "⚽ **YAKLAŞAN MAÇLAR VE ANALİZ** ⚽\n"
        msg += "───────────────────\n\n"

        for match in events[:5]:
            msg += format_card(match) + "\n"

        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Hata: {str(e)}")

async def ara(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not PINNODDS_API_KEY:
        await update.message.reply_text("❌ API anahtarı tanımlı değil.")
        return

    if not context.args:
        await update.message.reply_text("⚠️ Takım adı girin.\nÖrnek: `/ara Puebla`", parse_mode="Markdown")
        return

    query = " ".join(context.args).lower()
    await update.message.reply_text(f"🔍 '{query}' aranıyor...")

    try:
        events, status = fetch_and_process_matches()
        if status != 200 or not events:
            await update.message.reply_text("⚠️ Maç verisi alınamadı.")
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
        print("HATA: TELEGRAM_BOT_TOKEN yok!")
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
