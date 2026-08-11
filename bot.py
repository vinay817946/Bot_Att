import os
import json
import asyncio
import logging
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from dotenv import load_dotenv

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

from erp_monitor import LBRCEMonitor


# =========================================================
# LOAD ENVIRONMENT
# =========================================================

load_dotenv()


# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    "",
).strip()

CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    "",
).strip()

WEBHOOK_SECRET = os.getenv(
    "WEBHOOK_SECRET",
    "lbrce-secret",
).strip()

RENDER_EXTERNAL_URL = os.getenv(
    "RENDER_EXTERNAL_URL",
    "",
).strip()

CHECK_SECRET = os.getenv(
    "CHECK_SECRET",
    "check-secret",
).strip()

CHECK_INTERVAL = int(
    os.getenv(
        "CHECK_INTERVAL",
        "60",
    )
)


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s - "
        "%(levelname)s - "
        "%(message)s"
    ),
)

logger = logging.getLogger(__name__)


# =========================================================
# FASTAPI
# =========================================================

app = FastAPI(
    title="MyLBRCEBot",
)


# =========================================================
# GLOBALS
# =========================================================

monitor: Optional[LBRCEMonitor] = None

last_attendance = None

last_check_time = None

last_check_status = "Not checked yet"

telegram_application = None

monitor_task = None

attendance_lock = None


# =========================================================
# KEYBOARD
# =========================================================

def main_keyboard():

    keyboard = [
        [
            InlineKeyboardButton(
                "📊 Check Attendance",
                callback_data="attendance",
            ),
        ],
        [
            InlineKeyboardButton(
                "🟢 Bot Status",
                callback_data="status",
            ),
        ],
    ]

    return InlineKeyboardMarkup(
        keyboard
    )


def attendance_keyboard():

    keyboard = [
        [
            InlineKeyboardButton(
                "🔄 Refresh Attendance",
                callback_data="attendance",
            ),
        ],
        [
            InlineKeyboardButton(
                "🟢 Bot Status",
                callback_data="status",
            ),
        ],
        [
            InlineKeyboardButton(
                "🏠 Main Menu",
                callback_data="menu",
            ),
        ],
    ]

    return InlineKeyboardMarkup(
        keyboard
    )


def status_keyboard():

    keyboard = [
        [
            InlineKeyboardButton(
                "📊 Check Attendance",
                callback_data="attendance",
            ),
        ],
        [
            InlineKeyboardButton(
                "🔄 Refresh Status",
                callback_data="status",
            ),
        ],
        [
            InlineKeyboardButton(
                "🏠 Main Menu",
                callback_data="menu",
            ),
        ],
    ]

    return InlineKeyboardMarkup(
        keyboard
    )


# =========================================================
# FORMAT ATTENDANCE
# =========================================================

def format_attendance(data):

    subjects = data.get(
        "subjects",
        [],
    )

    overall = data.get(
        "overall",
    )

    monthly = data.get(
        "monthly",
        [],
    )

    lines = []

    lines.append(
        "📊 *LBRCE Attendance*"
    )

    lines.append("")

    if not subjects:

        lines.append(
            "⚠️ No subject attendance found."
        )

    for item in subjects:

        subject = item.get(
            "subject",
            "Unknown",
        )

        present = item.get(
            "classes_present",
            0,
        )

        held = item.get(
            "classes_held",
            0,
        )

        percentage = item.get(
            "percentage",
            0,
        )

        lines.append(
            f"📚 *{subject}*\n"
            f"   Present: {present}/{held}\n"
            f"   Attendance: "
            f"{percentage:.2f}%"
        )

    if overall is not None:

        lines.append("")

        lines.append(
            f"🎯 *Overall: "
            f"{overall:.2f}%*"
        )

    if monthly:

        lines.append("")

        lines.append(
            "📅 *Monthly Attendance*"
        )

        for month in monthly:

            month_name = month.get(
                "month",
                "",
            )

            present = month.get(
                "present",
                0,
            )

            total = month.get(
                "total",
                0,
            )

            percentage = month.get(
                "percentage",
                0,
            )

            lines.append(
                f"{month_name}: "
                f"{present}/{total} "
                f"({percentage:.2f}%)"
            )

    return "\n".join(lines)


# =========================================================
# START COMMAND
# =========================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not update.message:
        return

    await update.message.reply_text(
        "👋 *Welcome to MyLBRCEBot!*\n\n"
        "Choose an option:",
        parse_mode="Markdown",
        reply_markup=main_keyboard(),
    )


