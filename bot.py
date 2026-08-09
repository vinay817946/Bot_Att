import os
import asyncio
import logging
import json
from datetime import datetime

from dotenv import load_dotenv

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

from erp_monitor import LBRCEMonitor


# =========================================================
# CONFIG
# =========================================================

load_dotenv()

BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
).strip()

CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
).strip()

CHECK_INTERVAL = int(
    os.getenv(
        "CHECK_INTERVAL",
        "300"
    )
)

STATE_FILE = "attendance_state.json"


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    format=(
        "%(asctime)s - "
        "%(name)s - "
        "%(levelname)s - "
        "%(message)s"
    ),
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# =========================================================
# GLOBALS
# =========================================================

monitor = None

last_attendance = None

last_check_time = None

monitor_task = None

shutdown_event = asyncio.Event()


# =========================================================
# STATE MANAGEMENT
# =========================================================

def load_attendance_state():
    """
    Load previous attendance from disk.

    This allows the bot to remember the previous
    attendance even after restarting.
    """

    if not os.path.exists(STATE_FILE):
        logger.info(
            "No previous attendance state found."
        )
        return None

    try:

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8",
        ) as file:

            data = json.load(file)

        logger.info(
            "Previous attendance state loaded."
        )

        return data

    except Exception as exc:

        logger.error(
            "Could not load attendance state: %s",
            exc,
        )

        return None


def save_attendance_state(data):
    """
    Save latest attendance to disk.
    """

    try:

        temporary_file = (
            STATE_FILE + ".tmp"
        )

        with open(
            temporary_file,
            "w",
            encoding="utf-8",
        ) as file:

            json.dump(
                data,
                file,
                indent=2,
                ensure_ascii=False,
            )

        # Replace old state atomically.
        os.replace(
            temporary_file,
            STATE_FILE,
        )

        logger.info(
            "Attendance state saved."
        )

    except Exception as exc:

        logger.error(
            "Could not save attendance state: %s",
            exc,
        )


# =========================================================
# FORMAT ATTENDANCE
# =========================================================

def format_attendance(data):

    subjects = data.get(
        "subjects",
        []
    )

    overall = data.get(
        "overall"
    )

    monthly = data.get(
        "monthly",
        []
    )

    lines = []

    lines.append(
        "📊 *LBRCE Attendance*"
    )

    lines.append("")

    for item in subjects:

        subject = item.get(
            "subject",
            "Unknown"
        )

        present = item.get(
            "classes_present",
            0
        )

        held = item.get(
            "classes_held",
            0
        )

        percentage = item.get(
            "percentage",
            0
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

            lines.append(
                f"{month.get('month', 'Unknown')}: "
                f"{month.get('present', 0)}/"
                f"{month.get('total', 0)} "
                f"({month.get('percentage', 0):.2f}%)"
            )

    return "\n".join(lines)


# =========================================================
# START COMMAND
# =========================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    await update.message.reply_text(
        "👋 Welcome to MyLBRCEBot!\n\n"
        "Commands:\n"
        "/attendance - Check attendance\n"
        "/status - Bot status\n"
    )


# =========================================================
# ATTENDANCE COMMAND
# =========================================================

async def attendance_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    global monitor

    message = await update.message.reply_text(
        "🔄 Checking LBRCE attendance..."
    )

    try:

        if monitor is None:

            monitor = LBRCEMonitor()

            await monitor.start()

        data = await monitor.get_attendance()

        text = format_attendance(
            data
        )

        await message.edit_text(
            text,
            parse_mode="Markdown",
        )

    except Exception as exc:

        logger.exception(
            "Attendance command failed"
        )

        await message.edit_text(
            "❌ Attendance check failed.\n\n"
            f"`{str(exc)}`",
            parse_mode="Markdown",
        )


# =========================================================
# STATUS COMMAND
# =========================================================

async def status_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    global last_check_time

    if last_check_time:

        text = (
            "🟢 *Bot is running.*\n\n"
            f"Last successful check:\n"
            f"`{last_check_time}`"
        )

    else:

        text = (
            "🟢 *Bot is running.*\n\n"
            "Attendance has not been checked yet."
        )

    await update.message.reply_text(
        text,
        parse_mode="Markdown",
    )


