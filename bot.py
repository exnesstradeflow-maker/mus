#!/usr/bin/env python3
"""
Telegram Bot: Video → Voice Message
✅ Crash-proof  ✅ Auto-reconnect  ✅ Railway ready
"""

import asyncio
import logging
import os
import subprocess
import sys
import tempfile
import time

from telegram import Update
from telegram.error import NetworkError, RetryAfter, TelegramError, TimedOut
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ── Sozlamalar ──────────────────────────────────────────────────────────────────
BOT_TOKEN   = os.environ.get("BOT_TOKEN", "")
MAX_FILE_MB = 50
# ───────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
    force=True,
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)


# ── Token tekshiruvi ────────────────────────────────────────────────────────────
def check_token() -> bool:
    if not BOT_TOKEN:
        logger.critical("BOT_TOKEN topilmadi! Railway → Variables ga qo'shing.")
        return False
    if ":" not in BOT_TOKEN or len(BOT_TOKEN) < 30:
        logger.critical("BOT_TOKEN noto'g'ri format!")
        return False
    return True


# ── Xavfsiz edit yordamchi ──────────────────────────────────────────────────────
async def safe_edit(msg, text: str) -> None:
    if msg is None:
        return
    try:
        await msg.edit_text(text)
    except TelegramError:
        pass


# ── /start ──────────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    try:
        await update.message.reply_text(
            "👋 Salom!\n\n"
            "Menga 🎬 video yuboring — men audio ajratib,\n"
            "🎤 golosovoy xabar qilib qaytaraman.\n\n"
            "📌 Qo'llab-quvvatlanadigan formatlar:\n"
            "MP4, MOV, AVI, MKV, WebM va boshqalar.\n\n"
            "⚠️ Maksimal hajm: 50 MB"
        )
    except TelegramError as e:
        logger.warning("start xatosi: %s", e)


# ── Video qabul qilish ──────────────────────────────────────────────────────────
async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    message = update.message
    video   = message.video or message.document
    status  = None

    if video is None:
        return

    # Hajm tekshiruvi
    if video.file_size and video.file_size > MAX_FILE_MB * 1024 * 1024:
        try:
            await message.reply_text(
                f"❌ Fayl {MAX_FILE_MB} MB dan katta.\n"
                "Kichikroq video yuboring."
            )
        except TelegramError:
            pass
        return

    # Status xabari
    try:
        status = await message.reply_text("⏳ Video yuklanmoqda...")
    except TelegramError as e:
        logger.warning("Status yuborilmadi: %s", e)
        return

    with tempfile.TemporaryDirectory() as tmp:
        video_path = os.path.join(tmp, "input_video")
        ogg_path   = os.path.join(tmp, "output.ogg")

        try:
            # 1. Yuklab olish
            try:
                tg_file = await context.bot.get_file(video.file_id)
                await tg_file.download_to_drive(video_path)
            except TelegramError as e:
                logger.error("Yuklab olishda xato: %s", e)
                await safe_edit(status, "❌ Video yuklanmadi. Qayta urinib ko'ring.")
                return

            # Bo'sh fayl tekshiruvi
            if not os.path.exists(video_path) or os.path.getsize(video_path) == 0:
                await safe_edit(status, "❌ Fayl bo'sh keldi. Qayta yuboring.")
                return

            await safe_edit(status, "🔧 Audio ajratilmoqda...")

            # 2. FFmpeg ishga tushirish
            ffmpeg_cmd = [
                "ffmpeg", "-y",
                "-i", video_path,
                "-vn",
                "-c:a", "libopus",
                "-b:a", "64k",
                "-ar", "48000",
                "-ac", "1",
                ogg_path,
            ]

            try:
                proc = subprocess.run(
                    ffmpeg_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=180,
                )
            except FileNotFoundError:
                logger.error("ffmpeg topilmadi!")
                await safe_edit(status, "❌ Server xatosi: ffmpeg yo'q.")
                return
            except subprocess.TimeoutExpired:
                await safe_edit(status, "❌ Vaqt tugadi (3 daqiqa). Video juda uzun.")
                return

            # FFmpeg xatosi
            if proc.returncode != 0:
                err_msg = proc.stderr.decode(errors="replace")
                logger.error("FFmpeg xato (code %s):\n%s", proc.returncode, err_msg)

                # Audio trek yo'q bo'lsa
                if "no audio" in err_msg.lower() or "does not contain" in err_msg.lower():
                    await safe_edit(status, "❌ Bu videoda audio yo'q.")
                else:
                    await safe_edit(status, "❌ Audio ajratishda xato. Boshqa video sinab ko'ring.")
                return

            # OGG fayl tekshiruvi
            if not os.path.exists(ogg_path) or os.path.getsize(ogg_path) == 0:
                await safe_edit(status, "❌ Audio fayl yaratilmadi. Videoda ovoz bor-yo'qligini tekshiring.")
                return

            # 3. Voice message yuborish
            await safe_edit(status, "📤 Yuborilmoqda...")
            try:
                with open(ogg_path, "rb") as audio_file:
                    await message.reply_voice(
                        voice=audio_file,
                        caption="✅ Mana golosovoy xabaringiz!",
                    )
                try:
                    await status.delete()
                except TelegramError:
                    pass

            except TelegramError as e:
                logger.error("Voice yuborishda xato: %s", e)
                await safe_edit(status, "❌ Yuborishda xato. Qayta urinib ko'ring.")

        except RetryAfter as e:
            logger.warning("Rate limit: %ss", e.retry_after)
            await asyncio.sleep(e.retry_after)
            await safe_edit(status, "❌ Telegram cheklovi. Biroz kuting va qayta yuboring.")

        except (TimedOut, NetworkError) as e:
            logger.warning("Tarmoq xatosi: %s", e)
            await safe_edit(status, "❌ Internet muammosi. Qayta urinib ko'ring.")

        except TelegramError as e:
            logger.error("Telegram xatosi: %s", e)
            await safe_edit(status, "❌ Telegram xatosi. Qayta urinib ko'ring.")

        except Exception as e:
            logger.exception("Kutilmagan xato: %s", e)
            await safe_edit(status, "❌ Kutilmagan xato. Qayta urinib ko'ring.")