# =========================================================
# ATTENDANCE COMMAND
# =========================================================

async def attendance_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not update.message:
        return

    message = await update.message.reply_text(
        "🔄 Checking LBRCE attendance..."
    )

    try:

        data = await get_attendance_safely()

        text = format_attendance(
            data
        )

        await message.edit_text(
            text,
            parse_mode="Markdown",
            reply_markup=attendance_keyboard(),
        )

    except Exception as exc:

        logger.exception(
            "Attendance command failed."
        )

        await message.edit_text(
            "❌ *Attendance check failed.*\n\n"
            f"`{str(exc)}`",
            parse_mode="Markdown",
            reply_markup=main_keyboard(),
        )


# =========================================================
# STATUS COMMAND
# =========================================================

async def status_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not update.message:
        return

    text = get_status_text()

    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=status_keyboard(),
    )


# =========================================================
# STATUS TEXT
# =========================================================

def get_status_text():

    global last_check_time
    global last_check_status
    global monitor

    if monitor is not None:

        monitor_status = (
            "✅ LBRCE monitor initialized"
        )

    else:

        monitor_status = (
            "⏳ LBRCE monitor not initialized"
        )

    if last_check_time:

        last_check = last_check_time

    else:

        last_check = "Not checked yet"

    return (
        "🟢 *MyLBRCEBot Status*\n\n"
        "✅ Telegram Bot: Running\n"
        "✅ Web Server: Running\n"
        f"{monitor_status}\n\n"
        f"📡 Last check:\n"
        f"`{last_check}`\n\n"
        f"📌 Last result:\n"
        f"`{last_check_status}`"
    )


# =========================================================
# BUTTON CALLBACK
# =========================================================

async def button_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    if not query:
        return

    await query.answer()

    if query.data == "menu":

        await query.edit_message_text(
            "👋 *Welcome to MyLBRCEBot!*\n\n"
            "Choose an option:",
            parse_mode="Markdown",
            reply_markup=main_keyboard(),
        )

        return

    # -----------------------------------------------------
    # ATTENDANCE BUTTON
    # -----------------------------------------------------

    if query.data == "attendance":

        await query.edit_message_text(
            "🔄 *Checking LBRCE attendance...*",
            parse_mode="Markdown",
        )

        try:

            data = await get_attendance_safely()

            text = format_attendance(
                data
            )

            await query.edit_message_text(
                text,
                parse_mode="Markdown",
                reply_markup=attendance_keyboard(),
            )

        except Exception as exc:

            logger.exception(
                "Attendance button failed."
            )

            await query.edit_message_text(
                "❌ *Attendance check failed.*\n\n"
                f"`{str(exc)}`",
                parse_mode="Markdown",
                reply_markup=main_keyboard(),
            )

        return

    # -----------------------------------------------------
    # STATUS BUTTON
    # -----------------------------------------------------

    if query.data == "status":

        await query.edit_message_text(
            get_status_text(),
            parse_mode="Markdown",
            reply_markup=status_keyboard(),
        )

        return


# =========================================================
# GET ATTENDANCE SAFELY
# =========================================================

async def get_attendance_safely():

    global monitor
    global last_check_time
    global last_check_status

    if monitor is None:

        logger.info(
            "Creating LBRCE monitor..."
        )

        monitor = LBRCEMonitor()

        await monitor.start()

    try:

        data = await monitor.get_attendance()

    except Exception as exc:

        logger.exception(
            "Attendance retrieval failed."
        )

        # -------------------------------------------------
        # Recreate browser/session once.
        # This handles stale Playwright/ERP sessions.
        # -------------------------------------------------

        logger.warning(
            "Recreating LBRCE browser session..."
        )

        try:
            await monitor.close()
        except Exception:
            pass

        monitor = LBRCEMonitor()

        await monitor.start()

        data = await monitor.get_attendance()

    last_check_time = (
        datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    )

    last_check_status = "SUCCESS"

    return data


# =========================================================
# BACKGROUND ATTENDANCE CHECK
# =========================================================