# =========================================================
# CHECK ATTENDANCE ONCE
# =========================================================

async def check_attendance_once(
    application
):

    global monitor
    global last_attendance
    global last_check_time

    try:

        logger.info(
            "Checking LBRCE attendance..."
        )

        # -------------------------------------------------
        # Create monitor if necessary
        # -------------------------------------------------

        if monitor is None:

            logger.info(
                "Creating LBRCE monitor..."
            )

            monitor = LBRCEMonitor()

            await monitor.start()

        # -------------------------------------------------
        # Get attendance
        # -------------------------------------------------

        data = await monitor.get_attendance()

        last_check_time = (
            datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        )

        # -------------------------------------------------
        # First successful check
        # -------------------------------------------------

        if last_attendance is None:

            last_attendance = data

            save_attendance_state(
                data
            )

            logger.info(
                "Initial attendance saved."
            )

            return

        # -------------------------------------------------
        # Previous subjects
        # -------------------------------------------------

        old_subjects = {
            item.get("subject"): item
            for item in last_attendance.get(
                "subjects",
                []
            )
        }

        # -------------------------------------------------
        # New subjects
        # -------------------------------------------------

        new_subjects = {
            item.get("subject"): item
            for item in data.get(
                "subjects",
                []
            )
        }

        changes = []

        # =================================================
        # COMPARE SUBJECTS
        # =================================================

        for subject, new in new_subjects.items():

            old = old_subjects.get(
                subject
            )

            # ------------------------------------------------
            # New subject
            # ------------------------------------------------

            if old is None:

                changes.append(
                    f"➕ *New subject detected*\n"
                    f"📚 {subject}\n"
                    f"Attendance: "
                    f"{new.get('percentage', 0):.2f}%"
                )

                continue

            old_held = old.get(
                "classes_held",
                0
            )

            new_held = new.get(
                "classes_held",
                0
            )

            old_present = old.get(
                "classes_present",
                0
            )

            new_present = new.get(
                "classes_present",
                0
            )

            # =================================================
            # NEW CLASS ADDED
            # =================================================

            if new_held > old_held:

                added_classes = (
                    new_held - old_held
                )

                added_present = (
                    new_present - old_present
                )

                if added_present > 0:

                    status = "✅ *PRESENT*"

                else:

                    status = "❌ *ABSENT*"

                changes.append(
                    f"{status}\n"
                    f"📚 *{subject}*\n"
                    f"New class(es): "
                    f"{added_classes}\n"
                    f"Present: "
                    f"{new_present}/"
                    f"{new_held}\n"
                    f"Attendance: "
                    f"{new.get('percentage', 0):.2f}%"
                )

            # =================================================
            # ATTENDANCE CORRECTION
            # =================================================

            elif new_present != old_present:

                changes.append(
                    f"⚠️ *Attendance corrected*\n"
                    f"📚 *{subject}*\n"
                    f"Previous: "
                    f"{old_present}/{old_held}\n"
                    f"Current: "
                    f"{new_present}/{new_held}\n"
                    f"Attendance: "
                    f"{new.get('percentage', 0):.2f}%"
                )

        # =================================================
        # OVERALL ATTENDANCE
        # =================================================

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
                f"🎯 *Overall attendance changed*\n"
                f"{old_overall:.2f}% → "
                f"{new_overall:.2f}%"
            )

        # =================================================
        # SAVE NEW STATE
        # =================================================

        last_attendance = data

        save_attendance_state(
            data
        )

        # =================================================
        # SEND TELEGRAM NOTIFICATION
        # =================================================

        if changes:

            message = (
                "🔔 *LBRCE Attendance Update*\n\n"
                + "\n\n".join(changes)
            )

            await application.bot.send_message(
                chat_id=CHAT_ID,
                text=message,
                parse_mode="Markdown",
            )

            logger.info(
                "Attendance update sent to Telegram."
            )

        else:

            logger.info(
                "No attendance changes."
            )

        return True

    except Exception as exc:

        logger.exception(
            "Attendance monitoring error"
        )

        return False


