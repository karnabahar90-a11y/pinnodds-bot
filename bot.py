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
        "/maclar - Başlamamış maçları, 1X2 & Alt/Üst oranlarını ve olasılıkları getirir.\n"
        "/durum - Botun çalışma durumunu kontrol eder."
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

def extract_odds_value(data, keys):
    """Farklı API formatlarındaki oran değerlerini bulur"""
    for key in keys:
        if isinstance(data, dict) and key in data and data[key] is not None:
            return data[key]
    return "-"

async def maclar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not PINNODDS_API_KEY:
        await update.message.reply_text("❌ PinnOdds API anahtarı bulunamadı.")
        return

    await update.message.reply_text("⏳ Başlamamış maçlar ve oranlar analiz ediliyor...")
    try:
        import requests
        headers = {"x-portal-apikey": PINNODDS_API_KEY}
        
        # PinnOdds Pre-match Endpoint
        url = "https://pinnodds.com/api/drops?mode=prematch&sport_id=1&min_drop_pct=0&max_age_sec=86400"
        response = requests.get(url, headers=headers, timeout=12)
        
        if response.status_code == 200:
            res_json = response.json()
            
            if isinstance(res_json, dict):
                items = res_json.get("data", res_json.get("events", res_json.get("drops", [])))
            else:
                items = res_json

            if not items:
                await update.message.reply_text("⚠️ Görüntülenecek maç verisi bulunamadı.")
                return

            msg = "⚽ **GÜNCEL BAŞLAMAMIŞ MAÇLAR BÜLTENİ** ⚽\n"
            msg += "───────────────────\n\n"

            now = datetime.now(timezone.utc)
            count = 0

            for item in items:
                if count >= 5:
                    break

                # 1. Başlama zamanı kontrolü (Başlamış maçları eleme)
                match_time_str = item.get("starts_at", item.get("match_time", item.get("start_time")))
                if match_time_str:
                    try:
                        # ISO format çözümleme
                        clean_time = match_time_str.replace("Z", "+00:00")
                        match_dt = datetime.fromisoformat(clean_time)
                        if match_dt < now:
                            continue  # Maç başlamışsa atla
                    except Exception:
                        pass

                # Takım ve Lig bilgileri
                event = item.get("event", item)
                home = event.get("home_team", event.get("home", "Ev Sahibi"))
                away = event.get("away_team", event.get("away", "Deplasman"))
                league = event.get("league_name", event.get("league", "Futbol Ligi"))

                # Oran verileri (Derinlemesine arama)
                odds = item.get("odds", item)
                
                # 1X2 Oranları Çekme
                m1 = extract_odds_value(odds, ["home", "home_odds", "price_home", "1", "to"])
                mx = extract_odds_value(odds, ["draw", "draw_odds", "price_draw", "X"])
                m2 = extract_odds_value(odds, ["away", "away_odds", "price_away", "2"])
                
                # Eğer tekil drop nesnesinden geliyorsa:
                if m1 == "-" and item.get("selection") == "home":
                    m1 = item.get("to", "-")
                elif m2 == "-" and item.get("selection") == "away":
                    m2 = item.get("to", "-")

                # Olasılıklar
                p1 = calculate_prob(m1)
                px = calculate_prob(mx)
                p2 = calculate_prob(m2)

                # Alt / Üst Oranları
                o1_5 = extract_odds_value(odds, ["over_1_5", "o15", "over15"])
                u1_5 = extract_odds_value(odds, ["under_1_5", "u15", "under15"])
                
                o2_5 = extract_odds_value(odds, ["over_2_5", "o25", "over25"])
                u2_5 = extract_odds_value(odds, ["under_2_5", "u25", "under25"])
                
                o3_5 = extract_odds_value(odds, ["over_3_5", "o35", "over35"])
                u3_5 = extract_odds_value(odds, ["under_3_5", "u35", "under35"])

                msg += f"🏆 **{league}**\n"
                msg += f"⚔️ **{home} vs {away}**\n\n"
                
                msg += f"📊 **Kazanma Olasılıkları:**\n"
                msg += f"• Ev Sahibi: {p1} | Beraberlik: {px} | Deplasman: {p2}\n\n"
                
                msg += f"1️⃣ **MS (1X2) Oranları:**\n"
                msg += f"• MS 1: {m1} | MS X: {mx} | MS 2: {m2}\n\n"
                
                msg += f"⚽ **Alt / Üst Oranları:**\n"
                msg += f"• 1.5 Alt: {u1_5} | 1.5 Üst: {o1_5}\n"
                msg += f"• 2.5 Alt: {u2_5} | 2.5 Üst: {o2_5}\n"
                msg += f"• 3.5 Alt: {u3_5} | 3.5 Üst: {o3_5}\n"
                msg += "───────────────────\n\n"
                
                count += 1

            if count == 0:
                await update.message.reply_text("⚠️ Şu anda başlamamış bülten maçı bulunamadı.")
                return

            await update.message.reply_text(msg, parse_mode="Markdown")
        else:
            await update.message.reply_text(f"⚠️ API Hatası ({response.status_code}).")
    except Exception as e:
        await update.message.reply_text(f"❌ Bağlantı hatası: {str(e)}")

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

    print("Telegram botu başlatılıyor...")
    app.run_polling(drop_pending_updates=True, stop_signals=None)

if __name__ == "__main__":
    main()
