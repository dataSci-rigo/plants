import asyncio
import os
import re
import socket
import subprocess
import sys
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
import db
from ai import analyze_plant_health

logger = logging.getLogger(__name__)

# Onboarding conversation states
(
    NAME, PLANT_TYPE, LOCATION, POT_DEPTH, POT_WIDTH, SOIL_ALKALINITY,
    SOIL_TYPE, FERTILIZER_TYPE, FERTILIZER_AMOUNT, FERTILIZER_FREQUENCY,
    FACING, HEIGHT, SUNLIGHT_ACTUAL, SUNLIGHT_NEEDED, FREQUENCY, AMOUNT, PHOTO,
) = range(17)

_FACING_NORMALIZE = {
    "north": "north", "n": "north",
    "south": "south", "s": "south",
    "east": "east", "e": "east",
    "west": "west", "w": "west",
    "northeast": "northeast", "north east": "northeast", "ne": "northeast",
    "northwest": "northwest", "north west": "northwest", "nw": "northwest",
    "southeast": "southeast", "south east": "southeast", "se": "southeast",
    "southwest": "southwest", "south west": "southwest", "sw": "southwest",
    "no shade": "no shade", "noshade": "no shade", "full sun": "no shade", "none": "no shade",
}

# Flask server subprocess handle (module-level so it persists across calls)
_flask_process: subprocess.Popen | None = None


