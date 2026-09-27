"""
Bot Telegram pengingat absen kuliah.
- Tiap kelas punya jadwal (hari, jam mulai).
- Selama jendela waktu tertentu setelah kelas mulai, bot kirim pesan
  tiap 10 menit dengan tombol "Sudah absen".
- Begitu tombol ditekan, pengingat untuk kelas itu berhenti untuk hari itu,
  dan otomatis aktif lagi minggu depan.
- Chat ID diambil otomatis dari orang pertama yang mengirim /start ke bot,
  jadi tidak perlu di-hardcode.

Cara pakai:
1. pip install -r requirements.txt
2. Set environment variable BOT_TOKEN (jangan taruh token di kode).
3. Jalankan: python main.py
4. Di Telegram, kirim /start ke bot supaya bot tahu ke mana kirim pengingat.
"""

import json
import logging
import os
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

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

# weekday: 0=Senin ... 6=Minggu (mengikuti Python date.weekday())
# duration_minutes: berapa lama jendela pengingat berjalan setelah start
CLASSES = [
    {"id": "sna", "name": "Analisis Jejaring Sosial", "weekday": 0, "start": "08:00", "duration_minutes": 60},
    {"id": "hci", "name": "Human Computer Interaction", "weekday": 0, "start": "10:30", "duration_minutes": 60},
    {"id": "bisnis", "name": "Pengantar Bisnis", "weekday": 0, "start": "13:30", "duration_minutes": 60},
    {"id": "lab_grafika", "name": "Lab Grafika Komputer", "weekday": 2, "start": "08:00", "duration_minutes": 60},
    {"id": "grafika", "name": "Grafika Komputer", "weekday": 2, "start": "10:30", "duration_minutes": 60},
    {"id": "metpen", "name": "Metodologi Penelitian", "weekday": 3, "start": "08:00", "duration_minutes": 60},
    {"id": "bi", "name": "Business Intelligence", "weekday": 3, "start": "10:30", "duration_minutes": 60},
    {"id": "cloud", "name": "Cloud Computing", "weekday": 3, "start": "13:50", "duration_minutes": 60},
    {"id": "lab_mobile", "name": "Lab Pemrograman Mobile", "weekday": 4, "start": "10:40", "duration_minutes": 60},
    {"id": "mobile", "name": "Pemrograman Mobile", "weekday": 4, "start": "13:50", "duration_minutes": 60},
]

REMINDER_INTERVAL_SECONDS = 10 * 60  # cek tiap 10 menit


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {"owner_chat_id": None, "confirmed": {}}


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def parse_hhmm(value: str) -> dtime:
    h, m = value.split(":")
    return dtime(hour=int(h), minute=int(m))


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = load_state()
    state["owner_chat_id"] = update.effective_chat.id
    save_state(state)
    await update.message.reply_text(
        "Siap. Bot ini akan mengingatkanmu absen kuliah tiap 10 menit "
        "sampai kamu konfirmasi lewat tombol di pesannya."
    )


async def confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    class_id, date_str = query.data.split("|", 1)
    state = load_state()
    state["confirmed"][f"{class_id}:{date_str}"] = True
    save_state(state)
    class_name = next((c["name"] for c in CLASSES if c["id"] == class_id), class_id)
    await query.answer("Dicatat, terima kasih!")
    await query.edit_message_text(f"Sudah absen {class_name} ✅ ({date_str})")


async def check_reminders(context: ContextTypes.DEFAULT_TYPE) -> None:
    state = load_state()
    chat_id = state.get("owner_chat_id")
    if not chat_id:
        return  # belum ada yang /start

    now = datetime.now(TZ)
    today_str = now.date().isoformat()

    for cls in CLASSES:
        if cls["weekday"] != now.weekday():
            continue
        start_t = parse_hhmm(cls["start"])
        start_dt = now.replace(hour=start_t.hour, minute=start_t.minute, second=0, microsecond=0)
        end_dt = start_dt + __import__("datetime").timedelta(minutes=cls["duration_minutes"])

        if not (start_dt <= now <= end_dt):
            continue

        key = f"{cls['id']}:{today_str}"
        if state["confirmed"].get(key):
            continue  # sudah dikonfirmasi hari ini

        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Sudah absen", callback_data=f"{cls['id']}|{today_str}")]]
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Sudah absen kuliah {cls['name']}?",
            reply_markup=keyboard,
        )


def main() -> None:
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise SystemExit("Set environment variable BOT_TOKEN dulu.")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(confirm_callback))
    app.job_queue.run_repeating(check_reminders, interval=REMINDER_INTERVAL_SECONDS, first=5)

    log.info("Bot jalan...")
    app.run_polling()


if __name__ == "__main__":
    main()