async def check_attendance_once():

    global monitor
    global last_attendance
    global last_check_time
    global last_check_status
    global telegram_application

    logger.info(
        "Checking LBRCE attendance..."
    )

    try:

        data = await get_attendance_safely()

        # -------------------------------------------------
        # FIRST SUCCESSFUL CHECK
        # -------------------------------------------------

        if last_attendance is None:

            last_attendance = data

            logger.info(
                "Initial attendance saved."
            )

            return {
                "status": "initial",
                "changes": [],
                "attendance": data,
            }

        old_subjects = {
            item["subject"]: item
            for item in last_attendance.get(
                "subjects",
                [],
            )
        }

        new_subjects = {
            item["subject"]: item
            for item in data.get(
                "subjects",
                [],
            )
        }

        changes = []

        # -------------------------------------------------
        # SUBJECT COMPARISON
        # -------------------------------------------------

        for subject, new in new_subjects.items():

            old = old_subjects.get(
                subject
            )

            if old is None:

                changes.append(
                    f"➕ New subject: {subject}"
                )

                continue

            old_held = old.get(
                "classes_held",
                0,
            )

            new_held = new.get(
                "classes_held",
                0,
            )

            old_present = old.get(
                "classes_present",
                0,
            )

            new_present = new.get(
                "classes_present",
                0,
            )

            if new_held > old_held:

                added_classes = (
                    new_held - old_held
                )

                added_present = (
                    new_present - old_present
                )

                if added_present > 0:

                    status = "✅ PRESENT"

                else:

                    status = "❌ ABSENT"

                changes.append(
                    f"{status}\n"
                    f"📚 {subject}\n"
                    f"New class(es): "
                    f"{added_classes}\n"
                    f"Present: "
                    f"{new_present}/"
                    f"{new_held}\n"
                    f"Attendance: "
                    f"{new.get('percentage', 0):.2f}%"
                )

        # -------------------------------------------------
        # OVERALL COMPARISON
        # -------------------------------------------------

        old_overall = (
            last_attendance.get(
                "overall"
            )
        )

        new_overall = (
            data.get(
                "overall"
            )
        )

        if (
            old_overall is not None
            and new_overall is not None
            and old_overall != new_overall
        ):

            changes.append(
                "🎯 Overall attendance changed:\n"
                f"{old_overall:.2f}% → "
                f"{new_overall:.2f}%"
            )

        # -------------------------------------------------
        # SAVE STATE
        # -------------------------------------------------

        last_attendance = data

        last_check_status = "SUCCESS"

        # -------------------------------------------------
        # SEND NOTIFICATION
        # -------------------------------------------------

        if (
            changes
            and telegram_application
        ):

            message = (
                "🔔 *LBRCE Attendance Update*\n\n"
                + "\n\n".join(changes)
            )

            await telegram_application.bot.send_message(
                chat_id=CHAT_ID,
                text=message,
                parse_mode="Markdown",
                reply_markup=main_keyboard(),
            )

            logger.info(
                "Attendance update sent."
            )

        else:

            logger.info(
                "No attendance changes."
            )

        return {
            "status": "success",
            "changes": changes,
            "attendance": data,
        }

    except Exception as exc:

        last_check_status = (
            f"FAILED: {str(exc)[:200]}"
        )

        logger.exception(
            "Attendance monitoring error."
        )

        raise


# =========================================================
# BACKGROUND MONITOR
# =========================================================

async def background_monitor():

    logger.info(
        "Background attendance monitor started."
    )

    logger.info(
        "Check interval: %s seconds",
        CHECK_INTERVAL,
    )

    # Give the web server and Telegram
    # application time to initialize.

    await asyncio.sleep(15)

    while True:

        try:

            await check_attendance_once()

        except Exception:

            logger.exception(
                "Background attendance check failed."
            )

        await asyncio.sleep(
            CHECK_INTERVAL
        )


# =========================================================
# ROOT
# =========================================================

@app.get("/")
async def root():

    return {
        "status": "online",
        "bot": "MyLBRCEBot",
    }


# =========================================================
# HEALTH
# =========================================================

@app.get("/health")
async def health():

    return {
        "status": "ok",
        "bot": "MyLBRCEBot",
        "time": datetime.now().isoformat(),
        "last_check": last_check_time,
        "last_status": last_check_status,
    }


# =========================================================
# TELEGRAM WEBHOOK
# =========================================================

@app.post("/telegram-webhook")
async def telegram_webhook(
    request: Request,
):

    global telegram_application

    if telegram_application is None:

        return JSONResponse(
            status_code=503,
            content={
                "error": "Telegram application not ready"
            },
        )

    secret = request.headers.get(
        "X-Telegram-Bot-Api-Secret-Token"
    )

    if secret != WEBHOOK_SECRET:

        return JSONResponse(
            status_code=403,
            content={
                "error": "forbidden"
            },
        )

    try:

        data = await request.json()

        update = Update.de_json(
            data,
            telegram_application.bot,
        )

        await telegram_application.process_update(
            update
        )

        return {
            "ok": True
        }

    except Exception as exc:

        logger.exception(
            "Webhook error."
        )

        return JSONResponse(
            status_code=500,
            content={
                "error": str(exc)
            },
        )