def _get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _get_tailscale_ip() -> str | None:
    try:
        result = subprocess.run(
            ["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=3
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    # Fallback: look for a 100.x.x.x address on any interface
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            ip = info[4][0]
            if ip.startswith("100."):
                return ip
    except Exception:
        pass
    return None


# ── Core commands ────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    await db.set_setting("owner_chat_id", chat_id)
    await update.message.reply_text(
        "🌱 *Plant Tracker*\n\n"
        "/add — Onboard a new plant\n"
        "/list — All plants & last watered\n"
        "/water `<plant>` `[ml]` — Log a watering\n"
        "/status `<plant>` — Watering history\n"
        "/photo `<plant>` — Get plant photo\n"
        "/health `<plant>` — AI health check\n"
        "/height `<plant>` `<cm>` — Log a new height reading\n"
        "/startserver — Start the plant dashboard\n"
        "/stopserver — Stop the dashboard\n\n"
        "Reply to any daily recommendation to log watering or update a photo.",
        parse_mode="Markdown",
    )


async def settopic_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Run this from inside the plants forum topic to route all bot messages there."""
    chat_id = update.effective_chat.id
    thread_id = update.message.message_thread_id if update.message else None

    await db.set_setting("target_chat_id", str(chat_id))
    if thread_id:
        await db.set_setting("target_thread_id", str(thread_id))
        await update.message.reply_text(
            f"✅ Routing enabled!\nAll plant messages will come here.\n"
            f"`chat_id={chat_id}` · `thread_id={thread_id}`",
            parse_mode="Markdown",
        )
    else:
        await db.set_setting("target_thread_id", "")
        await update.message.reply_text(
            f"✅ Routing enabled for this chat (`{chat_id}`).",
            parse_mode="Markdown",
        )


async def startserver_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global _flask_process
    if _flask_process and _flask_process.poll() is None:
        await update.message.reply_text("⚠️ Server is already running. Use /stopserver to stop it.")
        return

    port = int(os.getenv("PORT_PLANTS", os.getenv("FLASK_PORT", 5060)))
    web_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web.py")

    _flask_process = subprocess.Popen(
        [sys.executable, web_py],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    await asyncio.sleep(1.5)  # give Flask a moment to bind

    if _flask_process.poll() is not None:
        await update.message.reply_text("❌ Server failed to start. Check the logs on the machine.")
        _flask_process = None
        return

    local_ip = _get_local_ip()
    tailscale_ip = _get_tailscale_ip()

    lines = [f"🌐 *Plant dashboard started!*\n"]
    lines.append(f"🏠 WiFi: `http://{local_ip}:{port}`")
    if tailscale_ip:
        lines.append(f"🔒 Tailscale: `http://{tailscale_ip}:{port}`")
    lines.append(f"\n🛑 To stop: /stopserver")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def stopserver_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global _flask_process
    if not _flask_process or _flask_process.poll() is not None:
        await update.message.reply_text("ℹ️ Server is not running.")
        _flask_process = None
        return

    _flask_process.terminate()
    try:
        _flask_process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        _flask_process.kill()
    _flask_process = None
    await update.message.reply_text("✅ Dashboard stopped.")


async def list_plants(update: Update, context: ContextTypes.DEFAULT_TYPE):
    plants = await db.get_all_plants()
    if not plants:
        await update.message.reply_text("No plants yet — use /add to get started.")
        return

    lines = ["🌿 *Your Plants*\n"]
    for p in plants:
        last = await db.get_last_watered(p["id"])
        if last:
            from datetime import datetime
            days = (datetime.now() - datetime.fromisoformat(last[0])).days
            last_str = "today" if days == 0 else f"{days}d ago"
        else:
            last_str = "never"
        photo_icon = "📷 " if p["telegram_file_id"] or p["image_data"] else ""
        lines.append(
            f"{photo_icon}• *{p['name']}* ({p['plant_type'] or '?'}) — last watered: {last_str}"
        )

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def water_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Usage: `/water <plant name> [ml]`", parse_mode="Markdown"
        )
        return

    args = context.args
    amount_ml = None
    if args[-1].isdigit():
        amount_ml = int(args[-1])
        plant_name = " ".join(args[:-1])
    else:
        plant_name = " ".join(args)

    plant = await db.get_plant_by_name(plant_name)
    if not plant:
        await update.message.reply_text(f"Plant '{plant_name}' not found. Use /list to see all plants.")
        return

    if amount_ml is None:
        amount_ml = plant["watering_amount_ml"]

    await db.log_watering(plant["id"], amount_ml)
    await update.message.reply_text(
        f"✅ Logged *{amount_ml} ml* for *{plant['name']}*", parse_mode="Markdown"
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Usage: `/status <plant name>`", parse_mode="Markdown"
        )
        return

    plant = await db.get_plant_by_name(" ".join(context.args))
    if not plant:
        await update.message.reply_text("Plant not found. Use /list to see all plants.")
        return

    history = await db.get_watering_history(plant["id"], limit=10)

    if plant["fertilizer_type"]:
        fert_line = plant["fertilizer_type"]
        if plant["fertilizer_amount"]:
            fert_line += f", {plant['fertilizer_amount']}"
        if plant["fertilizer_frequency_days"]:
            fert_line += f", every {plant['fertilizer_frequency_days']} days"
    else:
        fert_line = "none"

    lines = [
        f"🌿 *{plant['name']}*",
        f"Type: {plant['plant_type'] or 'Unknown'}",
        f"Location: {plant['location'] or '?'}",
        f"Pot depth: {plant['pot_depth_cm'] or '?'} cm",
        f"Pot width: {plant['pot_width_cm'] or '?'} cm",
        f"Soil volume: {plant['soil_volume_l'] or '?'} L",
        f"Soil: {plant['soil_alkalinity'] or '?'}, {plant['soil_type'] or '?'}",
        f"Fertilizer: {fert_line}",
        f"Facing: {plant['facing'] or '?'}",
        f"Height: {plant['height_cm'] or '?'} cm",
        f"Watering frequency: every {plant['watering_frequency_days']} days",
        f"Amount per session: {plant['watering_amount_ml']} ml\n",
        "💧 *Recent waterings:*",
    ]
    if history:
        for h in history:
            lines.append(f"  • {h['watered_at'][:16]} — {h['amount_ml']} ml")
    else:
        lines.append("  No history yet.")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def photo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Usage: `/photo <plant name>`", parse_mode="Markdown"
        )
        return

    plant = await db.get_plant_by_name(" ".join(context.args))
    if not plant:
        await update.message.reply_text("Plant not found. Use /list to see all plants.")
        return

    if not plant["telegram_file_id"] and not plant["image_data"]:
        await update.message.reply_text(
            f"No photo stored for *{plant['name']}*. Send a photo as a reply to any recommendation.",
            parse_mode="Markdown",
        )
        return

    caption = f"📷 *{plant['name']}*"
    if plant["telegram_file_id"]:
        await update.message.reply_photo(
            photo=plant["telegram_file_id"], caption=caption, parse_mode="Markdown"
        )
    else:
        await update.message.reply_photo(
            photo=plant["image_data"], caption=caption, parse_mode="Markdown"
        )


async def health_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        plant = await db.get_plant_by_name(" ".join(context.args))
        if not plant:
            await update.message.reply_text("Plant not found. Use /list to see all plants.")
            return
        await _run_health_check(update.effective_chat.id, dict(plant), context)
        return

    plants = await db.get_all_plants()
    if not plants:
        await update.message.reply_text("No plants yet — use /add to get started.")
        return

    keyboard, row = [], []
    for p in plants:
        row.append(InlineKeyboardButton(p["name"], callback_data=f"health:{p['id']}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    await update.message.reply_text(
        "Which plant would you like to analyze?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def health_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    plant_id = int(query.data.split(":")[1])
    plant = await db.get_plant(plant_id)
    if not plant:
        await query.edit_message_text("Plant not found.")
        return
    await query.edit_message_text(f"Analyzing *{plant['name']}*…", parse_mode="Markdown")
    await _run_health_check(update.effective_chat.id, dict(plant), context)


async def _run_health_check(chat_id: int, plant: dict, context: ContextTypes.DEFAULT_TYPE):
    history = await db.get_watering_history(plant["id"], limit=10)
    plant["history"] = [dict(h) for h in history]
    image_data = plant.get("image_data")

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    response = await analyze_plant_health(plant, image_data)

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"🔬 *Health check — {plant['name']}*\n\n{response}",
        parse_mode="Markdown",
    )


# ── Reply handlers ───────────────────────────────────────────────────────────

async def handle_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Parse a text reply to a plant recommendation and log watering."""
    if not update.message.reply_to_message:
        return

    chat_id = update.effective_chat.id
    replied_id = update.message.reply_to_message.message_id
    plant = await db.get_plant_by_message(chat_id, replied_id)
    if not plant:
        return

    text = update.message.text.strip().lower()
    if text in ("skip", "s", "no", "later", "x"):
        await update.message.reply_text(
            f"Skipped — *{plant['name']}* not watered today.", parse_mode="Markdown"
        )
        return

    match = re.search(r"(\d+)", text)
    amount_ml = int(match.group(1)) if match else plant["watering_amount_ml"]

    await db.log_watering(plant["id"], amount_ml)
    await update.message.reply_text(
        f"✅ Logged *{amount_ml} ml* for *{plant['name']}*", parse_mode="Markdown"
    )


async def handle_photo_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Store a photo sent as a reply to a plant recommendation."""
    if not update.message.reply_to_message:
        return

    chat_id = update.effective_chat.id
    replied_id = update.message.reply_to_message.message_id
    plant = await db.get_plant_by_message(chat_id, replied_id)
    if not plant:
        return

    photo = update.message.photo[-1]
    file_obj = await context.bot.get_file(photo.file_id)
    image_bytes = await file_obj.download_as_bytearray()

    await db.update_plant_image(plant["id"], bytes(image_bytes), photo.file_id)
    await update.message.reply_text(
        f"📷 Photo updated for *{plant['name']}*!", parse_mode="Markdown"
    )


# ── Onboarding conversation ──────────────────────────────────────────────────

async def onboard_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "🌱 *Add a new plant*\n\nWhat's the plant's name?",
        parse_mode="Markdown",
    )
    return NAME


async def onboard_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if await db.get_plant_by_name(name):
        await update.message.reply_text(
            f"A plant named *{name}* already exists. Try a different name.",
            parse_mode="Markdown",
        )
        return NAME
    context.user_data["name"] = name
    await update.message.reply_text(
        f"What *type* of plant is *{name}*?\n(e.g. succulent, fern, tomato, cactus)",
        parse_mode="Markdown",
    )
    return PLANT_TYPE


async def onboard_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["plant_type"] = update.message.text.strip()
    await update.message.reply_text(
        "Is it planted in a *pot* or in the *ground*?", parse_mode="Markdown"
    )
    return LOCATION


async def onboard_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    if text not in ("pot", "ground"):
        await update.message.reply_text("Please answer `pot` or `ground`.", parse_mode="Markdown")
        return LOCATION
    context.user_data["location"] = text

    if text == "ground":
        context.user_data["pot_depth_cm"] = None
        context.user_data["pot_width_cm"] = None
        await update.message.reply_text(
            "What's the soil alkalinity? (e.g. `acidic`, `neutral`, `alkaline`, or a pH like `6.5`) — or `?` to skip.",
            parse_mode="Markdown",
        )
        return SOIL_ALKALINITY

    await update.message.reply_text("How deep is the pot? (cm, e.g. `15`)", parse_mode="Markdown")
    return POT_DEPTH


async def onboard_pot_depth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    if text in ("?", "idk", "skip", "unknown"):
        context.user_data["pot_depth_cm"] = None
    else:
        try:
            context.user_data["pot_depth_cm"] = float(text)
        except ValueError:
            await update.message.reply_text("Enter a number in cm (e.g. `20`) or `?` to skip.", parse_mode="Markdown")
            return POT_DEPTH
    await update.message.reply_text("How *wide* is the pot? (cm, e.g. `25`) — or `?` to skip.", parse_mode="Markdown")
    return POT_WIDTH


async def onboard_pot_width(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    if text in ("?", "idk", "skip", "unknown"):
        context.user_data["pot_width_cm"] = None
    else:
        try:
            context.user_data["pot_width_cm"] = float(text)
        except ValueError:
            await update.message.reply_text("Enter a number in cm (e.g. `25`) or `?` to skip.", parse_mode="Markdown")
            return POT_WIDTH
    await update.message.reply_text(
        "What's the soil alkalinity? (e.g. `acidic`, `neutral`, `alkaline`, or a pH like `6.5`) — or `?` to skip.",
        parse_mode="Markdown",
    )
    return SOIL_ALKALINITY


async def onboard_soil_alkalinity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data["soil_alkalinity"] = None if text.lower() in ("?", "idk", "skip", "unknown") else text
    await update.message.reply_text(
        "What soil type? (e.g. `potting mix`, `clay`, `sandy`, `loam`) — or `?` to skip.",
        parse_mode="Markdown",
    )
    return SOIL_TYPE


async def onboard_soil_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data["soil_type"] = None if text.lower() in ("?", "idk", "skip", "unknown") else text
    await update.message.reply_text(
        "What *type* of fertilizer do you use, if any? (e.g. `fish emulsion`, `10-10-10`) — or `none`/`?` to skip.",
        parse_mode="Markdown",
    )
    return FERTILIZER_TYPE


_NONE_WORDS = ("?", "idk", "skip", "unknown", "none")


async def onboard_fertilizer_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.lower() in _NONE_WORDS:
        context.user_data["fertilizer_type"] = None
        context.user_data["fertilizer_amount"] = None
        context.user_data["fertilizer_frequency_days"] = None
        await update.message.reply_text(
            "Which way does it face — `north`, `south`, `east`, `west`, or `no shade`? — or `?` to skip.",
            parse_mode="Markdown",
        )
        return FACING

    context.user_data["fertilizer_type"] = text
    await update.message.reply_text(
        "How much fertilizer per application? (e.g. `1 tbsp`, `10 ml`) — or `?` to skip.",
        parse_mode="Markdown",
    )
    return FERTILIZER_AMOUNT


async def onboard_fertilizer_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data["fertilizer_amount"] = None if text.lower() in _NONE_WORDS else text
    await update.message.reply_text(
        "How often do you fertilize? (days, e.g. `30`) — or `?` to skip.",
        parse_mode="Markdown",
    )
    return FERTILIZER_FREQUENCY


async def onboard_fertilizer_frequency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    if text in _NONE_WORDS:
        context.user_data["fertilizer_frequency_days"] = None
    else:
        try:
            context.user_data["fertilizer_frequency_days"] = int(text)
        except ValueError:
            await update.message.reply_text(
                "Enter a whole number of days (e.g. `30`) or `?` to skip.", parse_mode="Markdown"
            )
            return FERTILIZER_FREQUENCY
    await update.message.reply_text(
        "Which way does it face — `north`, `south`, `east`, `west`, or `no shade`? — or `?` to skip.",
        parse_mode="Markdown",
    )
    return FACING


async def onboard_facing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    if text in ("?", "idk", "skip", "unknown"):
        context.user_data["facing"] = None
    elif text in _FACING_NORMALIZE:
        context.user_data["facing"] = _FACING_NORMALIZE[text]
    else:
        await update.message.reply_text(
            "Please answer a compass direction (e.g. `north`, `southwest`, `NW`) or `no shade`, or `?` to skip.",
            parse_mode="Markdown",
        )
        return FACING
    await update.message.reply_text(
        "How tall is the plant today? (cm, e.g. `30`) — or `?` to skip.", parse_mode="Markdown"
    )
    return HEIGHT


async def onboard_height(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    if text in ("?", "idk", "skip", "unknown"):
        context.user_data["height_cm"] = None
    else:
        try:
            context.user_data["height_cm"] = float(text)
        except ValueError:
            await update.message.reply_text("Enter a number in cm (e.g. `30`) or `?` to skip.", parse_mode="Markdown")
            return HEIGHT
    await update.message.reply_text(
        "How many hours of *direct sunlight* does it get per day? (e.g. `4`) — or `?` to skip.",
        parse_mode="Markdown",
    )
    return SUNLIGHT_ACTUAL


async def onboard_sunlight_actual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    if text in ("?", "idk", "skip", "unknown"):
        context.user_data["sunlight_hours_actual"] = None
    else:
        try:
            context.user_data["sunlight_hours_actual"] = float(text)
        except ValueError:
            await update.message.reply_text("Enter a number (e.g. `4`) or `?` to skip.", parse_mode="Markdown")
            return SUNLIGHT_ACTUAL
    await update.message.reply_text(
        "How many hours of sunlight does it *need*? (e.g. `6`) — or `?` for a suggestion.",
        parse_mode="Markdown",
    )
    return SUNLIGHT_NEEDED


async def onboard_sunlight_needed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from ai import suggest_sunlight_needs
    text = update.message.text.strip().lower()
    if text in _UNSURE:
        await update.message.reply_text("🔍 Looking up sunlight requirements…")
        try:
            rec = await suggest_sunlight_needs(
                context.user_data["name"],
                context.user_data["plant_type"],
                context.user_data.get("facing"),
            )
            context.user_data["sunlight_hours_needed"] = rec["hours_needed"]
            note = f"\n_{rec['note']}_" if rec.get("note") else ""
            actual = context.user_data.get("sunlight_hours_actual")
            gap = ""
            if actual is not None:
                diff = rec["hours_needed"] - actual
                if diff > 0.5:
                    gap = f"\n⚠️ Currently getting {actual}h — needs {diff:.1f}h more."
                elif diff < -0.5:
                    gap = f"\n✅ Getting {actual}h — more than enough."
            await update.message.reply_text(
                f"☀️ *{context.user_data['plant_type']}* needs ~*{rec['hours_needed']}h* of direct sun.{note}{gap}\n\n"
                "How often does it need watering? (days, e.g. `7`) — or `?` for a suggestion.",
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error(f"Sunlight lookup failed: {e}")
            context.user_data["sunlight_hours_needed"] = None
            await update.message.reply_text(
                "Couldn't reach the AI. How often does it need watering? (days, e.g. `7`)",
                parse_mode="Markdown",
            )
        return FREQUENCY

    try:
        context.user_data["sunlight_hours_needed"] = float(text)
    except ValueError:
        await update.message.reply_text("Enter a number (e.g. `6`) or `?` for a suggestion.", parse_mode="Markdown")
        return SUNLIGHT_NEEDED
    await update.message.reply_text(
        "How often does it need watering? (days, e.g. `7`) — or `?` for a suggestion.",
        parse_mode="Markdown",
    )
    return FREQUENCY


_UNSURE = {"?", "idk", "i don't know", "not sure", "unsure", "unknown", "help", "idc"}


async def onboard_frequency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from ai import suggest_watering_schedule
    text = update.message.text.strip().lower()

    if text in _UNSURE:
        await update.message.reply_text("🔍 Looking up care requirements for your plant…")
        try:
            rec = await suggest_watering_schedule(
                context.user_data["name"],
                context.user_data["plant_type"],
                context.user_data.get("pot_depth_cm"),
            )
            context.user_data["watering_frequency_days"] = rec["frequency_days"]
            context.user_data["watering_amount_ml"] = rec["amount_ml"]
            note = f"\n_{rec['note']}_" if rec.get("note") else ""
            await update.message.reply_text(
                f"✅ Recommendation for *{context.user_data['plant_type']}*:\n"
                f"• Every *{rec['frequency_days']} days*\n"
                f"• *{rec['amount_ml']} ml* per session{note}\n\n"
                "Both saved! Last step: send a *photo* or type `skip`.",
                parse_mode="Markdown",
            )
            return PHOTO  # skip AMOUNT — both values are filled
        except Exception as e:
            logger.error(f"Schedule lookup failed: {e}")
            await update.message.reply_text(
                "Couldn't reach the AI right now. Enter frequency in days (e.g. `7`):",
                parse_mode="Markdown",
            )
            return FREQUENCY

    try:
        context.user_data["watering_frequency_days"] = int(text)
    except ValueError:
        await update.message.reply_text(
            "Enter a whole number of days (e.g. `7`), or `?` for a recommendation.",
            parse_mode="Markdown",
        )
        return FREQUENCY
    await update.message.reply_text(
        "How much water per session? (ml, e.g. `200`) — or `?` for a suggestion.",
        parse_mode="Markdown",
    )
    return AMOUNT


async def onboard_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from ai import suggest_watering_schedule
    text = update.message.text.strip().lower()

    if text in _UNSURE:
        await update.message.reply_text("🔍 Looking up a recommendation…")
        try:
            rec = await suggest_watering_schedule(
                context.user_data["name"],
                context.user_data["plant_type"],
                context.user_data.get("pot_depth_cm"),
            )
            context.user_data["watering_amount_ml"] = rec["amount_ml"]
            await update.message.reply_text(
                f"✅ Suggested *{rec['amount_ml']} ml* per session for a {context.user_data['plant_type']}. Saved!\n\n"
                "Last step: send a *photo* or type `skip`.",
                parse_mode="Markdown",
            )
            return PHOTO
        except Exception as e:
            logger.error(f"Amount lookup failed: {e}")
            await update.message.reply_text(
                "Couldn't reach the AI right now. Enter the amount in ml (e.g. `200`):",
                parse_mode="Markdown",
            )
            return AMOUNT

    try:
        context.user_data["watering_amount_ml"] = int(text)
    except ValueError:
        await update.message.reply_text(
            "Enter a whole number in ml (e.g. `200`) or `?` for a suggestion.",
            parse_mode="Markdown",
        )
        return AMOUNT
    await update.message.reply_text(
        "Last step: send a *photo* of the plant, or type `skip` to add it later.",
        parse_mode="Markdown",
    )
    return PHOTO


async def onboard_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = context.user_data
    image_data, file_id = None, None

    if update.message.photo:
        photo = update.message.photo[-1]
        file_id = photo.file_id
        file_obj = await context.bot.get_file(file_id)
        image_data = bytes(await file_obj.download_as_bytearray())

    plant_id = await db.add_plant(
        name=data["name"],
        plant_type=data["plant_type"],
        pot_depth_cm=data.get("pot_depth_cm"),
        pot_width_cm=data.get("pot_width_cm"),
        location=data.get("location"),
        soil_alkalinity=data.get("soil_alkalinity"),
        soil_type=data.get("soil_type"),
        fertilizer_type=data.get("fertilizer_type"),
        fertilizer_amount=data.get("fertilizer_amount"),
        fertilizer_frequency_days=data.get("fertilizer_frequency_days"),
        facing=data.get("facing"),
        height_cm=data.get("height_cm"),
        sunlight_hours_actual=data.get("sunlight_hours_actual"),
        sunlight_hours_needed=data.get("sunlight_hours_needed"),
        watering_frequency_days=data["watering_frequency_days"],
        watering_amount_ml=data["watering_amount_ml"],
    )

    if image_data:
        await db.update_plant_image(plant_id, image_data, file_id)

    context.user_data.clear()

    if data.get("location") == "pot":
        depth = f"{data.get('pot_depth_cm')} cm" if data.get("pot_depth_cm") else "?"
        width = f"{data.get('pot_width_cm')} cm" if data.get("pot_width_cm") else "?"
        location_line = f"Pot: {depth} deep × {width} wide"
        volume = db.estimate_soil_volume_l(data.get("pot_depth_cm"), data.get("pot_width_cm"))
        if volume:
            location_line += f" (~{volume} L soil)"
    else:
        location_line = "Planted in the ground"

    height_str = f"{data.get('height_cm')} cm" if data.get("height_cm") else "?"

    if data.get("fertilizer_type"):
        fert_line = data["fertilizer_type"]
        if data.get("fertilizer_amount"):
            fert_line += f", {data['fertilizer_amount']}"
        if data.get("fertilizer_frequency_days"):
            fert_line += f", every {data['fertilizer_frequency_days']} days"
    else:
        fert_line = "none"

    await update.message.reply_text(
        f"✅ *{data['name']}* added!\n\n"
        f"Type: {data['plant_type']}\n"
        f"{location_line}\n"
        f"Soil: {data.get('soil_alkalinity') or '?'}, {data.get('soil_type') or '?'}\n"
        f"Fertilizer: {fert_line}\n"
        f"Facing: {data.get('facing') or '?'}\n"
        f"Height: {height_str}\n"
        f"Waters every {data['watering_frequency_days']} days, {data['watering_amount_ml']} ml\n\n"
        "Use /list to see all your plants. Use /height to update height anytime.",
        parse_mode="Markdown",
    )
    return ConversationHandler.END


# ── Height tracking ──────────────────────────────────────────────────────────

async def height_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Usage: /height <plant name> <cm> — log a new height reading."""
    if len(context.args) < 2 or not context.args[-1].replace(".", "", 1).isdigit():
        await update.message.reply_text(
            "Usage: `/height <plant name> <cm>`\ne.g. `/height Monstera 45`",
            parse_mode="Markdown",
        )
        return

    height_cm = float(context.args[-1])
    plant_name = " ".join(context.args[:-1])
    plant = await db.get_plant_by_name(plant_name)
    if not plant:
        await update.message.reply_text(f"Plant '{plant_name}' not found. Use /list to see all plants.")
        return

    await db.log_height(plant["id"], height_cm)
    await update.message.reply_text(
        f"📏 Logged *{height_cm} cm* for *{plant['name']}*", parse_mode="Markdown"
    )


async def onboard_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Cancelled. Use /add to start over.")
    return ConversationHandler.END
