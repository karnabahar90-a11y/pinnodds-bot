import os
import logging
import threading
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

import requests
from flask import Flask
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

# =========================================================
# AYARLAR
# =========================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
PINNODDS_API_KEY = os.getenv("PINNODDS_API_KEY", "").strip()

PINNODDS_URL = "https://pinnodds.com/kit/v1/prematch/fixtures?sport_id=1"
TR_TZ = timezone(timedelta(hours=3))

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("pinnodds_bot")

app_flask = Flask(__name__)


# =========================================================
# HEALTH CHECK
# =========================================================

@app_flask.route("/")
def health_check():
    return "PinnOdds Telegram Bot is running!", 200


@app_flask.route("/health")
def health():
    return {"status": "ok", "bot": "pinnodds"}, 200


# =========================================================
# YARDIMCI FONKSİYONLAR
# =========================================================

def as_text(value: Any, default: str = "-") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def first_value(data: Dict[str, Any], keys: List[str], default: Any = None) -> Any:
    for key in keys:
        value = data.get(key)
        if value is not None and value != "":
            return value
    return default


def calculate_prob(odd: Any) -> str:
    try:
        value = float(odd)
        if value > 1.0:
            return f"%{round((1.0 / value) * 100, 1)}"
    except (ValueError, TypeError):
        pass
    return "-"


def calculate_ou_prob(over_odd: Any, under_odd: Any) -> Tuple[str, str]:
    try:
        over = float(over_odd)
        under = float(under_odd)

        if over > 1.0 and under > 1.0:
            p_over = 1.0 / over
            p_under = 1.0 / under
            total = p_over + p_under

            return (
                f"%{round((p_over / total) * 100, 1)}",
                f"%{round((p_under / total) * 100, 1)}",
            )
    except (ValueError, TypeError, ZeroDivisionError):
        pass

    return "-", "-"


def parse_match_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None

    try:
        text = str(value).strip()

        if text.endswith("Z"):
            text = text[:-1] + "+00:00"

        dt = datetime.fromisoformat(text)

        if dt.tzinfo is None:
            # API timezone vermiyorsa UTC kabul ediyoruz.
            dt = dt.replace(tzinfo=timezone.utc)

        return dt.astimezone(TR_TZ)
    except (ValueError, TypeError):
        return None


def is_bad_market_name(value: Any) -> bool:
    text = as_text(value, "").lower()
    return any(word in text for word in ("corner", "corners", "booking", "cards"))


# =========================================================
# ORAN AYIKLAMA
# =========================================================

