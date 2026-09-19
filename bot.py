import os
import logging
import threading
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

async def maclar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not PINNODDS_API_KEY:
        await update.message.reply_text("❌ PinnOdds API anahtarı bulunamadı.")
        return

    await update.message.reply_text("⏳ Başlamamış maçlar ve oranlar çekiliyor...")
    try:
        import requests
        
        # PinnOdds API Prematch Fikstür & Oran Servisi
        headers = {"x-portal-apikey": PINNODDS_API_KEY}
        
        # 1. Öncelikli endpoint: Pre-match drops / fixtures
        url = "https://pinnodds.com/api/drops?mode=prematch&sport_id=1&min_drop_pct=0&max_age_sec=86400"
        response = requests.get(url, headers=headers, timeout=12)
        
        if response.status_code != 200:
            # Alternatif endpoint denemesi
            url = "https://pinnodds.com/api/fixtures?sport_id=1"
            response = requests.get(url, headers=headers, timeout=12)

        if response.status_code == 200:
            data = response.json()
            
            if isinstance(data, dict):
                fixtures = data.get("data", data.get("events", data.get("fixtures", data.get("drops", []))))
            else:
                fixtures = data

            if not fixtures:
                await update.message.reply_text("⚠️ Şu anda görüntülenecek aktif maç verisi bulunamadı.")
                return

            msg = "⚽ **GÜNCEL MAÇ BÜLTENİ VE ANALİZİ** ⚽\n"
            msg += "───────────────────\n\n"

            count = 0
            for match in fixtures:
                if count >= 5:  # Telegram mesaj sınırını aşmamak için 5 maç
                    break

                home = match.get("home_team", match.get("home", "Ev Sahibi"))
                away = match.get("away_team", match.get("away", "Deplasman"))
                league = match.get("league_name", match.get("league", "Futbol Ligi"))
                
                # Oran objesi
                odds = match.get("odds", match)
                
                # 1X2 Oranları
                m1 = odds.get("home", odds.get("1", odds.get("price_home", "-")))
                mx = odds.get("draw", odds.get("X", odds.get("price_draw", "-")))
                m2 = odds.get("away", odds.get("2", odds.get("price_away", "-")))
                
                # Olasılıklar (%)
                p1 = calculate_prob(m1)
                px = calculate_prob(mx)
                p2 = calculate_prob(m2)
                
                # Alt / Üst Seçenekleri (1.5, 2.5, 3.5)
                u1_5 = odds.get("under_1_5", odds.get("u15", "-"))
                o1_5 = odds.get("over_1_5", odds.get("o15", "-"))
                
                u2_5 = odds.get("under_2_5", odds.get("u25", "-"))
                o2_5 = odds.get("over_2_5", odds.get("o25", "-"))
                
                u3_5 = odds.get("under_3_5", odds.get("u35", "-"))
                o3_5 = odds.get("over_3_5", odds.get("o35", "-"))

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

            await update.message.reply_text(msg, parse_mode="Markdown")
        else:
            await update.message.reply_text(f"⚠️ API Hatası ({response.status_code}): Lütfen API endpoint izinlerinizi kontrol edin.")
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
