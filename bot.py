import os
import logging
import threading
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Logging ayarları
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PINNODDS_API_KEY = os.getenv("PINNODDS_API_KEY")

# Render Web Service port kontrolü için Flask sunucusu
app_flask = Flask(__name__)

@app_flask.route('/')
def health_check():
    return "Bot is running!", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host="0.0.0.0", port=port)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 PinnOdds Botuna Hoş Geldiniz!\n\n"
        "Kullanılabilir komutlar:\n"
        "/oranlar - Güncel PinnOdds oranlarını getirir.\n"
        "/durum - Botun çalışma durumunu kontrol eder."
    )

async def durum(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Bot Render üzerinde 7/24 sorunsuz çalışıyor!")

async def oranlar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not PINNODDS_API_KEY:
        await update.message.reply_text("❌ PinnOdds API anahtarı sistemde bulunamadı.")
        return

    await update.message.reply_text("⏳ PinnOdds verileri çekiliyor, lütfen bekleyin...")
    try:
        import requests
        url = "https://api.pinnodds.com/v1/odds"
        headers = {"x-api-key": PINNODDS_API_KEY}
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            await update.message.reply_text(f"📊 Veriler başarıyla çekildi!\n\nPayload: {str(data)[:300]}...")
        else:
            await update.message.reply_text(f"⚠️ PinnOdds API hatası: {response.status_code}")
    except Exception as e:
        await update.message.reply_text(f"❌ Bir hata oluştu: {str(e)}")

def main():
    if not TELEGRAM_BOT_TOKEN:
        print("HATA: TELEGRAM_BOT_TOKEN bulunamadı!")
        return

    # Flask web sunucusunu arka planda başlat
    threading.Thread(target=run_flask, daemon=True).start()

    # Telegram bot uygulamasını başlat
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("durum", durum))
    app.add_handler(CommandHandler("oranlar", oranlar))

    print("Bot çalışıyor...")
    app.run_polling()

if __name__ == "__main__":
    main()
