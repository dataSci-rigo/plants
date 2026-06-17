import logging
import os
from datetime import datetime
from telegram.ext import ContextTypes
import db
from weather import fetch_weather, water_adjustment

logger = logging.getLogger(__name__)


async def _owner_chat_id() -> int | None:
    """Return the owner's DM chat_id — env var takes priority, falls back to DB."""
    raw = os.getenv("OWNER_CHAT_ID") or await db.get_setting("owner_chat_id")
    return int(raw) if raw else None


async def send_daily_recommendations(context: ContextTypes.DEFAULT_TYPE):
    chat_id = await _owner_chat_id()
    if not chat_id:
        logger.warning("OWNER_CHAT_ID not set — skipping daily recommendations")
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

    if not plants:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"{weather_header}✅ All plants are on schedule today — no watering needed!",
            parse_mode="Markdown",
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

        msg = await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
        await db.save_plant_message(plant["id"], chat_id, msg.message_id)

    logger.info(f"Sent {len(plants)} recommendations → DM {chat_id}")


async def send_height_reminder(context: ContextTypes.DEFAULT_TYPE):
    chat_id = await _owner_chat_id()
    if not chat_id:
        logger.warning("OWNER_CHAT_ID not set — skipping height reminder")
        return

    plants = await db.get_all_plants()
    if not plants:
        return

    lines = ["📏 *Time for a height check-in!*\n", "Reply with `/height <plant> <cm>` for each:"]
    for plant in plants:
        last = plant["height_cm"]
        last_str = f" (last: {last} cm)" if last is not None else ""
        lines.append(f"• `/height {plant['name']} <cm>`{last_str}")

    await context.bot.send_message(chat_id=chat_id, text="\n".join(lines), parse_mode="Markdown")
    logger.info(f"Sent height reminder for {len(plants)} plants → DM {chat_id}")