def extract_odds_safely(ev: Dict[str, Any]) -> Dict[str, str]:
    odds = {
        "1": "-",
        "X": "-",
        "2": "-",
        "o15": "-",
        "u15": "-",
        "o25": "-",
        "u25": "-",
        "o35": "-",
        "u35": "-",
    }

    # Maç/lig adı üzerinden köşe/korner/kart pazarlarını ele.
    league_name = as_text(
        first_value(ev, ["league_name", "league", "competition_name"], ""),
        "",
    ).lower()

    if is_bad_market_name(league_name):
        return odds

    home_name = as_text(first_value(ev, ["home", "home_team"], ""), "").lower()
    away_name = as_text(first_value(ev, ["away", "away_team"], ""), "").lower()

    if is_bad_market_name(home_name) or is_bad_market_name(away_name):
        return odds

    # -----------------------------------------------------
    # Doğrudan alanlar
    # -----------------------------------------------------
    odds["1"] = as_text(
        first_value(ev, ["home_price", "home_odds", "price_home", "home_win", "1"]),
        "-",
    )
    odds["X"] = as_text(
        first_value(ev, ["draw_price", "draw_odds", "price_draw", "draw", "x", "X"]),
        "-",
    )
    odds["2"] = as_text(
        first_value(ev, ["away_price", "away_odds", "price_away", "away_win", "2"]),
        "-",
    )

    # -----------------------------------------------------
    # periods -> num_0
    # -----------------------------------------------------
    periods = ev.get("periods", {})
    if isinstance(periods, dict):
        p0 = periods.get("num_0", periods.get("0", {}))

        if isinstance(p0, dict):
            ml = p0.get(
                "money_line",
                p0.get("moneyline", p0.get("1x2", {})),
            )

            if isinstance(ml, dict):
                if odds["1"] == "-":
                    odds["1"] = as_text(
                        first_value(ml, ["home", "1"]), "-"
                    )
                if odds["X"] == "-":
                    odds["X"] = as_text(
                        first_value(ml, ["draw", "x", "X"]), "-"
                    )
                if odds["2"] == "-":
                    odds["2"] = as_text(
                        first_value(ml, ["away", "2"]), "-"
                    )

            if odds["1"] == "-" and p0.get("home") not in (None, ""):
                odds["1"] = as_text(p0.get("home"))
            if odds["X"] == "-" and p0.get("draw") not in (None, ""):
                odds["X"] = as_text(p0.get("draw"))
            if odds["2"] == "-" and p0.get("away") not in (None, ""):
                odds["2"] = as_text(p0.get("away"))

            totals = p0.get("totals", p0.get("over_under", {}))

            if isinstance(totals, dict):
                for line, tdata in totals.items():
                    if not isinstance(tdata, dict):
                        continue

                    line_text = str(line).strip()
                    over = first_value(tdata, ["over", "o"], "-")
                    under = first_value(tdata, ["under", "u"], "-")

                    if line_text in ("1.5", "15"):
                        odds["o15"] = as_text(over)
                        odds["u15"] = as_text(under)
                    elif line_text in ("2.5", "25"):
                        odds["o25"] = as_text(over)
                        odds["u25"] = as_text(under)
                    elif line_text in ("3.5", "35"):
                        odds["o35"] = as_text(over)
                        odds["u35"] = as_text(under)

    # -----------------------------------------------------
    # markets
    # -----------------------------------------------------
    markets = ev.get("markets", {})

    if isinstance(markets, dict):
        ml = markets.get(
            "moneyline",
            markets.get("money_line", markets.get("1x2", {})),
        )

        if isinstance(ml, dict):
            if odds["1"] == "-":
                odds["1"] = as_text(first_value(ml, ["home", "1"]), "-")
            if odds["X"] == "-":
                odds["X"] = as_text(first_value(ml, ["draw", "x", "X"]), "-")
            if odds["2"] == "-":
                odds["2"] = as_text(first_value(ml, ["away", "2"]), "-")

    return odds


# =========================================================
# PINNODDS API
# =========================================================

def fetch_data() -> List[Dict[str, Any]]:
    if not PINNODDS_API_KEY:
        logger.error("PINNODDS_API_KEY bulunamadı.")
        return []

    headers = {
        "x-portal-apikey": PINNODDS_API_KEY,
        "Accept": "application/json",
        "User-Agent": "PinnOddsTelegramBot/1.0",
    }

    try:
        response = requests.get(
            PINNODDS_URL,
            headers=headers,
            timeout=(5, 20),
        )

        if response.status_code != 200:
            logger.error(
                "PinnOdds HTTP hatası: %s - %s",
                response.status_code,
                response.text[:500],
            )
            return []

        data = response.json()

        if isinstance(data, dict):
            events = data.get("events", [])
        elif isinstance(data, list):
            events = data
        else:
            logger.error("Beklenmeyen API JSON formatı: %s", type(data))
            return []

        if not isinstance(events, list):
            logger.error("API 'events' alanı liste değil.")
            return []

        now = datetime.now(TR_TZ)
        valid: List[Dict[str, Any]] = []

        for ev in events:
            if not isinstance(ev, dict):
                continue

            starts_at = first_value(
                ev,
                ["starts_at", "starts", "start_time", "kickoff"],
            )

            match_dt = parse_match_datetime(starts_at)

            # Başlangıç zamanı okunamıyorsa listeye alma.
            if match_dt is None:
                continue

            # Başlamış/geçmiş maçları alma.
            if match_dt <= now:
                continue

            odds = extract_odds_safely(ev)

            # 1X2'nin tamamı yoksa listeye alma.
            if any(odds[key] == "-" for key in ("1", "X", "2")):
                continue

            ev["parsed_dt"] = match_dt
            ev["extracted_odds"] = odds
            valid.append(ev)

        # Aynı maçın tekrarlarını temizle.
        # Aynı takım + başlangıç zamanı üzerinden gruplanır.
        unique: Dict[Tuple[str, str, str], Dict[str, Any]] = {}

        for ev in valid:
            home = as_text(first_value(ev, ["home", "home_team"], ""), "").lower()
            away = as_text(first_value(ev, ["away", "away_team"], ""), "").lower()
            dt = ev["parsed_dt"].isoformat()

            key = (home, away, dt)

            if key not in unique:
                unique[key] = ev
                continue

            # Tekrarlı kayıtta daha dolu oran setini tercih et.
            old = unique[key]
            old_odds = old.get("extracted_odds", {})
            new_odds = ev.get("extracted_odds", {})

            old_count = sum(v != "-" for v in old_odds.values())
            new_count = sum(v != "-" for v in new_odds.values())

            if new_count > old_count:
                unique[key] = ev

        valid = list(unique.values())
        valid.sort(key=lambda item: item["parsed_dt"])

        logger.info(
            "API toplam etkinlik: %s | geçerli gelecek maç: %s",
            len(events),
            len(valid),
        )

        return valid

    except requests.RequestException as exc:
        logger.error("PinnOdds bağlantı hatası: %s", exc)
        return []
    except ValueError as exc:
        logger.error("API JSON okuma hatası: %s", exc)
        return []
    except Exception:
        logger.exception("fetch_data beklenmeyen hata")
        return []


