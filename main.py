import logging
import os
from datetime import time, timedelta, timezone
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

import db
from handlers import (
    AMOUNT, FACING, FERTILIZER_AMOUNT, FERTILIZER_FREQUENCY, FERTILIZER_TYPE,
    FREQUENCY, HEIGHT, LOCATION, NAME, PHOTO, PLANT_TYPE, POT_DEPTH, POT_WIDTH,
    SOIL_ALKALINITY, SOIL_TYPE, SUNLIGHT_ACTUAL, SUNLIGHT_NEEDED,
    care_command, disease_command, health_callback, health_command, help_command, height_command,
    issues_command, list_plants, onboard_amount,
    report_command, report_plant_callback, report_section_callback,
    onboard_cancel, onboard_facing, onboard_fertilizer_amount,
    onboard_fertilizer_frequency, onboard_fertilizer_type, onboard_frequency,
    onboard_height, onboard_location, onboard_name, onboard_photo,
    onboard_pot_depth, onboard_pot_width, onboard_soil_alkalinity,
    onboard_soil_type, onboard_start, onboard_sunlight_actual, onboard_sunlight_needed,
    onboard_type, pest_command, photo_command,
    start, status_command, treat_command, water_command,
    handle_photo_reply, handle_reply,
    startserver_command, stopserver_command,
)
from quickadd import build_quickadd_handler
from scheduler import send_daily_recommendations, send_height_reminder

load_dotenv()

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)


async def post_init(application: Application) -> None:
    await db.init_db()


def main():
    token = os.getenv("PLANT_TELEGRAM_TOKEN")
    if not token:
        raise ValueError("PLANT_TELEGRAM_TOKEN not set in .env")

    app = (
        Application.builder()
        .token(token)
        .post_init(post_init)
        .build()
    )

    onboarding = ConversationHandler(
        entry_points=[CommandHandler("add", onboard_start)],
        states={
            NAME:            [MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_name)],
            PLANT_TYPE:      [MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_type)],
            LOCATION:        [MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_location)],
            POT_DEPTH:       [MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_pot_depth)],
            POT_WIDTH:       [MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_pot_width)],
            SOIL_ALKALINITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_soil_alkalinity)],
            SOIL_TYPE:       [MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_soil_type)],
            FERTILIZER_TYPE:      [MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_fertilizer_type)],
            FERTILIZER_AMOUNT:    [MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_fertilizer_amount)],
            FERTILIZER_FREQUENCY: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_fertilizer_frequency)],
            FACING:          [MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_facing)],
            HEIGHT:          [MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_height)],
            SUNLIGHT_ACTUAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_sunlight_actual)],
            SUNLIGHT_NEEDED: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_sunlight_needed)],
            FREQUENCY:       [MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_frequency)],
            AMOUNT:          [MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_amount)],
            PHOTO: [
                MessageHandler(filters.PHOTO, onboard_photo),
                MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_photo),
            ],
        },
        fallbacks=[CommandHandler("cancel", onboard_cancel)],
    )

    app.add_handler(build_quickadd_handler())
    app.add_handler(onboarding)
    app.add_handler(CommandHandler("start",       start))
    app.add_handler(CommandHandler("help",        help_command))
    app.add_handler(CommandHandler("list",        list_plants))
    app.add_handler(CommandHandler("water",       water_command))
    app.add_handler(CommandHandler("status",      status_command))
    app.add_handler(CommandHandler("photo",       photo_command))
    app.add_handler(CommandHandler("health",      health_command))
    app.add_handler(CommandHandler("height",      height_command))
    app.add_handler(CommandHandler("pest",        pest_command))
    app.add_handler(CommandHandler("disease",     disease_command))
    app.add_handler(CommandHandler("treat",       treat_command))
    app.add_handler(CommandHandler("issues",      issues_command))
    app.add_handler(CommandHandler("care",        care_command))
    app.add_handler(CommandHandler("report",      report_command))
    app.add_handler(CallbackQueryHandler(report_plant_callback,   pattern=r"^report:\d+$"))
    app.add_handler(CallbackQueryHandler(report_section_callback, pattern=r"^report_sec:"))
    app.add_handler(CommandHandler("startserver", startserver_command))
    app.add_handler(CommandHandler("stopserver",  stopserver_command))
    app.add_handler(CallbackQueryHandler(health_callback, pattern=r"^health:\d+$"))

    # Photo replies must be registered before text replies
    app.add_handler(MessageHandler(filters.REPLY & filters.PHOTO, handle_photo_reply))
    app.add_handler(MessageHandler(filters.REPLY & filters.TEXT & ~filters.COMMAND, handle_reply))

    # Daily recommendations at 08:00 UTC
    app.job_queue.run_daily(
        send_daily_recommendations,
        time=time(hour=8, minute=0, tzinfo=timezone.utc),
        name="daily_plant_recommendations",
    )

    # Height check-in every 2 weeks at 09:00 UTC
    app.job_queue.run_repeating(
        send_height_reminder,
        interval=timedelta(days=14),
        first=time(hour=9, minute=0, tzinfo=timezone.utc),
        name="biweekly_height_reminder",
    )

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