# ── Boshqa xabarlar ─────────────────────────────────────────────────────────────
async def handle_other(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    try:
        await update.message.reply_text(
            "🎬 Iltimos, video yuboring.\n"
            "Yordam uchun: /start"
        )
    except TelegramError:
        pass


# ── Global xato handler ──────────────────────────────────────────────────────────
async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    err = context.error
    if isinstance(err, TimedOut):
        logger.warning("Timeout (bot davom etadi)")
    elif isinstance(err, NetworkError):
        logger.warning("Network xato (bot davom etadi): %s", err)
    elif isinstance(err, RetryAfter):
        logger.warning("Rate limit %ss (bot davom etadi)", err.retry_after)
    else:
        logger.error("Xato (bot davom etadi): %s", err, exc_info=err)
    # Bot HECH QACHON to'xtamaydi


# ── Application yaratish ─────────────────────────────────────────────────────────
def build_app():
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(60)
        .pool_timeout(30)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.VIDEO, handle_video))
    app.add_handler(MessageHandler(filters.Document.VIDEO, handle_video))
    app.add_handler(
        MessageHandler(
            ~filters.VIDEO & ~filters.Document.VIDEO & ~filters.COMMAND,
            handle_other,
        )
    )
    app.add_error_handler(global_error_handler)
    return app


# ── Main: sonsiz qayta urinish ───────────────────────────────────────────────────
def main() -> None:
    if not check_token():
        sys.exit(1)

    delay = 5

    while True:
        try:
            logger.info("Bot ishga tushmoqda...")
            app = build_app()
            logger.info("Bot tayyor! Xabarlar kutilmoqda...")
            app.run_polling(
                drop_pending_updates=True,
                allowed_updates=["message"],
            )
            # run_polling normal tugasa (masalan SIGTERM) — chiqamiz
            logger.info("Bot to'xtatildi.")
            break

        except KeyboardInterrupt:
            logger.info("Ctrl+C — bot to'xtatildi.")
            break

        except Exception as e:
            logger.error(
                "Bot to'xtadi: %s\n→ %s soniyadan keyin qayta ishga tushadi...",
                e, delay
            )
            time.sleep(delay)
            delay = min(delay * 2, 60)  # 5 → 10 → 20 → 40 → 60s (max)


if __name__ == "__main__":
    main()
