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
        "/maclar - Yaklaşan başlamamış maçları, 1X2 oranlarını ve yüzde olasılıklarını getirir.\n"
        "/ara takım_adı - Belirttiğiniz takımın maçını ve oranlarını arar.\n"
        "/durum - Botun aktiflik durumunu kontrol eder."
    )

async def durum(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Bot Render üzerinde 7/24 aktif çalışıyor!")

def calculate_prob(odd):
    """Orandan yüzde olasılık hesaplama"""
    try:
        val = float(odd)
        if val > 1.0:
            prob = (1 / val) * 100
            return f"%{round(prob, 1)}"
    except (ValueError, TypeError):
        pass
    return "-"

def get_complete_odds(event):
    """1X2 ve Alt/Üst oranlarını API yanıtından eksiksiz çeker"""
    odds = {
        "1": "-", "X": "-", "2": "-",
        "o15": "-", "u15": "-",
        "o25": "-", "u25": "-",
        "o35": "-", "u35": "-"
    }
    
    # 1. Objenin doğrudan üzerindeki anahtar kontrolleri
    if "home_odds" in event: odds["1"] = event["home_odds"]
    if "draw_odds" in event: odds["X"] = event["draw_odds"]
    if "away_odds" in event: odds["2"] = event["away_odds"]

    # 2. Periyot taraması (num_0 / period_0 = Maç Sonu)
    periods = event.get("periods", event.get("markets", {}))
    if isinstance(periods, dict):
        p0 = periods.get("num_0", periods.get("0", periods.get("period_0", {})))
        if not p0 and len(periods) > 0:
            p0 = list(periods.values())[0]

        if isinstance(p0, dict):
            # Moneyline (1X2)
            ml = p0.get("moneyline", p0.get("1x2", p0.get("win_draw_win", {})))
            if isinstance(ml, dict):
                if odds["1"] == "-": odds["1"] = ml.get("home", ml.get("1", "-"))
                if odds["X"] == "-": odds["X"] = ml.get("draw", ml.get("x", "-"))
                if odds["2"] == "-": odds["2"] = ml.get("away", ml.get("2", "-"))

            # Totals (Alt / Üst)
            totals = p0.get("totals", {})
            if isinstance(totals, dict):
                for line_key, data in totals.items():
                    line_str = str(line_key)
                    if isinstance(data, dict):
                        o_val = data.get("over", "-")
                        u_val = data.get("under", "-")
                        if line_str in ["1.5", "15"]:
                            odds["o15"], odds["u15"] = o_val, u_val
                        elif line_str in ["2.5", "25"]:
                            odds["o25"], odds["u25"] = o_val, u_val
                        elif line_str in ["3.5", "35"]:
                            odds["o35"], odds["u35"] = o_val, u_val

    return odds

def fetch_and_sort_matches():
    import requests
    headers = {"x-portal-apikey": PINNODDS_API_KEY}
    
    # Drops Endpoint'i 1X2 Oranlarını Tam Verir
    url = "https://pinnodds.com/api/drops?mode=prematch&sport_id=1&min_drop_pct=0&max_age_sec=86400"
    response = requests.get(url, headers=headers, timeout=10)
    
    events = []
    if response.status_code == 200:
        res_json = response.json()
        events = res_json.get("data", res_json.get("events", res_json.get("drops", [])))
    else:
        # Yedek Fikstür Endpoint'i
        url_alt = "https://pinnodds.com/kit/v1/prematch/fixtures?sport_id=1"
        res_alt = requests.get(url_alt, headers=headers, timeout=10)
        if res_alt.status_code == 200:
            events = res_alt.json().get("events", [])

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
        
        # Başlamış maçları filtrele
        if match_dt and match_dt < now:
            continue
        
        ev["parsed_dt"] = match_dt
        valid_events.append(ev)

    # Saat sırasına göre kronolojik diz (En yakın maç en üstte)
    valid_events.sort(key=lambda x: x["parsed_dt"] if x["parsed_dt"] else datetime.max.replace(tzinfo=timezone.utc))
    return valid_events, 200

def format_match_card(match):
    home = match.get("home", match.get("home_team", "Ev Sahibi"))
    away = match.get("away", match.get("away_team", "Deplasman"))
    league = match.get("league_name", match.get("league", "Futbol Ligi"))
    
    time_str = "Saat Bilinmiyor"
    if match.get("parsed_dt"):
        time_str = match["parsed_dt"].strftime("%H:%M (%d.%m.%Y)")

    odds = get_complete_odds(match)
    
    # Gerçekleşecek Senaryoların Olasılık Yüzdeleri
    p1 = calculate_prob(odds["1"])
    px = calculate_prob(odds["X"])
    p2 = calculate_prob(odds["2"])

    card = f"⏰ **Saat:** {time_str}\n"
    card += f"🏆 **{league}**\n"
    card += f"⚔️ **{home} vs {away}**\n\n"
    card += f"📊 **Gerçekleşme Olasılık Yüzdeleri:**\n"
    card += f"• Ev Sahibi Galibiyeti: **{p1}**\n"
    card += f"• Beraberlik: **{px}**\n"
    card += f"• Deplasman Galibiyeti: **{p2}**\n\n"
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
        await update.message.reply_text("❌ PINNODDS_API_KEY tanımlı değil.")
        return

    await update.message.reply_text("⏳ Yaklaşan maçlar ve olasılık yüzdeleri hesaplanıyor...")
    try:
        events, status = fetch_and_sort_matches()
        if status != 200 or not events:
            await update.message.reply_text("⚠️ Görüntülenecek başlamamış maç verisi bulunamadı.")
            return

        msg = "⚽ **YAKLAŞAN MAÇLAR VE OLASILIK YÜZDELERİ** ⚽\n"
        msg += "───────────────────\n\n"

        for match in events[:5]:
            msg += format_match_card(match) + "\n"

        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Bağlantı hatası: {str(e)}")

async def ara(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not PINNODDS_API_KEY:
        await update.message.reply_text("❌ PINNODDS_API_KEY tanımlı değil.")
        return

    if not context.args:
        await update.message.reply_text("⚠️ Lütfen bir takım adı yazın.\nÖrnek: `/ara Puebla`", parse_mode="Markdown")
        return

    query = " ".join(context.args).lower()
    await update.message.reply_text(f"🔍 '{query}' aranıyor...")

    try:
        events, status = fetch_and_sort_matches()
        if status != 200 or not events:
            await update.message.reply_text("⚠️ Maç verisi bulunamadı.")
            return

        matches = []
        for ev in events:
            home = str(ev.get("home", ev.get("home_team", ""))).lower()
            away = str(ev.get("away", ev.get("away_team", ""))).lower()
            if query in home or query in away:
                matches.append(ev)

        if not matches:
            await update.message.reply_text(f"🔍 '{query}' takımı için başlamamış maç bulunamadı.")
            return

        msg = f"🔎 **ARAMA SONUÇLARI ({query.upper()})** 🔎\n"
        msg += "───────────────────\n\n"

        for match in matches[:5]:
            msg += format_match_card(match) + "\n"

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

    print("Telegram botu başlatılıyor...")
    app.run_polling(drop_pending_updates=True, stop_signals=None)

if __name__ == "__main__":
    main()