# =========================================================
# TELEGRAM MESAJLARI
# =========================================================

def build_card(match: Dict[str, Any]) -> str:
    home = as_text(first_value(match, ["home", "home_team"]), "Ev Sahibi")
    away = as_text(first_value(match, ["away", "away_team"]), "Deplasman")
    league = as_text(
        first_value(match, ["league_name", "league", "competition_name"]),
        "Futbol Ligi",
    )

    parsed_dt = match.get("parsed_dt")
    time_str = (
        parsed_dt.strftime("%H:%M (%d.%m.%Y)")
        if isinstance(parsed_dt, datetime)
        else "Bilinmiyor"
    )

    odds = match.get("extracted_odds", extract_odds_safely(match))

    p1 = calculate_prob(odds["1"])
    px = calculate_prob(odds["X"])
    p2 = calculate_prob(odds["2"])

    o15_p, u15_p = calculate_ou_prob(odds["o15"], odds["u15"])
    o25_p, u25_p = calculate_ou_prob(odds["o25"], odds["u25"])
    o35_p, u35_p = calculate_ou_prob(odds["o35"], odds["u35"])

    # HTML parse mode kullanıldığı için takım/lig isimleri Markdown
    # karakterleri yüzünden mesajı bozmaz.
    from html import escape

    return (
        f"⏰ <b>Saat:</b> {escape(time_str)}\n"
        f"🏆 <b>{escape(league)}</b>\n"
        f"⚔️ <b>{escape(home)} vs {escape(away)}</b>\n\n"
        f"📊 <b>Maç Sonu (1X2) Olasılıkları:</b>\n"
        f"• Ev Sahibi: <b>{p1}</b> | "
        f"Beraberlik: <b>{px}</b> | "
        f"Deplasman: <b>{p2}</b>\n\n"
        f"1️⃣ <b>MS (1X2) Oranları:</b>\n"
        f"• MS 1: {escape(odds['1'])} | "
        f"MS X: {escape(odds['X'])} | "
        f"MS 2: {escape(odds['2'])}\n\n"
        f"⚽ <b>Alt / Üst Oranları ve Yüzdeleri:</b>\n"
        f"• 1.5 Alt: {escape(odds['u15'])} ({u15_p}) | "
        f"1.5 Üst: {escape(odds['o15'])} ({o15_p})\n"
        f"• 2.5 Alt: {escape(odds['u25'])} ({u25_p}) | "
        f"2.5 Üst: {escape(odds['o25'])} ({o25_p})\n"
        f"• 3.5 Alt: {escape(odds['u35'])} ({u35_p}) | "
        f"3.5 Üst: {escape(odds['o35'])} ({o35_p})\n"
        "───────────────────\n"
    )


async def send_long_message(
    update: Update,
    text: str,
) -> None:
    """Telegram 4096 karakter sınırına takılmamak için mesajı böler."""
    if not update.message:
        return

    max_len = 3800

    while text:
        if len(text) <= max_len:
            await update.message.reply_text(
                text,
                parse_mode=ParseMode.HTML,
            )
            break

        split_at = text.rfind("\n", 0, max_len)

        if split_at <= 0:
            split_at = max_len

        part = text[:split_at]
        text = text[split_at:].lstrip("\n")

        await update.message.reply_text(
            part,
            parse_mode=ParseMode.HTML,
        )


