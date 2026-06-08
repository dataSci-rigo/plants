import logging
import os
from datetime import time, timezone
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
    AMOUNT, FREQUENCY, NAME, PHOTO, PLANT_TYPE, POT_DEPTH,
    health_callback, health_command, list_plants, onboard_amount,
    onboard_cancel, onboard_frequency, onboard_name, onboard_photo,
    onboard_pot_depth, onboard_start, onboard_type, photo_command,
    start, status_command, water_command,
    handle_photo_reply, handle_reply,
    settopic_command, startserver_command, stopserver_command,
)
from scheduler import send_daily_recommendations

load_dotenv()

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)


async def post_init(application: Application) -> None:
    await db.init_db()


def main():
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_TOKEN not set in .env")

    app = (
        Application.builder()
        .token(token)
        .post_init(post_init)
        .build()
    )

    onboarding = ConversationHandler(
        entry_points=[CommandHandler("add", onboard_start)],
        states={
            NAME:       [MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_name)],
            PLANT_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_type)],
            POT_DEPTH:  [MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_pot_depth)],
            FREQUENCY:  [MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_frequency)],
            AMOUNT:     [MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_amount)],
            PHOTO: [
                MessageHandler(filters.PHOTO, onboard_photo),
                MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_photo),
            ],
        },
        fallbacks=[CommandHandler("cancel", onboard_cancel)],
    )

    app.add_handler(onboarding)
    app.add_handler(CommandHandler("start",       start))
    app.add_handler(CommandHandler("list",        list_plants))
    app.add_handler(CommandHandler("water",       water_command))
    app.add_handler(CommandHandler("status",      status_command))
    app.add_handler(CommandHandler("photo",       photo_command))
    app.add_handler(CommandHandler("health",      health_command))
    app.add_handler(CommandHandler("settopic",    settopic_command))
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

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
