import logging
import os
from datetime import datetime
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes
import db
from weather import fetch_weather, water_adjustment
from i18n import t, lang_for

logger = logging.getLogger(__name__)


def _all_user_ids() -> list[int]:
    """Return every configured user ID (owner first, then second user if set)."""
    users = []
    owner = os.getenv("OWNER_CHAT_ID")
    if owner:
        users.append(int(owner))
    second = os.getenv("SECOND_USER_CHAT_ID")
    if second:
        users.append(int(second))
    if not users:
        logger.warning("No OWNER_CHAT_ID or SECOND_USER_CHAT_ID set")
    return users


async def send_daily_recommendations(context: ContextTypes.DEFAULT_TYPE):
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

    for chat_id in _all_user_ids():
        lang = lang_for(chat_id)
        plants = await db.get_plants_needing_water_for_user(chat_id)

        try:
            if not plants:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=t("daily_all_good", lang, weather=weather_header),
                    parse_mode="Markdown",
                )
                continue

            for plant in plants:
                last_watered = plant["last_watered"]
                if last_watered:
                    days_since = (datetime.now() - datetime.fromisoformat(last_watered)).days
                    if days_since == 0:
                        last_str = t("daily_today", lang)
                    elif days_since == 1:
                        last_str = t("daily_yesterday", lang)
                    else:
                        last_str = t("daily_days_ago", lang, days=days_since)
                else:
                    last_str = t("daily_never", lang)

                recommended_ml = int(plant["watering_amount_ml"] * multiplier)
                msg = await context.bot.send_message(
                    chat_id=chat_id,
                    text=t("daily_rec", lang,
                           weather=weather_header,
                           name=plant["name"],
                           last=last_str,
                           ml=recommended_ml),
                    parse_mode="Markdown",
                )
                await db.save_plant_message(plant["id"], chat_id, msg.message_id)

        except (BadRequest, Forbidden) as e:
            logger.warning("Skipping daily rec for chat_id=%s: %s", chat_id, e)

    logger.info("Sent daily recommendations to all users")


async def send_height_reminder(context: ContextTypes.DEFAULT_TYPE):
    for chat_id in _all_user_ids():
        lang = lang_for(chat_id)
        plants = await db.get_all_plants(user_id=chat_id)
        if not plants:
            continue

        lines = [t("height_reminder", lang)]
        for plant in plants:
            last = plant["height_cm"]
            last_str = f" (last: {last} cm)" if last is not None else ""
            lines.append(f"• `/height {plant['name']} <cm>`{last_str}")

        try:
            await context.bot.send_message(
                chat_id=chat_id, text="\n".join(lines), parse_mode="Markdown"
            )
        except (BadRequest, Forbidden) as e:
            logger.warning("Skipping height reminder for chat_id=%s: %s", chat_id, e)

    logger.info("Sent height reminder to all users")
