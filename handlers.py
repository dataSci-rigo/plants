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
import ai as _ai
import perenual
from ai import analyze_plant_health
from i18n import t, lang_for, LOCATION_ALIASES, SKIP_WORDS, NONE_WORDS, UNSURE

logger = logging.getLogger(__name__)

# Onboarding conversation states
(
    NAME, PLANT_TYPE, LOCATION, POT_DEPTH, POT_WIDTH, SOIL_ALKALINITY,
    SOIL_TYPE, FERTILIZER_TYPE, FERTILIZER_AMOUNT, FERTILIZER_FREQUENCY,
    FACING, HEIGHT, SUNLIGHT_ACTUAL, SUNLIGHT_NEEDED, FREQUENCY, AMOUNT, PHOTO,
) = range(17)

_FACING_NORMALIZE = {
    "north": "north", "n": "north", "norte": "north",
    "south": "south", "s": "south", "sur": "south",
    "east": "east",  "e": "east",  "este": "east",
    "west": "west",  "w": "west",  "oeste": "west",
    "northeast": "northeast", "north east": "northeast", "ne": "northeast", "noreste": "northeast",
    "northwest": "northwest", "north west": "northwest", "nw": "northwest", "noroeste": "northwest",
    "southeast": "southeast", "south east": "southeast", "se": "southeast", "sureste": "southeast",
    "southwest": "southwest", "south west": "southwest", "sw": "southwest", "suroeste": "southwest",
    "no shade": "no shade", "noshade": "no shade", "full sun": "no shade",
    "sin sombra": "no shade", "sol directo": "no shade",
}

_flask_process: subprocess.Popen | None = None


# ── Plant name resolution helpers ────────────────────────────────────────────

async def _find_plant_in_args(args: list[str], uid: int):
    """
    Given a token list, find a plant by exact then partial match.
    Tries progressively shorter prefixes so extra args can trail the name.
    Returns (plant, extra_args, candidates):
      - plant set, candidates empty  → unambiguous match
      - plant None, candidates set   → multiple partial matches (show picker)
      - plant None, candidates empty → nothing found
    """
    # 1. Exact match: try all tokens as name, then shorter prefixes
    for i in range(len(args), 0, -1):
        name = " ".join(args[:i])
        plant = await db.get_plant_by_name(name, user_id=uid)
        if plant:
            return plant, list(args[i:]), []

    # 2. Partial (LIKE) match: same progressive approach
    for i in range(len(args), 0, -1):
        name = " ".join(args[:i])
        matches = await db.search_plants(name, user_id=uid)
        if matches:
            return None, list(args[i:]), list(matches)

    return None, [], []


async def _show_plant_picker(message, context, candidates, command: str,
                              extra_args: list, lang: str):
    """Send an inline keyboard of matching plants and stash extra_args for the callback."""
    context.user_data["_pick_args"] = extra_args
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(p["name"], callback_data=f"plant_pick:{command}:{p['id']}")]
        for p in candidates
    ])
    await message.reply_text(t("plant_picker", lang), reply_markup=kb)


