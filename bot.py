import os
import logging
import threading
import asyncio
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
        "👋 PinnOdds Botuna Hoş Geldiniz!\n\n"
        "Komutlar:\n"
        "/oranlar - Güncel düşen oranları ve maçları getirir.\n"
        "/durum - Botun çalışma durumunu kontrol eder."
    )

async def durum(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Bot Render üzerinde 7/24 aktif çalışıyor!")

async def oranlar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not PINNODDS_API_KEY:
        await update.message.reply_text("❌ PinnOdds API anahtarı sistemde bulunamadı.")
        return

    await update.message.reply_text("⏳ Pinnacle Düşen Oran Verileri Çekiliyor...")
    try:
        import requests
        # PinnacleOddsAPI doğru endpoint ve header kullanımı
        url = "https://pinnodds.com/api/drops?mode=prematch&sport_id=1&min_drop_pct=2&max_age_sec=10800"
        headers = {"x-portal-apikey": PINNODDS_API_KEY}
        
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            if not data or not isinstance(data, list):
                await update.message.reply_text("⚠️ Şu anda aktif düşen oran verisi bulunamadı.")
                return

            msg = "⚽ **DÜŞEN ORANLAR (Prematch Drops)** ⚽\n\n"
            for item in data[:8]:  # İlk 8 maçı göster
                home = item.get("home_team", item.get("home", "Ev Sahibi"))
                away = item.get("away_team", item.get("away", "Deplasman"))
                drop_pct = item.get("drop_pct", "0")
                to_val = item.get("to", "-")
                
                msg += f"🔹 **{home} vs {away}**\n"
                msg += f"📉 Düşüş: %{drop_pct} | Yeni Oran: {to_val}\n\n"

            await update.message.reply_text(msg, parse_mode="Markdown")
        else:
            await update.message.reply_text(f"⚠️ API Hatası ({response.status_code}): Lütfen API anahtarını kontrol edin.")
    except Exception as e:
        await update.message.reply_text(f"❌ Bağlantı hatası: {str(e)}")

def run_telegram_bot():
    if not TELEGRAM_BOT_TOKEN:
        print("HATA: TELEGRAM_BOT_TOKEN bulunamadı!")
        return

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("durum", durum))
    app.add_handler(CommandHandler("oranlar", oranlar))

    app.run_polling(drop_pending_updates=True, close_loop=False)

if __name__ == "__main__":
    bot_thread = threading.Thread(target=run_telegram_bot)
    bot_thread.daemon = True
    bot_thread.start()

    run_flask()
