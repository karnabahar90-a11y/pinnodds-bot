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
        "/ara takım_adı - Belirttiğiniz takımın maçını arar (Örn: /ara Luton).\n"
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

def extract_odds(event):
    """PinnOdds V1 API yanıtından 1X2 Moneyline ve Totals (Alt/Üst) oranlarını çıkarır"""
    odds = {
        "1": "-", "X": "-", "2": "-",
        "o15": "-", "u15": "-",
        "o25": "-", "u25": "-",
        "o35": "-", "u35": "-"
    }
    
    # 1. Periyotlar Üzerinden Tarama (num_0 = Maç Sonu)
    periods = event.get("periods", {})
    p0 = {}
    if isinstance(periods, dict):
        p0 = periods.get("num_0", periods.get("0", periods.get("period_0", {})))
        if not p0 and len(periods) > 0:
            p0 = list(periods.values())[0]

    # Moneyline / 1X2 Oranları
    moneyline = p0.get("moneyline", event.get("moneyline", {}))
    if isinstance(moneyline, dict) and moneyline:
        odds["1"] = moneyline.get("home", moneyline.get("1", "-"))
        odds["X"] = moneyline.get("draw", moneyline.get("x", "-"))
        odds["2"] = moneyline.get("away", moneyline.get("2", "-"))

    # Alt / Üst Oranları
    totals = p0.get("totals", event.get("totals", {}))
    if isinstance(totals, dict) and totals:
        for line, data in totals.items():
            line_str = str(line)
            if isinstance(data, dict):
                over_val = data.get("over", data.get("o", "-"))
                under_val = data.get("under", data.get("u", "-"))
                
                if line_str in ["1.5", "15"]:
                    odds["o15"], odds["u15"] = over_val, under_val
                elif line_str in ["2.5", "25"]:
                    odds["o25"], odds["u25"] = over_val, under_val
                elif line_str in ["3.5", "35"]:
                    odds["o35"], odds["u35"] = over_val, under_val

    # Yedek Kontrol: Eğer Ana Objede Doğrudan 1X2 Varsa
    if odds["1"] == "-":
        odds["1"] = event.get("home_price", event.get("price_home", "-"))
        odds["X"] = event.get("draw_price", event.get("price_draw", "-"))
        odds["2"] = event.get("away_price", event.get("price_away", "-"))

    return odds

def fetch_and_sort_matches():
    """API'den maçları çeker, başlamış maçları süzüp en yakın saate göre kronolojik dizer"""
    import requests
    # PinnOdds API V1 prematch adresi
    url = "https://pinnodds.com/kit/v1/prematch/fixtures?sport_id=1&include_specials=1"
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
        
        # Başlamış maçları filtrele
        if match_dt and match_dt < now:
            continue
        
        ev["parsed_dt"] = match_dt
        valid_events.append(ev)

    # Saat sırasına göre diz (En yakın maç en üstte)
    valid_events.sort(key=lambda x: x["parsed_dt"] if x["parsed_dt"] else datetime.max.replace(tzinfo=timezone.utc))
    return valid_events, 200

def build_match_card(match):
    home = match.get("home", match.get("home_team", "Ev Sahibi"))
    away = match.get("away", match.get("away_team", "Deplasman"))
    league = match.get("league_name", match.get("league", "Futbol Ligi"))
    
    time_str = "Saat Bilinmiyor"
    if match.get("parsed_dt"):
        time_str = match["parsed_dt"].strftime("%H:%M (%d.%m.%Y)")

    odds = extract_odds(match)
    p1 = calculate_prob(odds["1"])
    px = calculate_prob(odds["X"])
    p2 = calculate_prob(odds["2"])

    card = f"⏰ **Saat:** {time_str}\n"
    card += f"🏆 **{league}**\n"
    card += f"⚔️ **{home} vs {away}**\n\n"
    card += f"📊 **Kazanma Olasılıkları:**\n"
    card += f"• Ev Sahibi: {p1} | Beraberlik: {px} | Deplasman: {p2}\n\n"
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
        await update.message.reply_text("❌ PinnOdds API anahtarı ayarlanmamış.")
        return

    await update.message.reply_text("⏳ Sıradaki en yakın maçlar çekiliyor...")
    try:
        events, status = fetch_and_sort_matches()
        if status != 200 or events is None:
            await update.message.reply_text(f"⚠️ API Hatası ({status}).")
            return

        if not events:
            await update.message.reply_text("⚠️ Görüntülenecek başlamamış maç kalmadı.")
            return

        msg = "⚽ **YAKLAŞAN MAÇLAR (SAAT SIRALI)** ⚽\n"
        msg += "───────────────────\n\n"

        for match in events[:5]:  # En yakın ilk 5 maç
            msg += build_match_card(match) + "\n"

        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Hata: {str(e)}")

async def ara(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not PINNODDS_API_KEY:
        await update.message.reply_text("❌ PinnOdds API anahtarı ayarlanmamış.")
        return

    if not context.args:
        await update.message.reply_text("⚠️ Takım adı girmelisiniz.\nÖrnek: `/ara Luton`", parse_mode="Markdown")
        return

    query = " ".join(context.args).lower()
    await update.message.reply_text(f"🔍 '{query}' maçı aranıyor...")

    try:
        events, status = fetch_and_sort_matches()
        if status != 200 or events is None:
            await update.message.reply_text(f"⚠️ API Hatası ({status}).")
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
            msg += build_match_card(match) + "\n"

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