async def plant_pick_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Dispatch after the user selects a plant from the partial-match picker."""
    query = update.callback_query
    await query.answer()
    lang = _lang(update)
    uid = update.effective_chat.id

    _, command, plant_id_str = query.data.split(":", 2)
    plant = await db.get_plant_by_id(int(plant_id_str))
    if not plant:
        await query.edit_message_text(t("plant_not_found", lang))
        return

    extra = context.user_data.pop("_pick_args", [])
    plant = dict(plant)
    await query.edit_message_text(f"🌿 *{plant['name']}*", parse_mode="Markdown")
    bot = context.bot

    if command == "water":
        amount_ml = int(extra[0]) if extra and extra[0].isdigit() else plant["watering_amount_ml"]
        await db.log_watering(plant["id"], amount_ml)
        await bot.send_message(uid, t("water_logged", lang, ml=amount_ml, name=plant["name"]), parse_mode="Markdown")

    elif command == "status":
        await _send_status(bot, uid, plant, lang)

    elif command == "photo":
        await _send_photo(bot, uid, plant, lang)

    elif command == "health":
        await _run_health_check(uid, plant, context, lang)

    elif command == "height":
        if extra and extra[-1].replace(".", "", 1).isdigit():
            h = float(extra[-1])
            await db.log_height(plant["id"], h)
            await bot.send_message(uid, t("height_logged", lang, cm=h, name=plant["name"]), parse_mode="Markdown")
        else:
            await bot.send_message(uid, t("height_usage", lang), parse_mode="Markdown")

    elif command == "pest":
        desc = " ".join(extra)
        if desc:
            await db.log_issue(plant["id"], "bug", desc)
            await bot.send_message(uid, t("pest_logged", lang, name=plant["name"], desc=desc), parse_mode="Markdown")
        else:
            await bot.send_message(uid, t("pest_usage", lang), parse_mode="Markdown")

    elif command == "disease":
        desc = " ".join(extra)
        if desc:
            await db.log_issue(plant["id"], "fungal", desc)
            await bot.send_message(uid, t("disease_logged", lang, name=plant["name"], desc=desc), parse_mode="Markdown")
        else:
            await bot.send_message(uid, t("disease_usage", lang), parse_mode="Markdown")

    elif command == "treat":
        ingredients = {k: False for k in _TREAT_INGREDIENTS}
        notes_parts = []
        for token in extra:
            if token.lower() in _TREAT_INGREDIENTS:
                ingredients[token.lower()] = True
            else:
                notes_parts.append(token)
        if any(ingredients.values()):
            notes = " ".join(notes_parts) or None
            await db.log_treatment(plant["id"], notes=notes, **ingredients)
            used = [k for k, v in ingredients.items() if v]
            label = " + ".join(used) + (f" ({notes})" if notes else "")
            await bot.send_message(uid, t("treat_logged", lang, name=plant["name"], ingredients=label), parse_mode="Markdown")
        else:
            await bot.send_message(uid, t("treat_nothing", lang), parse_mode="Markdown")

    elif command == "issues":
        await _send_issues(bot, uid, plant, lang)

    elif command == "repot":
        new_width = new_depth = new_soil = None
        try:
            if extra: new_width = float(extra[0])
            if len(extra) > 1: new_depth = float(extra[1])
            if len(extra) > 2: new_soil = " ".join(extra[2:])
        except ValueError:
            new_soil = " ".join(extra)
        await db.log_repotting(plant["id"],
                                old_width=plant["pot_width_cm"], old_depth=plant["pot_depth_cm"],
                                old_soil=plant["soil_type"],
                                new_width=new_width, new_depth=new_depth, new_soil=new_soil)
        parts = [t("repot_logged", lang, name=plant["name"])]
        if new_width or new_depth:
            parts.append(f"🪴 New pot: {new_width or '?'} × {new_depth or '?'} cm")
        if new_soil:
            parts.append(f"🪨 Soil: {new_soil}")
        await bot.send_message(uid, "\n".join(parts), parse_mode="Markdown")

    elif command == "care":
        await _send_care(bot, uid, plant, lang)

    elif command == "report":
        await _show_report_menu(uid, plant, context, lang)


# ── Shared display helpers (used by commands + plant_pick_callback) ───────────

async def _send_status(bot, uid: int, plant: dict, lang: str):
    history = await db.get_watering_history(plant["id"], limit=10)
    if plant.get("fertilizer_type"):
        fert_line = t("status_fert", lang,
                      type=plant["fertilizer_type"],
                      amount=plant["fertilizer_amount"] or "?",
                      freq=plant["fertilizer_frequency_days"] or "?")
    else:
        fert_line = t("status_no_fert", lang)

    companion_line = ""
    if plant.get("pot_group") and plant.get("user_id"):
        companions = await db.get_pot_companions(plant["id"], plant["pot_group"], plant["user_id"])
        if companions:
            companion_line = f"\nPot companions: {', '.join(c['name'] for c in companions)}"

    lines = [
        f"🌿 *{plant['name']}*",
        f"Type: {plant.get('plant_type') or '?'}",
        f"Location: {plant.get('location') or '?'}",
        f"Pot: {plant.get('pot_depth_cm') or '?'} cm deep × {plant.get('pot_width_cm') or '?'} cm wide",
        f"Soil volume: {plant.get('soil_volume_l') or '?'} L",
        f"Soil: {plant.get('soil_alkalinity') or '?'}, {plant.get('soil_type') or '?'}",
        f"Fertilizer: {fert_line}",
        f"Facing: {plant.get('facing') or '?'}",
        f"Height: {plant.get('height_cm') or '?'} cm",
        f"Sun: {plant.get('sunlight_hours_actual') or '?'}h / {plant.get('sunlight_hours_needed') or '?'}h needed",
        f"Watering: every {plant.get('watering_frequency_days', '?')} days, {plant.get('watering_amount_ml', '?')} ml{companion_line}\n",
        "💧 *Recent waterings:*",
    ]
    if history:
        for h in history:
            lines.append(f"  • {h['watered_at'][:16]} — {h['amount_ml']} ml")
    else:
        lines.append(f"  {t('status_no_hist', lang)}")
    await bot.send_message(uid, "\n".join(lines), parse_mode="Markdown")


async def _send_photo(bot, uid: int, plant: dict, lang: str):
    caption = f"📷 *{plant['name']}*\n\n_Reply with a new photo to update it._"
    if plant.get("telegram_file_id"):
        msg = await bot.send_photo(uid, photo=plant["telegram_file_id"],
                                   caption=caption, parse_mode="Markdown")
    elif plant.get("image_data"):
        msg = await bot.send_photo(uid, photo=plant["image_data"],
                                   caption=caption, parse_mode="Markdown")
    else:
        msg = await bot.send_message(
            uid,
            t("photo_none", lang, name=plant["name"]) + "\n\n_Reply to this message with a photo to add one._",
            parse_mode="Markdown",
        )
    await db.save_plant_message(plant["id"], uid, msg.message_id)


async def _send_issues(bot, uid: int, plant: dict, lang: str):
    open_issues = await db.get_issues(plant["id"], open_only=True)
    if not open_issues:
        await bot.send_message(uid, t("issues_none", lang, name=plant["name"]), parse_mode="Markdown")
        return
    lines = [t("issues_header", lang, name=plant["name"])]
    for iss in open_issues:
        lines.append(t("issue_row", lang, cat=iss["category"],
                       desc=iss["description"], date=iss["observed_at"][:10]))
    await bot.send_message(uid, "\n".join(lines), parse_mode="Markdown")


async def _send_care(bot, uid: int, plant: dict, lang: str):
    await bot.send_chat_action(chat_id=uid, action="typing")
    species_id = await perenual.search_species(plant["name"])
    p_data = await perenual.get_species_details(species_id) if species_id else {}
    care = await _ai.suggest_care(plant["name"], plant.get("plant_type"),
                                  plant.get("pot_width_cm"), plant.get("pot_depth_cm"), p_data)
    lines = [f"🌿 *{plant['name']} — Care guide*\n"]
    if care["fertilizer_type"]:
        lines.append(f"🌱 *Fertilizer:* {care['fertilizer_type']}")
    if care["fertilizer_frequency"]:
        lines.append(f"   {care['fertilizer_frequency']}")
    if care["trimming_notes"]:
        lines.append(f"\n✂️ *Trimming:* {care['trimming_notes']}")
    if care["pot_upgrade"]:
        rec = f" → {care['recommended_pot_cm']} cm wide" if care["recommended_pot_cm"] else ""
        lines.append(f"\n🪴 *Pot:* upgrade recommended{rec}")
    else:
        lines.append("\n🪴 *Pot:* current size looks fine")
    if care["notes"]:
        lines.append(f"\n💡 {care['notes']}")
    source = "Perenual + AI" if p_data else "AI estimate"
    lines.append(f"\n_Source: {source}_")
    await bot.send_message(uid, "\n".join(lines), parse_mode="Markdown")


def _lang(update: Update) -> str:
    return lang_for(update.effective_chat.id)


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
    chat_id = update.effective_chat.id
    await db.set_setting("owner_chat_id", str(chat_id))
    await update.message.reply_text(t("start_help", _lang(update)), parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(t("start_help", _lang(update)), parse_mode="Markdown")


async def startserver_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global _flask_process
    if _flask_process and _flask_process.poll() is None:
        await update.message.reply_text("⚠️ Server is already running. Use /stopserver to stop it.")
        return

    port = int(os.getenv("PORT_PLANTS", os.getenv("FLASK_PORT", 5060)))
    web_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web.py")
    _flask_process = subprocess.Popen([sys.executable, web_py],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    await asyncio.sleep(1.5)

    if _flask_process.poll() is not None:
        await update.message.reply_text("❌ Server failed to start. Check the logs on the machine.")
        _flask_process = None
        return

    local_ip = _get_local_ip()
    tailscale_ip = _get_tailscale_ip()
    lines = ["🌐 *Plant dashboard started!*\n", f"🏠 WiFi: `http://{local_ip}:{port}`"]
    if tailscale_ip:
        lines.append(f"🔒 Tailscale: `http://{tailscale_ip}:{port}`")
    lines.append("\n🛑 To stop: /stopserver")
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
    lang = _lang(update)
    uid = update.effective_chat.id
    plants = await db.get_all_plants(user_id=uid)
    if not plants:
        await update.message.reply_text(t("no_plants", lang))
        return

    lines = [t("list_header", lang)]
    for p in plants:
        last = await db.get_last_watered(p["id"])
        if last:
            from datetime import datetime
            days = (datetime.now() - datetime.fromisoformat(last[0])).days
            last_str = t("daily_today", lang) if days == 0 else f"{days}d"
        else:
            last_str = t("daily_never", lang)
        icon = "📷 " if p["telegram_file_id"] or p["image_data"] else ""
        lines.append(t("list_row", lang, icon=icon, name=p["name"],
                       ptype=p["plant_type"] or "?", last=last_str))

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def water_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _lang(update)
    uid = update.effective_chat.id
    if not context.args:
        await update.message.reply_text(t("water_usage", lang), parse_mode="Markdown")
        return

    args = list(context.args)
    amount_ml = None
    if args[-1].isdigit():
        amount_ml = int(args.pop())

    plant, extra, candidates = await _find_plant_in_args(args, uid)
    if candidates:
        context.user_data["_pick_args"] = [str(amount_ml)] if amount_ml else []
        await _show_plant_picker(update.message, context, candidates, "water", [], lang)
        return
    if not plant:
        await update.message.reply_text(t("plant_not_found", lang))
        return

    if amount_ml is None:
        amount_ml = plant["watering_amount_ml"]
    await db.log_watering(plant["id"], amount_ml)
    await update.message.reply_text(t("water_logged", lang, ml=amount_ml, name=plant["name"]),
                                    parse_mode="Markdown")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _lang(update)
    uid = update.effective_chat.id
    if not context.args:
        await update.message.reply_text(t("status_usage", lang), parse_mode="Markdown")
        return

    plant, _, candidates = await _find_plant_in_args(list(context.args), uid)
    if candidates:
        await _show_plant_picker(update.message, context, candidates, "status", [], lang)
        return
    if not plant:
        await update.message.reply_text(t("plant_not_found", lang))
        return
    await _send_status(context.bot, uid, dict(plant), lang)


async def photo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _lang(update)
    uid = update.effective_chat.id
    if not context.args:
        await update.message.reply_text(t("photo_usage", lang), parse_mode="Markdown")
        return

    plant, _, candidates = await _find_plant_in_args(list(context.args), uid)
    if candidates:
        await _show_plant_picker(update.message, context, candidates, "photo", [], lang)
        return
    if not plant:
        await update.message.reply_text(t("plant_not_found", lang))
        return

    caption = f"📷 *{plant['name']}*\n\n_Reply with a new photo to update it._"
    if plant["telegram_file_id"]:
        msg = await update.message.reply_photo(photo=plant["telegram_file_id"],
                                               caption=caption, parse_mode="Markdown")
    elif plant["image_data"]:
        msg = await update.message.reply_photo(photo=plant["image_data"],
                                               caption=caption, parse_mode="Markdown")
    else:
        msg = await update.message.reply_text(
            t("photo_none", lang, name=plant["name"]) + "\n\n_Reply to this message with a photo to add one._",
            parse_mode="Markdown",
        )
    await db.save_plant_message(plant["id"], uid, msg.message_id)


async def health_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _lang(update)
    uid = update.effective_chat.id
    if context.args:
        plant, _, candidates = await _find_plant_in_args(list(context.args), uid)
        if candidates:
            await _show_plant_picker(update.message, context, candidates, "health", [], lang)
            return
        if not plant:
            await update.message.reply_text(t("plant_not_found", lang))
            return
        await _run_health_check(uid, dict(plant), context, lang)
        return

    plants = await db.get_all_plants(user_id=uid)
    if not plants:
        await update.message.reply_text(t("no_plants", lang))
        return

    keyboard, row = [], []
    for p in plants:
        row.append(InlineKeyboardButton(p["name"], callback_data=f"health:{p['id']}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    await update.message.reply_text(t("health_pick", lang),
                                    reply_markup=InlineKeyboardMarkup(keyboard))


async def health_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = lang_for(update.effective_chat.id)
    plant_id = int(query.data.split(":")[1])
    plant = await db.get_plant(plant_id)
    if not plant:
        await query.edit_message_text("Plant not found.")
        return
    await query.edit_message_text(f"Analyzing *{plant['name']}*…", parse_mode="Markdown")
    await _run_health_check(update.effective_chat.id, dict(plant), context, lang)


async def _run_health_check(chat_id: int, plant: dict, context: ContextTypes.DEFAULT_TYPE, lang: str = "en"):
    history = await db.get_watering_history(plant["id"], limit=10)
    plant["history"] = [dict(h) for h in history]
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    response = await analyze_plant_health(plant, plant.get("image_data"))
    await context.bot.send_message(
        chat_id=chat_id,
        text=t("health_header", lang, name=plant["name"], response=response),
        parse_mode="Markdown",
    )


async def height_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _lang(update)
    uid = update.effective_chat.id
    if len(context.args) < 2 or not context.args[-1].replace(".", "", 1).isdigit():
        await update.message.reply_text(t("height_usage", lang), parse_mode="Markdown")
        return

    height_cm = float(context.args[-1])
    name_args = list(context.args[:-1])
    plant, _, candidates = await _find_plant_in_args(name_args, uid)
    if candidates:
        await _show_plant_picker(update.message, context, candidates, "height",
                                  [str(height_cm)], lang)
        return
    if not plant:
        await update.message.reply_text(t("plant_not_found", lang))
        return

    await db.log_height(plant["id"], height_cm)
    await update.message.reply_text(t("height_logged", lang, cm=height_cm, name=plant["name"]),
                                    parse_mode="Markdown")


_TREAT_INGREDIENTS = {"soap", "spinosad", "neem", "kaolin"}


async def pest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _lang(update)
    uid = update.effective_chat.id
    if len(context.args) < 2:
        await update.message.reply_text(t("pest_usage", lang), parse_mode="Markdown")
        return

    plant, extra, candidates = await _find_plant_in_args(list(context.args), uid)
    if candidates:
        await _show_plant_picker(update.message, context, candidates, "pest", extra, lang)
        return
    if not plant or not extra:
        await update.message.reply_text(t("plant_not_found", lang))
        return

    desc = " ".join(extra)
    await db.log_issue(plant["id"], "bug", desc)
    await update.message.reply_text(t("pest_logged", lang, name=plant["name"], desc=desc),
                                    parse_mode="Markdown")


async def disease_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _lang(update)
    uid = update.effective_chat.id
    if len(context.args) < 2:
        await update.message.reply_text(t("disease_usage", lang), parse_mode="Markdown")
        return

    plant, extra, candidates = await _find_plant_in_args(list(context.args), uid)
    if candidates:
        await _show_plant_picker(update.message, context, candidates, "disease", extra, lang)
        return
    if not plant or not extra:
        await update.message.reply_text(t("plant_not_found", lang))
        return

    desc = " ".join(extra)
    await db.log_issue(plant["id"], "fungal", desc)
    await update.message.reply_text(t("disease_logged", lang, name=plant["name"], desc=desc),
                                    parse_mode="Markdown")


async def treat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _lang(update)
    uid = update.effective_chat.id
    if not context.args:
        await update.message.reply_text(t("treat_usage", lang), parse_mode="Markdown")
        return

    plant, extra, candidates = await _find_plant_in_args(list(context.args), uid)
    if candidates:
        await _show_plant_picker(update.message, context, candidates, "treat", extra, lang)
        return
    if not plant:
        await update.message.reply_text(t("plant_not_found", lang))
        return

    ingredients = {k: False for k in _TREAT_INGREDIENTS}
    notes_parts = []
    for token in extra:
        if token.lower() in _TREAT_INGREDIENTS:
            ingredients[token.lower()] = True
        else:
            notes_parts.append(token)

    if not any(ingredients.values()):
        await update.message.reply_text(t("treat_nothing", lang), parse_mode="Markdown")
        return

    notes = " ".join(notes_parts) if notes_parts else None
    await db.log_treatment(plant["id"], notes=notes, **ingredients)

    used = [k for k, v in ingredients.items() if v]
    label = " + ".join(used)
    if notes:
        label += f" ({notes})"
    await update.message.reply_text(t("treat_logged", lang, name=plant["name"], ingredients=label),
                                    parse_mode="Markdown")


async def issues_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _lang(update)
    uid = update.effective_chat.id
    if not context.args:
        await update.message.reply_text(t("issues_usage", lang), parse_mode="Markdown")
        return

    plant, _, candidates = await _find_plant_in_args(list(context.args), uid)
    if candidates:
        await _show_plant_picker(update.message, context, candidates, "issues", [], lang)
        return
    if not plant:
        await update.message.reply_text(t("plant_not_found", lang))
        return
    await _send_issues(context.bot, uid, dict(plant), lang)


async def repot_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /repot <plant> [new_width] [new_depth] [soil]
    e.g. /repot Jasmine 25 20 potting mix
    Width and depth are optional — omit to keep current values.
    """
    lang = _lang(update)
    uid = update.effective_chat.id
    if not context.args:
        await update.message.reply_text(
            t("repot_usage", lang), parse_mode="Markdown"
        )
        return

    plant, rest, candidates = await _find_plant_in_args(list(context.args), uid)
    if candidates:
        await _show_plant_picker(update.message, context, candidates, "repot", rest, lang)
        return
    if not plant:
        await update.message.reply_text(t("plant_not_found", lang))
        return
    new_width = new_depth = new_soil = None
    try:
        if rest:
            new_width = float(rest[0])
        if len(rest) > 1:
            new_depth = float(rest[1])
        if len(rest) > 2:
            new_soil = " ".join(rest[2:])
    except ValueError:
        # Non-numeric token — treat everything after name as soil note
        new_soil = " ".join(rest)

    await db.log_repotting(
        plant["id"],
        old_width=plant["pot_width_cm"], old_depth=plant["pot_depth_cm"],
        old_soil=plant["soil_type"],
        new_width=new_width, new_depth=new_depth, new_soil=new_soil,
    )

    parts = [t("repot_logged", lang, name=plant["name"])]
    if new_width or new_depth:
        parts.append(f"🪴 New pot: {new_width or '?'} × {new_depth or '?'} cm")
    if new_soil:
        parts.append(f"🪨 Soil: {new_soil}")
    await update.message.reply_text("\n".join(parts), parse_mode="Markdown")


