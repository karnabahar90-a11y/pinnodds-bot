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
        # FİLTRELER ESNETİLDİ: min_drop_pct=0.5 (Yarım puanlık düşüş) ve max_age_sec=86400 (Son 24 saat)
        url = "https://pinnodds.com/api/drops?mode=prematch&sport_id=1&min_drop_pct=0.5&max_age_sec=86400"
        headers = {"x-portal-apikey": PINNODDS_API_KEY}
        
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            # Eğer veri doğrudan liste değil de dict içinde geliyorsa güvenli şekilde çıkar
            if isinstance(data, dict):
                data = data.get("data", data.get("drops", []))
            
            if not data or len(data) == 0:
                await update.message.reply_text("⚠️ Şu an için son 24 saatte %0.5'ten fazla düşen oran yok.")
                return

            msg = "⚽ **DÜŞEN ORANLAR (Son 24 Saat)** ⚽\n\n"
            for item in data[:10]:  # İlk 10 maçı göster
                # API takım isimlerini "event" objesi içinde gönderiyorsa diye güvenlik eklendi
                event_data = item.get("event", item)
                
                home = event_data.get("home_team", event_data.get("home", "Ev Sahibi"))
                away = event_data.get("away_team", event_data.get("away", "Deplasman"))
                drop_pct = item.get("drop_pct", "0")
                to_val = item.get("to", "-")
                
                msg += f"🔹 **{home} vs {away}**\n"
                msg += f"📉 Düşüş: %{drop_pct} | Yeni Oran: {to_val}\n\n"

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
    app.add_handler(CommandHandler("oranlar", oranlar))

    print("Telegram botu başlatılıyor...")
    app.run_polling(drop_pending_updates=True, stop_signals=None)

if __name__ == "__main__":
    main()
