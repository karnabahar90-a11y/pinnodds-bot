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

def get_market_odds(periods):
    """PinnOdds V1 yapısından 1X2 ve Alt/Üst oranlarını çeker"""
    odds = {
        "1": "-", "X": "-", "2": "-",
        "o15": "-", "u15": "-",
        "o25": "-", "u25": "-",
        "o35": "-", "u35": "-"
    }
    
    if not periods or not isinstance(periods, dict):
        return odds

    # Genelde period 'num_0' veya '0' anahtarındadır (Match Full Time)
    match_period = periods.get("num_0", periods.get("0", list(periods.values())[0] if periods else {}))
    
    # 1. Moneyline / 1X2 Market
    moneyline = match_period.get("moneyline", {})
    if moneyline:
        odds["1"] = moneyline.get("home", "-")
        odds["X"] = moneyline.get("draw", "-")
        odds["2"] = moneyline.get("away", "-")

    # 2. Totals / Alt-Üst Marketleri
    totals = match_period.get("totals", {})
    if isinstance(totals, dict):
        for line, data in totals.items():
            line_str = str(line)
            if line_str == "1.5":
                odds["o15"] = data.get("over", "-")
                odds["u15"] = data.get("under", "-")
            elif line_str == "2.5":
                odds["o25"] = data.get("over", "-")
                odds["u25"] = data.get("under", "-")
            elif line_str == "3.5":
                odds["o35"] = data.get("over", "-")
                odds["u35"] = data.get("under", "-")
                
    return odds

async def maclar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not PINNODDS_API_KEY:
        await update.message.reply_text("❌ PinnOdds API anahtarı bulunamadı.")
        return

    await update.message.reply_text("⏳ Başlamamış maçlar, oranlar ve olasılıklar çekiliyor...")
    try:
        import requests
        # Ekran görüntünüzdeki Tam Doğru Endpoint Path
        url = "https://pinnodds.com/kit/v1/prematch/fixtures?sport_id=1"
        headers = {"x-portal-apikey": PINNODDS_API_KEY}
        
        response = requests.get(url, headers=headers, timeout=12)
        
        if response.status_code == 200:
            res_json = response.json()
            events = res_json.get("events", [])

            if not events:
                await update.message.reply_text("⚠️ Görüntülenecek maç verisi bulunamadı.")
                return

            msg = "⚽ **GÜNCEL BAŞLAMAMIŞ MAÇLAR BÜLTENİ** ⚽\n"
            msg += "───────────────────\n\n"

            now = datetime.now(timezone.utc)
            count = 0

            for event in events:
                if count >= 5: # Telegram sınırını zorlamamak için ilk 5 maç
                    break

                # Başlama saati kontrolü (Başlamış maçları eleme)
                starts_at = event.get("starts_at", event.get("starts", ""))
                if starts_at:
                    try:
                        clean_time = starts_at.replace("Z", "+00:00")
                        match_dt = datetime.fromisoformat(clean_time)
                        if match_dt < now:
                            continue  # Maç zaten başladıysa listeye alma
                    except Exception:
                        pass

                home = event.get("home", event.get("home_team", "Ev Sahibi"))
                away = event.get("away", event.get("away_team", "Deplasman"))
                league = event.get("league_name", event.get("league", "Futbol Ligi"))

                # Oranları Ayrıştır
                periods = event.get("periods", {})
                odds = get_market_odds(periods)

                # Kazanma Olasılıkları Hesapla
                p1 = calculate_prob(odds["1"])
                px = calculate_prob(odds["X"])
                p2 = calculate_prob(odds["2"])

                msg += f"🏆 **{league}**\n"
                msg += f"⚔️ **{home} vs {away}**\n\n"
                
                msg += f"📊 **Kazanma Olasılıkları:**\n"
                msg += f"• Ev Sahibi: {p1} | Beraberlik: {px} | Deplasman: {p2}\n\n"
                
                msg += f"1️⃣ **MS (1X2) Oranları:**\n"
                msg += f"• MS 1: {odds['1']} | MS X: {odds['X']} | MS 2: {odds['2']}\n\n"
                
                msg += f"⚽ **Alt / Üst Oranları:**\n"
                msg += f"• 1.5 Alt: {odds['u15']} | 1.5 Üst: {odds['o15']}\n"
                msg += f"• 2.5 Alt: {odds['u25']} | 2.5 Üst: {odds['o25']}\n"
                msg += f"• 3.5 Alt: {odds['u35']} | 3.5 Üst: {odds['o35']}\n"
                msg += "───────────────────\n\n"
                
                count += 1

            if count == 0:
                await update.message.reply_text("⚠️ Şu an için başlamamış bülten maçı kalmadı.")
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