async def potgroup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /potgroup <group_name> <plant1>, <plant2>, ...
    e.g. /potgroup "window box" Basil, Jasmine
    Use /potgroup clear <plant> to remove a plant from its group.
    """
    lang = _lang(update)
    uid = update.effective_chat.id
    if not context.args:
        await update.message.reply_text(
            t("potgroup_usage", lang), parse_mode="Markdown"
        )
        return

    raw = " ".join(context.args)

    # "clear <plant>" removes from group
    if context.args[0].lower() == "clear":
        plant_name = " ".join(context.args[1:])
        plant = await db.get_plant_by_name(plant_name, user_id=uid)
        if not plant:
            await update.message.reply_text(t("plant_not_found", lang))
            return
        await db.set_pot_group(plant["id"], None)
        await update.message.reply_text(
            t("potgroup_cleared", lang, name=plant["name"]), parse_mode="Markdown"
        )
        return

    # Split "GroupName Plant1, Plant2" — group name is first token(s) before a comma-separated list
    # Try: first token = group name, rest = comma-separated plants
    parts = raw.split(None, 1)
    if len(parts) < 2:
        await update.message.reply_text(t("potgroup_usage", lang), parse_mode="Markdown")
        return
    group_name = parts[0]
    plant_names = [p.strip() for p in parts[1].split(",") if p.strip()]

    grouped = []
    not_found = []
    for pname in plant_names:
        plant = await db.get_plant_by_name(pname, user_id=uid)
        if plant:
            await db.set_pot_group(plant["id"], group_name)
            grouped.append(plant["name"])
        else:
            not_found.append(pname)

    msg_parts = []
    if grouped:
        msg_parts.append(t("potgroup_set", lang, group=group_name, names=", ".join(grouped)))
    if not_found:
        msg_parts.append(f"Not found: {', '.join(not_found)}")
    await update.message.reply_text("\n".join(msg_parts), parse_mode="Markdown")


async def care_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _lang(update)
    uid = update.effective_chat.id
    if not context.args:
        await update.message.reply_text(t("care_usage", lang), parse_mode="Markdown")
        return

    plant, _, candidates = await _find_plant_in_args(list(context.args), uid)
    if candidates:
        await _show_plant_picker(update.message, context, candidates, "care", [], lang)
        return
    if not plant:
        await update.message.reply_text(t("plant_not_found", lang))
        return

    await context.bot.send_chat_action(chat_id=uid, action="typing")

    species_id = await perenual.search_species(plant["name"])
    p_data = await perenual.get_species_details(species_id) if species_id else {}
    care = await _ai.suggest_care(
        plant["name"], plant["plant_type"],
        plant["pot_width_cm"], plant["pot_depth_cm"],
        p_data,
    )

    lines = [f"🌿 *{plant['name']} — Care guide*\n"]

    if care["fertilizer_type"]:
        lines.append(f"🌱 *Fertilizer:* {care['fertilizer_type']}")
    if care["fertilizer_frequency"]:
        lines.append(f"   {care['fertilizer_frequency']}")

    if care["trimming_notes"]:
        lines.append(f"\n✂️ *Trimming:* {care['trimming_notes']}")

    if care["pot_upgrade"]:
        rec = f" → {care['recommended_pot_cm']} cm wide" if care["recommended_pot_cm"] else ""
        lines.append(f"\n🪴 *Pot:* upgrade recommended{rec}")
    else:
        lines.append("\n🪴 *Pot:* current size looks fine")

    if care["notes"]:
        lines.append(f"\n💡 {care['notes']}")

    source = "Perenual + AI" if p_data else "AI estimate"
    lines.append(f"\n_Source: {source}_")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ── Report command ────────────────────────────────────────────────────────────

_REPORT_SECTIONS = {
    "health":      "🏥 Health",
    "fertilizer":  "🌱 Fertilizer",
    "repotting":   "🪴 Repotting",
    "pruning":     "✂️ Pruning",
    "insecticide": "🐛 Insecticide",
}


def _report_menu_kb(plant_id: int) -> InlineKeyboardMarkup:
    items = list(_REPORT_SECTIONS.items())
    rows = [
        [(label, f"report_sec:{plant_id}:{key}") for key, label in items[i:i+2]]
        for i in range(0, len(items), 2)
    ]
    rows.append([("🔄 Refresh", f"report_sec:{plant_id}:refresh")])
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(label, callback_data=data) for label, data in row]
        for row in rows
    ])


async def _do_generate_report(plant: dict) -> None:
    """Run Perenual + AI analysis and save to DB. Works for any plant."""
    from quickadd import _generate_and_save_report
    await _generate_and_save_report(
        plant["id"], plant["name"], plant["plant_type"],
        plant["pot_width_cm"], plant["pot_depth_cm"], plant["image_data"],
    )


async def _show_report_menu(chat_id: int, plant: dict, context, lang: str, edit_msg=None):
    report = await db.get_plant_report(plant["id"])
    if not report:
        notice = t("report_analyzing", lang, name=plant["name"])
        if edit_msg:
            await edit_msg.edit_text(notice, parse_mode="Markdown")
        else:
            await context.bot.send_message(chat_id=chat_id, text=notice, parse_mode="Markdown")
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        await _do_generate_report(plant)
        report = await db.get_plant_report(plant["id"])

    kb = _report_menu_kb(plant["id"])
    text = t("report_menu", lang, name=plant["name"])
    if edit_msg:
        await edit_msg.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    else:
        await context.bot.send_message(chat_id=chat_id, text=text,
                                        parse_mode="Markdown", reply_markup=kb)


async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _lang(update)
    uid = update.effective_chat.id
    if not context.args:
        plants = await db.get_all_plants(user_id=uid)
        if not plants:
            await update.message.reply_text(t("no_plants", lang))
            return
        keyboard, row = [], []
        for p in plants:
            row.append(InlineKeyboardButton(p["name"], callback_data=f"report:{p['id']}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        await update.message.reply_text(t("report_pick", lang),
                                        reply_markup=InlineKeyboardMarkup(keyboard))
        return

    plant, _, candidates = await _find_plant_in_args(list(context.args), uid)
    if candidates:
        await _show_plant_picker(update.message, context, candidates, "report", [], lang)
        return
    if not plant:
        await update.message.reply_text(t("plant_not_found", lang))
        return
    await _show_report_menu(uid, dict(plant), context, lang)


async def report_plant_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = _lang(update)
    plant_id = int(query.data.split(":")[1])
    plant = await db.get_plant_by_id(plant_id)
    if not plant:
        await query.edit_message_text(t("plant_not_found", lang))
        return
    await _show_report_menu(update.effective_chat.id, dict(plant), context, lang,
                            edit_msg=query.message)


async def report_section_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = _lang(update)
    _, plant_id_str, section = query.data.split(":", 2)
    plant_id = int(plant_id_str)

    plant = await db.get_plant_by_id(plant_id)
    if not plant:
        await query.edit_message_text(t("plant_not_found", lang))
        return

    if section == "refresh":
        await query.edit_message_text(t("report_refresh", lang, name=plant["name"]),
                                      parse_mode="Markdown")
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        await _do_generate_report(dict(plant))
        await _show_report_menu(update.effective_chat.id, dict(plant), context, lang,
                                edit_msg=query.message)
        return

    if section == "menu":
        await _show_report_menu(update.effective_chat.id, dict(plant), context, lang,
                                edit_msg=query.message)
        return

    report = await db.get_plant_report(plant_id)
    content = (dict(report).get(section) or t("report_no_data", lang)) if report else t("report_no_data", lang)
    section_label = _REPORT_SECTIONS.get(section, section.title())

    back_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("← Back", callback_data=f"report_sec:{plant_id}:menu")
    ]])
    await query.edit_message_text(
        f"📋 *{plant['name']} — {section_label}*\n\n{content}",
        parse_mode="Markdown",
        reply_markup=back_kb,
    )


# ── Watering button callbacks ────────────────────────────────────────────────

async def water_log_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = _lang(update)
    _, plant_id_str, ml_str = query.data.split(":")
    plant = await db.get_plant_by_id(int(plant_id_str))
    if not plant:
        await query.edit_message_text("Plant not found.")
        return
    amount_ml = int(ml_str)
    await db.log_watering(plant["id"], amount_ml)

    # Also log companions sharing the same pot
    companions = []
    if plant["pot_group"] and plant["user_id"]:
        pot_companions = await db.get_pot_companions(
            plant["id"], plant["pot_group"], plant["user_id"]
        )
        for c in pot_companions:
            await db.log_watering(c["id"], amount_ml)
            companions.append(c["name"])

    text = t("water_logged", lang, ml=amount_ml, name=plant["name"])
    if companions:
        text += f"\n_Also logged for pot companions: {', '.join(companions)}_"
    await query.edit_message_text(text, parse_mode="Markdown")


async def water_skip_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = _lang(update)
    plant = await db.get_plant_by_id(int(query.data.split(":")[1]))
    if not plant:
        await query.edit_message_text("Plant not found.")
        return
    await query.edit_message_text(
        t("water_skipped", lang, name=plant["name"]),
        parse_mode="Markdown",
    )


# ── Reply handlers ───────────────────────────────────────────────────────────

async def handle_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        return
    lang = _lang(update)
    chat_id = update.effective_chat.id
    plant = await db.get_plant_by_message(chat_id, update.message.reply_to_message.message_id)
    if not plant:
        return

    text = update.message.text.strip().lower()
    if text in ("skip", "s", "no", "later", "x", "omitir"):
        await update.message.reply_text(t("water_skipped", lang, name=plant["name"]),
                                        parse_mode="Markdown")
        return

    match = re.search(r"(\d+)", text)
    amount_ml = int(match.group(1)) if match else plant["watering_amount_ml"]
    await db.log_watering(plant["id"], amount_ml)
    await update.message.reply_text(t("water_logged", lang, ml=amount_ml, name=plant["name"]),
                                    parse_mode="Markdown")


async def handle_photo_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        return
    chat_id = update.effective_chat.id
    plant = await db.get_plant_by_message(chat_id, update.message.reply_to_message.message_id)
    if not plant:
        return

    photo = update.message.photo[-1]
    file_obj = await context.bot.get_file(photo.file_id)
    image_bytes = await file_obj.download_as_bytearray()
    await db.update_plant_image(plant["id"], bytes(image_bytes), photo.file_id)
    await update.message.reply_text(f"📷 *{plant['name']}* ✅", parse_mode="Markdown")


# ── Onboarding conversation ──────────────────────────────────────────────────

async def onboard_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["_lang"] = _lang(update)
    context.user_data["_uid"] = update.effective_chat.id
    await update.message.reply_text(t("ob_start", context.user_data["_lang"]), parse_mode="Markdown")
    return NAME


def _l(context) -> str:
    return context.user_data.get("_lang", "en")


async def onboard_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _l(context)
    name = update.message.text.strip()
    if await db.get_plant_by_name(name):
        await update.message.reply_text(t("ob_name_dup", lang, name=name), parse_mode="Markdown")
        return NAME
    context.user_data["name"] = name
    await update.message.reply_text(t("ob_type", lang, name=name), parse_mode="Markdown")
    return PLANT_TYPE


async def onboard_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["plant_type"] = update.message.text.strip()
    await update.message.reply_text(t("ob_location", _l(context)), parse_mode="Markdown")
    return LOCATION


async def onboard_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _l(context)
    text = update.message.text.strip().lower()
    canonical = LOCATION_ALIASES.get(text)
    if not canonical:
        await update.message.reply_text(t("ob_location_invalid", lang), parse_mode="Markdown")
        return LOCATION
    context.user_data["location"] = canonical

    if canonical == "ground":
        context.user_data["pot_depth_cm"] = None
        context.user_data["pot_width_cm"] = None
        await update.message.reply_text(t("ob_soil_alk", lang), parse_mode="Markdown")
        return SOIL_ALKALINITY

    await update.message.reply_text(t("ob_pot_depth", lang), parse_mode="Markdown")
    return POT_DEPTH


async def onboard_pot_depth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _l(context)
    text = update.message.text.strip().lower()
    if text in SKIP_WORDS:
        context.user_data["pot_depth_cm"] = None
    else:
        try:
            context.user_data["pot_depth_cm"] = float(text)
        except ValueError:
            await update.message.reply_text(t("ob_pot_depth_invalid", lang), parse_mode="Markdown")
            return POT_DEPTH
    await update.message.reply_text(t("ob_pot_width", lang), parse_mode="Markdown")
    return POT_WIDTH


async def onboard_pot_width(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _l(context)
    text = update.message.text.strip().lower()
    if text in SKIP_WORDS:
        context.user_data["pot_width_cm"] = None
    else:
        try:
            context.user_data["pot_width_cm"] = float(text)
        except ValueError:
            await update.message.reply_text(t("ob_pot_width_invalid", lang), parse_mode="Markdown")
            return POT_WIDTH
    await update.message.reply_text(t("ob_soil_alk", lang), parse_mode="Markdown")
    return SOIL_ALKALINITY


async def onboard_soil_alkalinity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data["soil_alkalinity"] = None if text.lower() in SKIP_WORDS else text
    await update.message.reply_text(t("ob_soil_type", _l(context)), parse_mode="Markdown")
    return SOIL_TYPE


async def onboard_soil_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data["soil_type"] = None if text.lower() in SKIP_WORDS else text
    await update.message.reply_text(t("ob_fert_type", _l(context)), parse_mode="Markdown")
    return FERTILIZER_TYPE


async def onboard_fertilizer_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _l(context)
    text = update.message.text.strip()
    if text.lower() in NONE_WORDS:
        context.user_data["fertilizer_type"] = None
        context.user_data["fertilizer_amount"] = None
        context.user_data["fertilizer_frequency_days"] = None
        await update.message.reply_text(t("ob_facing", lang), parse_mode="Markdown")
        return FACING
    context.user_data["fertilizer_type"] = text
    await update.message.reply_text(t("ob_fert_amount", lang), parse_mode="Markdown")
    return FERTILIZER_AMOUNT


async def onboard_fertilizer_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data["fertilizer_amount"] = None if text.lower() in NONE_WORDS else text
    await update.message.reply_text(t("ob_fert_freq", _l(context)), parse_mode="Markdown")
    return FERTILIZER_FREQUENCY


async def onboard_fertilizer_frequency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _l(context)
    text = update.message.text.strip().lower()
    if text in NONE_WORDS:
        context.user_data["fertilizer_frequency_days"] = None
    else:
        try:
            context.user_data["fertilizer_frequency_days"] = int(text)
        except ValueError:
            await update.message.reply_text(t("ob_fert_freq_invalid", lang), parse_mode="Markdown")
            return FERTILIZER_FREQUENCY
    await update.message.reply_text(t("ob_facing", lang), parse_mode="Markdown")
    return FACING


async def onboard_facing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _l(context)
    text = update.message.text.strip().lower()
    if text in SKIP_WORDS:
        context.user_data["facing"] = None
    elif text in _FACING_NORMALIZE:
        context.user_data["facing"] = _FACING_NORMALIZE[text]
    else:
        await update.message.reply_text(t("ob_facing_invalid", lang), parse_mode="Markdown")
        return FACING
    await update.message.reply_text(t("ob_height", lang), parse_mode="Markdown")
    return HEIGHT


async def onboard_height(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _l(context)
    text = update.message.text.strip().lower()
    if text in SKIP_WORDS:
        context.user_data["height_cm"] = None
    else:
        try:
            context.user_data["height_cm"] = float(text)
        except ValueError:
            await update.message.reply_text(t("ob_height_invalid", lang), parse_mode="Markdown")
            return HEIGHT
    await update.message.reply_text(t("ob_sun_actual", lang), parse_mode="Markdown")
    return SUNLIGHT_ACTUAL


async def onboard_sunlight_actual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _l(context)
    text = update.message.text.strip().lower()
    if text in SKIP_WORDS:
        context.user_data["sunlight_hours_actual"] = None
    else:
        try:
            context.user_data["sunlight_hours_actual"] = float(text)
        except ValueError:
            await update.message.reply_text(t("ob_sun_actual_invalid", lang), parse_mode="Markdown")
            return SUNLIGHT_ACTUAL
    await update.message.reply_text(t("ob_sun_needed", lang), parse_mode="Markdown")
    return SUNLIGHT_NEEDED


async def onboard_sunlight_needed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from ai import suggest_sunlight_needs
    lang = _l(context)
    text = update.message.text.strip().lower()

    if text in UNSURE:
        await update.message.reply_text(t("ob_sun_looking_up", lang))
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
                    gap = t("ob_sun_gap_more", lang, actual=actual, diff=diff)
                elif diff < -0.5:
                    gap = t("ob_sun_gap_ok", lang, actual=actual)
            await update.message.reply_text(
                t("ob_sun_result", lang, plant_type=context.user_data["plant_type"],
                  hours=rec["hours_needed"], note=note, gap=gap),
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error(f"Sunlight lookup failed: {e}")
            context.user_data["sunlight_hours_needed"] = None
            await update.message.reply_text(t("ob_sun_failed", lang), parse_mode="Markdown")
        return FREQUENCY

    try:
        context.user_data["sunlight_hours_needed"] = float(text)
    except ValueError:
        await update.message.reply_text(t("ob_sun_invalid", lang), parse_mode="Markdown")
        return SUNLIGHT_NEEDED
    await update.message.reply_text(t("ob_freq", lang), parse_mode="Markdown")
    return FREQUENCY


async def onboard_frequency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from ai import suggest_watering_schedule
    lang = _l(context)
    text = update.message.text.strip().lower()

    if text in UNSURE:
        await update.message.reply_text(t("ob_freq_looking_up", lang))
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
                t("ob_freq_result", lang, plant_type=context.user_data["plant_type"],
                  freq=rec["frequency_days"], ml=rec["amount_ml"], note=note),
                parse_mode="Markdown",
            )
            return PHOTO
        except Exception as e:
            logger.error(f"Schedule lookup failed: {e}")
            await update.message.reply_text(t("ob_freq_failed", lang), parse_mode="Markdown")
            return FREQUENCY

    try:
        context.user_data["watering_frequency_days"] = int(text)
    except ValueError:
        await update.message.reply_text(t("ob_freq_invalid", lang), parse_mode="Markdown")
        return FREQUENCY
    await update.message.reply_text(t("ob_amount", lang), parse_mode="Markdown")
    return AMOUNT


async def onboard_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from ai import suggest_watering_schedule
    lang = _l(context)
    text = update.message.text.strip().lower()

    if text in UNSURE:
        await update.message.reply_text(t("ob_amount_looking_up", lang))
        try:
            rec = await suggest_watering_schedule(
                context.user_data["name"],
                context.user_data["plant_type"],
                context.user_data.get("pot_depth_cm"),
            )
            context.user_data["watering_amount_ml"] = rec["amount_ml"]
            await update.message.reply_text(
                t("ob_amount_result", lang, ml=rec["amount_ml"],
                  plant_type=context.user_data["plant_type"]),
                parse_mode="Markdown",
            )
            return PHOTO
        except Exception as e:
            logger.error(f"Amount lookup failed: {e}")
            await update.message.reply_text(t("ob_amount_failed", lang), parse_mode="Markdown")
            return AMOUNT

    try:
        context.user_data["watering_amount_ml"] = int(text)
    except ValueError:
        await update.message.reply_text(t("ob_amount_invalid", lang), parse_mode="Markdown")
        return AMOUNT
    await update.message.reply_text(t("ob_photo", lang), parse_mode="Markdown")
    return PHOTO


async def onboard_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _l(context)
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
        user_id=data.get("_uid"),
    )

    if image_data:
        await db.update_plant_image(plant_id, image_data, file_id)

    if data.get("location") == "pot":
        depth = f"{data.get('pot_depth_cm')} cm" if data.get("pot_depth_cm") else "?"
        width = f"{data.get('pot_width_cm')} cm" if data.get("pot_width_cm") else "?"
        volume = db.estimate_soil_volume_l(data.get("pot_depth_cm"), data.get("pot_width_cm"))
        vol_str = f" (~{volume} L)" if volume else ""
        location_line = t("location_pot", lang, depth=depth, width=width, vol=vol_str)
    else:
        location_line = t("location_ground", lang)

    if data.get("fertilizer_type"):
        fert = data["fertilizer_type"]
        if data.get("fertilizer_amount"):
            fert += f", {data['fertilizer_amount']}"
        if data.get("fertilizer_frequency_days"):
            fert += f", every {data['fertilizer_frequency_days']} days"
    else:
        fert = t("status_no_fert", lang)

    height_str = f"{data.get('height_cm')} cm" if data.get("height_cm") else "?"

    await update.message.reply_text(
        t("ob_done", lang,
          name=data["name"],
          plant_type=data["plant_type"],
          location_line=location_line,
          soil_alk=data.get("soil_alkalinity") or "?",
          soil_type=data.get("soil_type") or "?",
          fert=fert,
          facing=data.get("facing") or "?",
          height=height_str,
          freq=data["watering_frequency_days"],
          ml=data["watering_amount_ml"]),
        parse_mode="Markdown",
    )
    context.user_data.clear()
    return ConversationHandler.END


async def onboard_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _l(context)
    context.user_data.clear()
    await update.message.reply_text(t("ob_cancel", lang))
    return ConversationHandler.END
