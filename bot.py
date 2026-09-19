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
        "/maclar - Yaklaşan başlamamış maçları saat sırasına göre getirir.\n"
        "/ara takım_adı - Belirttiğiniz takımın maçını ve oranlarını arar.\n"
        "Örnek: /ara Galatasaray\n"
        "/durum - Botun durumunu kontrol eder."
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

def parse_odds_deep(event):
    """Pinnacle API yanıtındaki 1X2 ve Alt/Üst oranlarını derinlemesine tarar"""
    odds = {
        "1": "-", "X": "-", "2": "-",
        "o15": "-", "u15": "-",
        "o25": "-", "u25": "-",
        "o35": "-", "u35": "-"
    }
    
    periods = event.get("periods", {})
    if isinstance(periods, dict):
        # Full Time dönemi: num_0, period_0, 0 veya ilk periyot
        p0 = periods.get("num_0", periods.get("period_0", periods.get("0", {})))
        if not p0 and len(periods) > 0:
            p0 = list(periods.values())[0]

        if isinstance(p0, dict):
            # 1X2 / Moneyline
            ml = p0.get("moneyline", p0.get("1x2", p0.get("win_draw_win", {})))
            if isinstance(ml, dict):
                odds["1"] = ml.get("home", ml.get("1", ml.get("h", "-")))
                odds["X"] = ml.get("draw", ml.get("x", ml.get("d", "-")))
                odds["2"] = ml.get("away", ml.get("2", ml.get("a", "-")))

            # Totals / Alt-Üst
            totals = p0.get("totals", p0.get("totals_line", {}))
            if isinstance(totals, dict):
                for line_key, data in totals.items():
                    line_str = str(line_key)
                    if isinstance(data, dict):
                        over_val = data.get("over", data.get("o", "-"))
                        under_val = data.get("under", data.get("u", "-"))
                        
                        if line_str in ["1.5", "15"]:
                            odds["o15"], odds["u15"] = over_val, under_val
                        elif line_str in ["2.5", "25"]:
                            odds["o25"], odds["u25"] = over_val, under_val
                        elif line_str in ["3.5", "35"]:
                            odds["o35"], odds["u35"] = over_val, under_val

    # Eğer ana objede doğrudan oran varsa yedek kontrol:
    if odds["1"] == "-":
        odds["1"] = event.get("home_price", event.get("price_home", "-"))
        odds["X"] = event.get("draw_price", event.get("price_draw", "-"))
        odds["2"] = event.get("away_price", event.get("price_away", "-"))

    return odds

def fetch_and_sort_matches():
    """API'den verileri çeker, başlamış maçları eler ve saat sırasına dizer"""
    import requests
    url = "https://pinnodds.com/kit/v1/prematch/fixtures?sport_id=1"
    headers = {"x-portal-apikey": PINNODDS_API_KEY}
    
    response = requests.get(url, headers=headers, timeout=12)
    if response.status_code != 200:
        return None, response.status_code

    res_json = response.json()
    events = res_json.get("events", [])
    now = datetime.now(timezone.utc)
    valid_events = []

    for ev in events:
        starts_at = ev.get("starts_at", ev.get("starts", ev.get("start_time", "")))
        match_dt = None
        if starts_at:
            try:
                clean_time = starts_at.replace("Z", "+00:00")
                match_dt = datetime.fromisoformat(clean_time)
            except Exception:
                pass
        
        # Başlamamış maç filtresi
        if match_dt and match_dt < now:
            continue
        
        ev["parsed_dt"] = match_dt
        valid_events.append(ev)

    # Saate göre kronolojik sırala (En yakın maç en üstte)
    valid_events.sort(key=lambda x: x["parsed_dt"] if x["parsed_dt"] else datetime.max.replace(tzinfo=timezone.utc))
    return valid_events, 200

def format_match_message(match):
    home = match.get("home", match.get("home_team", "Ev Sahibi"))
    away = match.get("away", match.get("away_team", "Deplasman"))
    league = match.get("league_name", match.get("league", "Futbol Ligi"))
    
    match_time_str = "Bilinmiyor"
    if match.get("parsed_dt"):
        match_time_str = match["parsed_dt"].strftime("%H:%M (%d.%m.%Y)")

    odds = parse_odds_deep(match)
    p1 = calculate_prob(odds["1"])
    px = calculate_prob(odds["X"])
    p2 = calculate_prob(odds["2"])

    msg = f"⏰ **Saat:** {match_time_str}\n"
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
    msg += "───────────────────\n"
    return msg

async def maclar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not PINNODDS_API_KEY:
        await update.message.reply_text("❌ PinnOdds API anahtarı bulunamadı.")
        return

    await update.message.reply_text("⏳ Yaklaşan başlamamış maçlar saat sırasına göre yükleniyor...")
    try:
        events, status = fetch_and_sort_matches()
        if status != 200 or events is None:
            await update.message.reply_text(f"⚠️ API Hatası ({status}).")
            return

        if not events:
            await update.message.reply_text("⚠️ Görüntülenecek başlamamış maç bulunamadı.")
            return

        msg = "⚽ **YAKLAŞAN BAŞLAMAMIŞ MAÇLAR (SAAT SIRALI)** ⚽\n"
        msg += "───────────────────\n\n"

        for match in events[:5]:  # İlk 5 en yakın maç
            msg += format_match_message(match) + "\n"

        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Hata oluştu: {str(e)}")

async def ara(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not PINNODDS_API_KEY:
        await update.message.reply_text("❌ PinnOdds API anahtarı bulunamadı.")
        return

    if not context.args:
        await update.message.reply_text("⚠️ Lütfen aramak istediğiniz takımın adını yazın.\nÖrnek: `/ara Galatasaray`", parse_mode="Markdown")
        return

    query = " ".join(context.args).lower()
    await update.message.reply_text(f"🔍 '{query}' için başlamamış maçlar aranıyor...")

    try:
        events, status = fetch_and_sort_matches()
        if status != 200 or events is None:
            await update.message.reply_text(f"⚠️ API Hatası ({status}).")
            return

        matched_events = []
        for ev in events:
            home = str(ev.get("home", ev.get("home_team", ""))).lower()
            away = str(ev.get("away", ev.get("away_team", ""))).lower()
            if query in home or query in away:
                matched_events.append(ev)

        if not matched_events:
            await update.message.reply_text(f"🔍 '{query}' ismiyle eşleşen başlamamış maç bulunamadı.")
            return

        msg = f"🔎 **Arama Sonuçları ({query.upper()})** 🔎\n"
        msg += "───────────────────\n\n"

        for match in matched_events[:5]:
            msg += format_match_message(match) + "\n"

        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Arama hatası: {str(e)}")

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

    print("Telegram botu başlatılıyor...")
    app.run_polling(drop_pending_updates=True, stop_signals=None)

if __name__ == "__main__":
    main()