# =========================================================
# BACKGROUND MONITOR
# =========================================================

async def attendance_monitor(
    application
):

    logger.info(
        "Background attendance monitor started."
    )

    # -----------------------------------------------------
    # Small startup delay
    # -----------------------------------------------------

    try:

        await asyncio.wait_for(
            shutdown_event.wait(),
            timeout=10,
        )

        return

    except asyncio.TimeoutError:

        pass

    # =====================================================
    # MAIN LOOP
    # =====================================================

    while not shutdown_event.is_set():

        try:

            await check_attendance_once(
                application
            )

        except asyncio.CancelledError:

            logger.info(
                "Attendance monitor cancelled."
            )

            raise

        except Exception:

            logger.exception(
                "Background monitor error."
            )

        # -------------------------------------------------
        # Wait using shutdown event.
        #
        # This is better than:
        #
        # await asyncio.sleep(...)
        #
        # because shutdown can interrupt the wait.
        # -------------------------------------------------

        try:

            await asyncio.wait_for(
                shutdown_event.wait(),
                timeout=CHECK_INTERVAL,
            )

        except asyncio.TimeoutError:

            pass

    logger.info(
        "Background attendance monitor stopped."
    )


# =========================================================
# POST INITIALIZATION
# =========================================================

async def post_init(
    application
):

    global monitor_task
    global last_attendance

    logger.info(
        "Application initialization started."
    )

    # -----------------------------------------------------
    # Load previous state
    # -----------------------------------------------------

    last_attendance = (
        load_attendance_state()
    )

    if last_attendance is not None:

        logger.info(
            "Previous attendance loaded "
            "into memory."
        )

    # -----------------------------------------------------
    # Create background task
    # -----------------------------------------------------

    monitor_task = asyncio.create_task(
        attendance_monitor(
            application
        )
    )

    logger.info(
        "Background attendance task created."
    )


# =========================================================
# POST SHUTDOWN
# =========================================================

async def post_shutdown(
    application
):

    global monitor
    global monitor_task

    logger.info(
        "Starting graceful shutdown..."
    )

    # -----------------------------------------------------
    # Tell monitor loop to stop
    # -----------------------------------------------------

    shutdown_event.set()

    # -----------------------------------------------------
    # Wait for monitor task
    # -----------------------------------------------------

    if monitor_task:

        try:

            await asyncio.wait_for(
                monitor_task,
                timeout=15,
            )

        except asyncio.TimeoutError:

            logger.warning(
                "Monitor task did not stop "
                "within 15 seconds."
            )

            monitor_task.cancel()

            try:

                await monitor_task

            except asyncio.CancelledError:

                pass

        except asyncio.CancelledError:

            pass

        except Exception as exc:

            logger.error(
                "Monitor task shutdown error: %s",
                exc,
            )

    # -----------------------------------------------------
    # Close Playwright
    # -----------------------------------------------------

    if monitor:

        try:

            logger.info(
                "Closing LBRCE browser..."
            )

            await monitor.close()

            logger.info(
                "LBRCE browser closed."
            )

        except Exception as exc:

            logger.error(
                "Error closing LBRCE monitor: %s",
                exc,
            )

        finally:

            monitor = None

    logger.info(
        "Graceful shutdown complete."
    )


# =========================================================
# MAIN
# =========================================================

def main():

    if not BOT_TOKEN:

        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is missing."
        )

    if not CHAT_ID:

        raise RuntimeError(
            "TELEGRAM_CHAT_ID is missing."
        )

    print("")
    print(
        "================================"
    )
    print(
        "       MyLBRCEBot Started"
    )
    print(
        "================================"
    )
    print("")

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # -----------------------------------------------------
    # Commands
    # -----------------------------------------------------

    application.add_handler(
        CommandHandler(
            "start",
            start_command
        )
    )

    application.add_handler(
        CommandHandler(
            "attendance",
            attendance_command
        )
    )

    application.add_handler(
        CommandHandler(
            "status",
            status_command
        )
    )

    # -----------------------------------------------------
    # Start Telegram polling
    # -----------------------------------------------------

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


# =========================================================
# ENTRY POINT
# =========================================================

if __name__ == "__main__":

    main()
