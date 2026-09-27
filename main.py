"""
Bot Telegram pengingat absen kuliah — jadwal dibaca otomatis dari kalender iCloud.

- Bot ambil jadwal dari link publik kalender iCloud (format ICS) tiap kali cek.
- Untuk tiap acara yang mulai hari ini, selama jendela waktu setelah acara mulai,
  bot kirim pesan tiap 10 menit dengan tombol "Sudah absen".
- Begitu tombol ditekan, pengingat untuk acara itu berhenti untuk hari itu.
- Chat ID diambil otomatis dari orang pertama yang mengirim /start ke bot.

Cara pakai:
1. pip install -r requirements.txt
2. Set environment variable:
   - BOT_TOKEN   -> token dari BotFather
   - CALENDAR_ICS_URL -> link publik kalender iCloud, diawali https:// (bukan webcal://)
3. Jalankan: python main.py
4. Di Telegram, kirim /start ke bot supaya bot tahu ke mana kirim pengingat.
"""

import json
import logging
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import recurring_ical_events
import requests
from icalendar import Calendar
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("absen-bot")

TZ = ZoneInfo("Asia/Jakarta")
STATE_FILE = "state.json"

REMINDER_WINDOW_MINUTES = 60   # berapa lama jendela pengingat berjalan setelah acara mulai
REMINDER_INTERVAL_SECONDS = 10 * 60  # cek tiap 10 menit
ICS_CACHE_SECONDS = 15 * 60   # jangan download ICS lebih sering dari ini


_ics_cache = {"fetched_at": None, "text": None}


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {"owner_chat_id": None, "confirmed": {}}


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def fetch_ics_text(url: str) -> str:
    now = datetime.now(TZ)
    if (
        _ics_cache["text"] is not None
        and _ics_cache["fetched_at"] is not None
        and (now - _ics_cache["fetched_at"]).total_seconds() < ICS_CACHE_SECONDS
    ):
        return _ics_cache["text"]

    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    _ics_cache["text"] = resp.text
    _ics_cache["fetched_at"] = now
    return resp.text


def get_todays_events(ics_url: str) -> list[dict]:
    """Ambil semua acara yang mulai HARI INI dari link kalender."""
    ics_text = fetch_ics_text(ics_url)
    calendar = Calendar.from_ical(ics_text)

    now = datetime.now(TZ)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

    events = recurring_ical_events.of(calendar).between(day_start, day_end)

    result = []
    for event in events:
        summary = str(event.get("summary", "Tanpa judul"))
        dtstart = event["dtstart"].dt
        if not isinstance(dtstart, datetime):
            continue  # lewati acara sepanjang hari (tidak punya jam)
        if dtstart.tzinfo is None:
            dtstart = dtstart.replace(tzinfo=TZ)
        dtstart = dtstart.astimezone(TZ)
        uid = str(event.get("uid", summary))
        result.append({"id": uid, "name": summary, "start": dtstart})
    return result


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = load_state()
    state["owner_chat_id"] = update.effective_chat.id
    save_state(state)
    await update.message.reply_text(
        "Siap. Bot ini akan baca jadwal dari kalendermu dan mengingatkanmu "
        "absen tiap 10 menit sampai kamu konfirmasi lewat tombol di pesannya."
    )


async def confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    event_id, date_str = query.data.split("|", 1)
    state = load_state()
    state["confirmed"][f"{event_id}:{date_str}"] = True
    save_state(state)
    await query.answer("Dicatat, terima kasih!")
    await query.edit_message_text(f"{query.message.text} ✅ (dikonfirmasi)")


async def check_reminders(context: ContextTypes.DEFAULT_TYPE) -> None:
    state = load_state()
    chat_id = state.get("owner_chat_id")
    if not chat_id:
        return  # belum ada yang /start

    ics_url = os.environ.get("CALENDAR_ICS_URL")
    if not ics_url:
        log.warning("CALENDAR_ICS_URL belum diset, tidak bisa baca jadwal.")
        return

    try:
        todays_events = get_todays_events(ics_url)
    except Exception as e:
        log.error(f"Gagal ambil/parsing kalender: {e}")
        return

    now = datetime.now(TZ)
    today_str = now.date().isoformat()

    for event in todays_events:
        start_dt = event["start"]
        end_dt = start_dt + timedelta(minutes=REMINDER_WINDOW_MINUTES)

        if not (start_dt <= now <= end_dt):
            continue

        key = f"{event['id']}:{today_str}"
        if state["confirmed"].get(key):
            continue  # sudah dikonfirmasi hari ini

        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Sudah absen", callback_data=f"{event['id']}|{today_str}")]]
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Sudah absen kuliah {event['name']}?",
            reply_markup=keyboard,
        )


def main() -> None:
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise SystemExit("Set environment variable BOT_TOKEN dulu.")
    if not os.environ.get("CALENDAR_ICS_URL"):
        raise SystemExit("Set environment variable CALENDAR_ICS_URL dulu (link https://, bukan webcal://).")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(confirm_callback))
    app.job_queue.run_repeating(check_reminders, interval=REMINDER_INTERVAL_SECONDS, first=5)

    log.info("Bot jalan...")
    app.run_polling()


if __name__ == "__main__":
    main()