# =========================================================
# EXTERNAL CHECK
# =========================================================

@app.get("/check")
async def scheduled_check(
    request: Request,
):

    secret = request.query_params.get(
        "secret"
    )

    if secret != CHECK_SECRET:

        return JSONResponse(
            status_code=403,
            content={
                "error": "forbidden"
            },
        )

    try:

        result = await check_attendance_once()

        return {
            "ok": True,
            "result": result,
        }

    except Exception as exc:

        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "error": str(exc),
            },
        )


# =========================================================
# STARTUP
# =========================================================

@app.on_event("startup")
async def startup():

    global telegram_application
    global monitor_task

    if not BOT_TOKEN:

        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is missing."
        )

    if not CHAT_ID:

        raise RuntimeError(
            "TELEGRAM_CHAT_ID is missing."
        )

    if not RENDER_EXTERNAL_URL:

        raise RuntimeError(
            "RENDER_EXTERNAL_URL is missing."
        )

    logger.info(
        "Starting Telegram application..."
    )

    telegram_application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # -----------------------------------------------------
    # COMMANDS
    # -----------------------------------------------------

    telegram_application.add_handler(
        CommandHandler(
            "start",
            start_command,
        )
    )

    telegram_application.add_handler(
        CommandHandler(
            "attendance",
            attendance_command,
        )
    )

    telegram_application.add_handler(
        CommandHandler(
            "status",
            status_command,
        )
    )

    # -----------------------------------------------------
    # BUTTONS
    # -----------------------------------------------------

    telegram_application.add_handler(
        CallbackQueryHandler(
            button_callback,
        )
    )

    # -----------------------------------------------------
    # TELEGRAM APPLICATION
    # -----------------------------------------------------

    await telegram_application.initialize()

    await telegram_application.start()

    # -----------------------------------------------------
    # WEBHOOK
    # -----------------------------------------------------

    webhook_url = (
        RENDER_EXTERNAL_URL.rstrip("/")
        + "/telegram-webhook"
    )

    logger.info(
        "Setting Telegram webhook: %s",
        webhook_url,
    )

    await telegram_application.bot.set_webhook(
        url=webhook_url,
        secret_token=WEBHOOK_SECRET,
        drop_pending_updates=True,
    )

    logger.info(
        "Telegram webhook configured."
    )

    logger.info(
        "MyLBRCEBot Started"
    )

    # -----------------------------------------------------
    # BACKGROUND MONITOR
    # -----------------------------------------------------

    monitor_task = asyncio.create_task(
        background_monitor()
    )

    logger.info(
        "Background attendance monitor started."
    )


# =========================================================
# SHUTDOWN
# =========================================================

@app.on_event("shutdown")
async def shutdown():

    global monitor
    global telegram_application
    global monitor_task

    logger.info(
        "Shutting down MyLBRCEBot..."
    )

    # -----------------------------------------------------
    # STOP BACKGROUND TASK
    # -----------------------------------------------------

    if monitor_task:

        monitor_task.cancel()

        try:

            await monitor_task

        except asyncio.CancelledError:

            pass

        monitor_task = None

    # -----------------------------------------------------
    # CLOSE PLAYWRIGHT
    # -----------------------------------------------------

    if monitor:

        try:

            await monitor.close()

        except Exception as exc:

            logger.error(
                "Error closing monitor: %s",
                exc,
            )

        monitor = None

    # -----------------------------------------------------
    # STOP TELEGRAM
    # -----------------------------------------------------

    if telegram_application:

        try:

            await telegram_application.bot.delete_webhook()

        except Exception as exc:

            logger.warning(
                "Could not delete webhook: %s",
                exc,
            )

        try:

            await telegram_application.stop()

        except Exception as exc:

            logger.warning(
                "Telegram stop error: %s",
                exc,
            )

        try:

            await telegram_application.shutdown()

        except Exception as exc:

            logger.warning(
                "Telegram shutdown error: %s",
                exc,
            )

        telegram_application = None

    logger.info(
        "MyLBRCEBot shutdown complete."
    )


# =========================================================
# LOCAL RUN
# =========================================================

if __name__ == "__main__":

    import uvicorn

    port = int(
        os.getenv(
            "PORT",
            "8000",
        )
    )

    uvicorn.run(
        "bot:app",
        host="0.0.0.0",
        port=port,
        reload=False,
    )
