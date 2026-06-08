import logging
from datetime import datetime
from telegram.ext import ContextTypes
import db
from weather import fetch_weather, water_adjustment

logger = logging.getLogger(__name__)


async def _target(bot) -> tuple[int | None, int | None]:
    """Return (chat_id, thread_id) to use for all outgoing bot messages."""
    raw_chat = await db.get_setting("target_chat_id") or await db.get_setting("owner_chat_id")
    raw_thread = await db.get_setting("target_thread_id")
    chat_id = int(raw_chat) if raw_chat else None
    thread_id = int(raw_thread) if raw_thread else None
    return chat_id, thread_id


async def send_daily_recommendations(context: ContextTypes.DEFAULT_TYPE):
    chat_id, thread_id = await _target(context.bot)
    if not chat_id:
        logger.warning("No target chat set — skipping daily recommendations")
        return

    weather = await fetch_weather()
    multiplier = 1.0
    weather_header = ""

    if weather:
        multiplier, reason = water_adjustment(weather["temp_c"])
        weather_header = (
            f"🌡️ {weather['description'].capitalize()}, "
            f"{weather['temp_c']:.0f}°C, {weather['humidity']}% humidity"
        )
        if multiplier != 1.0:
            direction = "more" if multiplier > 1.0 else "less"
            pct = abs(round((multiplier - 1) * 100))
            weather_header += f" — recommending {pct}% {direction} water ({reason})"
        weather_header += "\n\n"

    plants = await db.get_plants_needing_water()

    send_kwargs = {"chat_id": chat_id, "parse_mode": "Markdown"}
    if thread_id:
        send_kwargs["message_thread_id"] = thread_id

    if not plants:
        await context.bot.send_message(
            text=f"{weather_header}✅ All plants are on schedule today — no watering needed!",
            **send_kwargs,
        )
        return

    for plant in plants:
        last_watered = plant["last_watered"]
        if last_watered:
            days_since = (datetime.now() - datetime.fromisoformat(last_watered)).days
            if days_since == 0:
                last_str = "watered today"
            elif days_since == 1:
                last_str = "watered yesterday"
            else:
                last_str = f"last watered {days_since} days ago"
        else:
            last_str = "never watered"

        recommended_ml = int(plant["watering_amount_ml"] * multiplier)
        text = (
            f"{weather_header}"
            f"🌿 *{plant['name']}*\n"
            f"⏱️ {last_str}\n"
            f"💧 Recommended: *{recommended_ml} ml*\n\n"
            f"Reply with the amount you gave (e.g. `{recommended_ml}`) or `skip`."
        )

        msg = await context.bot.send_message(text=text, **send_kwargs)
        await db.save_plant_message(plant["id"], chat_id, msg.message_id)

    logger.info(f"Sent {len(plants)} recommendations → chat {chat_id} thread {thread_id}")