# =========================================================
# TELEGRAM KOMUTLARI
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    await update.message.reply_text(
        "👋 <b>PinnOdds Analiz Botu Aktif!</b>\n\n"
        "<b>Komutlar:</b>\n"
        "/maclar - Gelecek oranlı maçları listeler.\n"
        "/ara [takım] - Takım adına göre maç arar.\n"
        "/durum - Bot durumunu kontrol eder.",
        parse_mode=ParseMode.HTML,
    )


async def durum(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    await update.message.reply_text(
        "✅ <b>Bot aktif ve çalışıyor.</b>",
        parse_mode=ParseMode.HTML,
    )


async def maclar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    if not PINNODDS_API_KEY:
        await update.message.reply_text(
            "❌ PINNODDS_API_KEY sunucu ortamında tanımlı değil."
        )
        return

    await update.message.reply_text(
        "⏳ Oranlı ve başlamamış maçlar taranıyor..."
    )

    events = fetch_data()

    if not events:
        await update.message.reply_text(
            "⚠️ Şu anda 1X2 oranları tam olan başlamamış maç bulunamadı."
        )
        return

    count = min(10, len(events))

    msg = (
        f"⚽ <b>GELECEK ORANLI MAÇLAR ({count})</b> ⚽\n"
        "───────────────────\n\n"
    )

    for match in events[:10]:
        msg += build_card(match) + "\n"

    await send_long_message(update, msg)


async def ara(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    if not context.args:
        await update.message.reply_text(
            "⚠️ Takım adı yazın.\nÖrnek: /ara Puebla"
        )
        return

    query = " ".join(context.args).strip().lower()

    events = fetch_data()

    if not events:
        await update.message.reply_text(
            "⚠️ Başlamamış ve oranlı maç bulunamadı."
        )
        return

    matches = []

    for match in events:
        home = as_text(
            first_value(match, ["home", "home_team"], ""),
            "",
        ).lower()
        away = as_text(
            first_value(match, ["away", "away_team"], ""),
            "",
        ).lower()

        if query in home or query in away:
            matches.append(match)

    if not matches:
        await update.message.reply_text(
            f"🔍 '{query}' için oranlı ve gelecek maç bulunamadı."
        )
        return

    msg = (
        f"🔎 <b>ARAMA: {query.upper()}</b>\n"
        "───────────────────\n\n"
    )

    for match in matches[:10]:
        msg += build_card(match) + "\n"

    await send_long_message(update, msg)


# =========================================================
# FLASK
# =========================================================

def run_flask_app():
    port = int(os.environ.get("PORT", "10000"))
    app_flask.run(
        host="0.0.0.0",
        port=port,
        use_reloader=False,
    )


# =========================================================
# MAIN
# =========================================================

def validate_environment() -> bool:
    ok = True

    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN bulunamadı.")
        ok = False

    if not PINNODDS_API_KEY:
        logger.error("PINNODDS_API_KEY bulunamadı.")
        ok = False

    return ok


def main():
    if not validate_environment():
        logger.error(
            "Gerekli environment variable'lar eksik. "
            "Bot başlatılmadı."
        )
        return

    # Eski webhook varsa polling ile çakışmasını önle.
    try:
        response = requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/deleteWebhook",
            params={"drop_pending_updates": "true"},
            timeout=(5, 10),
        )

        if response.ok:
            logger.info("Telegram webhook temizlendi.")
        else:
            logger.warning(
                "Webhook temizlenemedi: HTTP %s",
                response.status_code,
            )
    except requests.RequestException as exc:
        logger.warning("Webhook temizleme hatası: %s", exc)

    # Render/Railway vb. servislerin port kontrolü için Flask.
    flask_thread = threading.Thread(
        target=run_flask_app,
        daemon=True,
        name="flask-health-server",
    )
    flask_thread.start()

    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("durum", durum))
    application.add_handler(CommandHandler("maclar", maclar))
    application.add_handler(CommandHandler("ara", ara))

    logger.info("PinnOdds Telegram Bot polling başlatılıyor...")

    application.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
    )


if __name__ == "__main__":
    main()
