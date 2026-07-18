"""
Expedited plant onboarding via photo + AI identification.
Usage: /quickadd → send photo → tap through AI suggestions → plant saved.
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler,
    CommandHandler, MessageHandler, CallbackQueryHandler, filters,
)
import db
from ai import analyze_plant_image

logger = logging.getLogger(__name__)

# ── States (200-range to avoid collision with main onboarding) ────────────────
(
    QA_PHOTO,
    QA_NAME, QA_NAME_CUSTOM,
    QA_LOCATION,
    QA_SOIL, QA_SOIL_CUSTOM,
    QA_FACING,
    QA_HEIGHT, QA_HEIGHT_CUSTOM,
    QA_WATERING, QA_WATERING_CUSTOM,
) = range(200, 211)

_SOIL_OPTIONS = ["Potting mix", "Cactus mix", "Garden soil"]
_FACINGS = [
    ("N", "north"), ("NE", "northeast"), ("E", "east"), ("SE", "southeast"),
    ("S", "south"), ("SW", "southwest"), ("W", "west"), ("NW", "northwest"),
]


def _kb(*rows: list) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(label, callback_data=data) for label, data in row]
        for row in rows
    ])


def _qa(context) -> dict:
    return context.user_data.setdefault("qa", {})


# ── Entry ─────────────────────────────────────────────────────────────────────

async def quickadd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["qa"] = {"_uid": update.effective_chat.id}
    await update.message.reply_text(
        "📸 *Quick Add Plant*\n\nSend me a photo of your plant and I'll identify it.",
        parse_mode="Markdown",
    )
    return QA_PHOTO


# ── Photo → AI analysis → name choice ─────────────────────────────────────────

async def quickadd_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text("Please send a photo of your plant.")
        return QA_PHOTO

    thinking = await update.message.reply_text("🔍 Identifying your plant…")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    photo = update.message.photo[-1]
    file_obj = await context.bot.get_file(photo.file_id)
    image_data = bytes(await file_obj.download_as_bytearray())

    qa = _qa(context)
    qa["image_data"] = image_data
    qa["file_id"] = photo.file_id

    ai = await analyze_plant_image(image_data)
    qa["ai"] = ai

    await thinking.delete()

    names = ai.get("name_suggestions") or []
    if names:
        rows = [[( name, f"qa_name:{i}")] for i, name in enumerate(names)]
    else:
        rows = []
    rows.append([("❌ None of the above", "qa_name:custom")])

    plant_type = ai.get("plant_type", "")
    header = f"🌿 Looks like a *{plant_type}*. Which name fits best?" if plant_type else "🌿 What's this plant called?"
    await update.message.reply_text(header, parse_mode="Markdown", reply_markup=_kb(*rows))
    return QA_NAME


# ── Name ─────────────────────────────────────────────────────────────────────

async def quickadd_name_pick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    qa = _qa(context)
    val = query.data.split(":", 1)[1]

    if val == "custom":
        await query.edit_message_text("What's the plant's name? Type it:")
        return QA_NAME_CUSTOM

    idx = int(val)
    names = qa["ai"].get("name_suggestions", [])
    qa["name"] = names[idx] if idx < len(names) else "Unknown"
    await query.edit_message_text(f"✅ *{qa['name']}*", parse_mode="Markdown")
    return await _ask_location(query.message, context)


async def quickadd_name_custom(update: Update, context: ContextTypes.DEFAULT_TYPE):
    qa = _qa(context)
    qa["name"] = update.message.text.strip()
    return await _ask_location(update.message, context)


# ── Location ──────────────────────────────────────────────────────────────────

async def _ask_location(message, context):
    ai_loc = _qa(context)["ai"].get("location")
    rows = [
        [("🪴 Pot", "qa_loc:pot"), ("🌱 Ground", "qa_loc:ground")],
    ]
    if ai_loc:
        rows.insert(0, [(f"🤖 AI: {ai_loc}", "qa_loc:ai")])
    rows.append([("⏭ Skip", "qa_loc:skip")])
    await message.reply_text("📍 Where is it planted?", reply_markup=_kb(*rows))
    return QA_LOCATION


async def quickadd_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    qa = _qa(context)
    val = query.data.split(":", 1)[1]

    if val == "ai":
        qa["location"] = qa["ai"].get("location")
    elif val == "skip":
        qa["location"] = None
    else:
        qa["location"] = val

    label = qa.get("location") or "skipped"
    await query.edit_message_text(f"📍 Location: *{label}*", parse_mode="Markdown")
    return await _ask_soil(query.message, context)


# ── Soil ──────────────────────────────────────────────────────────────────────

async def _ask_soil(message, context):
    ai_soil = _qa(context)["ai"].get("soil_type")
    rows = []
    if ai_soil:
        rows.append([(f"🤖 AI: {ai_soil}", "qa_soil:ai")])
    for opt in _SOIL_OPTIONS:
        rows.append([(opt, f"qa_soil:opt:{opt.lower()}")])
    rows.append([("✏️ Other", "qa_soil:other"), ("⏭ Skip", "qa_soil:skip")])
    await message.reply_text("🪨 What type of soil?", reply_markup=_kb(*rows))
    return QA_SOIL


async def quickadd_soil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    qa = _qa(context)
    val = query.data.split(":", 1)[1]

    if val == "other":
        await query.edit_message_text("Type the soil type:")
        return QA_SOIL_CUSTOM
    elif val == "ai":
        qa["soil_type"] = qa["ai"].get("soil_type")
    elif val == "skip":
        qa["soil_type"] = None
    elif val.startswith("opt:"):
        qa["soil_type"] = val[4:]

    label = qa.get("soil_type") or "skipped"
    await query.edit_message_text(f"🪨 Soil: *{label}*", parse_mode="Markdown")
    return await _ask_facing(query.message, context)


async def quickadd_soil_custom(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _qa(context)["soil_type"] = update.message.text.strip()
    return await _ask_facing(update.message, context)


# ── Facing ────────────────────────────────────────────────────────────────────

async def _ask_facing(message, context):
    ai_facing = _qa(context)["ai"].get("facing")
    rows = [
        [(label, f"qa_facing:{val}") for label, val in _FACINGS[:4]],
        [(label, f"qa_facing:{val}") for label, val in _FACINGS[4:]],
    ]
    if ai_facing:
        rows.append([(f"🤖 AI: {ai_facing}", "qa_facing:ai")])
    rows.append([("⏭ Skip", "qa_facing:skip")])
    await message.reply_text("🧭 Which direction does it face?", reply_markup=_kb(*rows))
    return QA_FACING


async def quickadd_facing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    qa = _qa(context)
    val = query.data.split(":", 1)[1]

    if val == "ai":
        qa["facing"] = qa["ai"].get("facing")
    elif val == "skip":
        qa["facing"] = None
    else:
        qa["facing"] = val

    label = qa.get("facing") or "skipped"
    await query.edit_message_text(f"🧭 Facing: *{label}*", parse_mode="Markdown")
    return await _ask_height(query.message, context)


# ── Height ────────────────────────────────────────────────────────────────────

async def _ask_height(message, context):
    ai_h = _qa(context)["ai"].get("height_cm")
    rows = []
    if ai_h:
        rows.append([(f"🤖 AI: ~{ai_h} cm", "qa_height:ai")])
    rows.append([("✏️ Enter value", "qa_height:custom"), ("⏭ Skip", "qa_height:skip")])
    await message.reply_text("📏 How tall is it?", reply_markup=_kb(*rows))
    return QA_HEIGHT


async def quickadd_height(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    qa = _qa(context)
    val = query.data.split(":", 1)[1]

    if val == "custom":
        await query.edit_message_text("Enter height in cm (e.g. `40`):", parse_mode="Markdown")
        return QA_HEIGHT_CUSTOM
    elif val == "ai":
        qa["height_cm"] = qa["ai"].get("height_cm")
    else:
        qa["height_cm"] = None

    h = qa.get("height_cm")
    label = f"{h} cm" if h else "skipped"
    await query.edit_message_text(f"📏 Height: *{label}*", parse_mode="Markdown")
    return await _ask_watering(query.message, context)


async def quickadd_height_custom(update: Update, context: ContextTypes.DEFAULT_TYPE):
    qa = _qa(context)
    text = update.message.text.strip().replace("cm", "").strip()
    try:
        qa["height_cm"] = float(text)
    except ValueError:
        await update.message.reply_text("Enter a number in cm (e.g. `40`):", parse_mode="Markdown")
        return QA_HEIGHT_CUSTOM
    return await _ask_watering(update.message, context)


# ── Watering ──────────────────────────────────────────────────────────────────

async def _ask_watering(message, context):
    ai = _qa(context)["ai"]
    freq = ai.get("watering_frequency_days", 7)
    ml = ai.get("watering_amount_ml", 200)
    rows = [
        [(f"🤖 AI: every {freq}d, {ml} ml", "qa_water:ai")],
        [("✏️ Custom", "qa_water:custom"), ("⏭ Defaults (7d / 200 ml)", "qa_water:skip")],
    ]
    await message.reply_text("💧 Watering schedule?", reply_markup=_kb(*rows))
    return QA_WATERING


async def quickadd_watering(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    qa = _qa(context)
    ai = qa["ai"]
    val = query.data.split(":", 1)[1]

    if val == "custom":
        await query.edit_message_text(
            "Enter as `<days> <ml>` (e.g. `7 250`):", parse_mode="Markdown"
        )
        return QA_WATERING_CUSTOM
    elif val == "ai":
        qa["watering_frequency_days"] = ai.get("watering_frequency_days", 7)
        qa["watering_amount_ml"] = ai.get("watering_amount_ml", 200)
    else:
        qa["watering_frequency_days"] = 7
        qa["watering_amount_ml"] = 200

    await query.edit_message_text(
        f"💧 Watering: every *{qa['watering_frequency_days']}d*, *{qa['watering_amount_ml']} ml*",
        parse_mode="Markdown",
    )
    return await _save_plant(query.message, context)


async def quickadd_watering_custom(update: Update, context: ContextTypes.DEFAULT_TYPE):
    qa = _qa(context)
    parts = update.message.text.strip().split()
    try:
        qa["watering_frequency_days"] = int(parts[0])
        qa["watering_amount_ml"] = int(parts[1]) if len(parts) > 1 else 200
    except (ValueError, IndexError):
        await update.message.reply_text(
            "Enter as `<days> <ml>` (e.g. `7 250`):", parse_mode="Markdown"
        )
        return QA_WATERING_CUSTOM
    return await _save_plant(update.message, context)


# ── Save ──────────────────────────────────────────────────────────────────────

async def _save_plant(message, context) -> int:
    qa = context.user_data.get("qa", {})
    ai = qa.get("ai", {})

    location = qa.get("location")
    pot_depth = ai.get("pot_depth_cm")
    pot_width = ai.get("pot_width_cm")

    plant_id = await db.add_plant(
        name=qa.get("name", "Unknown plant"),
        plant_type=ai.get("plant_type"),
        pot_depth_cm=pot_depth,
        pot_width_cm=pot_width,
        location=location,
        soil_alkalinity=None,
        soil_type=qa.get("soil_type"),
        fertilizer_type=None,
        fertilizer_amount=None,
        fertilizer_frequency_days=None,
        facing=qa.get("facing"),
        height_cm=qa.get("height_cm"),
        sunlight_hours_actual=None,
        sunlight_hours_needed=ai.get("sunlight_hours_needed"),
        watering_frequency_days=qa.get("watering_frequency_days", 7),
        watering_amount_ml=qa.get("watering_amount_ml", 200),
        user_id=qa.get("_uid"),
    )

    image_data = qa.get("image_data")
    file_id = qa.get("file_id")
    if image_data and file_id:
        await db.update_plant_image(plant_id, image_data, file_id)

    name = qa.get("name", "Plant")
    h = qa.get("height_cm")
    height_str = f"{h} cm" if h else "?"
    notes = ai.get("notes", "")
    context.user_data.clear()

    summary = (
        f"✅ *{name}* added!\n\n"
        f"Type: {ai.get('plant_type') or '?'}\n"
        f"Location: {location or '?'}\n"
        f"Soil: {qa.get('soil_type') or '?'}\n"
        f"Facing: {qa.get('facing') or '?'}\n"
        f"Height: {height_str}\n"
        f"Waters every {qa.get('watering_frequency_days', 7)} days, "
        f"{qa.get('watering_amount_ml', 200)} ml"
    )
    if notes:
        summary += f"\n\n💡 _{notes}_"
    summary += "\n\nEdit more details on the web dashboard anytime."

    await message.reply_text(summary, parse_mode="Markdown")
    return ConversationHandler.END


# ── Cancel ────────────────────────────────────────────────────────────────────

async def quickadd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Quick add cancelled.")
    return ConversationHandler.END


# ── ConversationHandler factory ───────────────────────────────────────────────

def build_quickadd_handler() -> ConversationHandler:
    cq = CallbackQueryHandler
    txt = MessageHandler(filters.TEXT & ~filters.COMMAND)
    return ConversationHandler(
        entry_points=[CommandHandler("quickadd", quickadd_start)],
        states={
            QA_PHOTO:           [MessageHandler(filters.PHOTO, quickadd_photo)],
            QA_NAME:            [cq(quickadd_name_pick,      pattern=r"^qa_name:")],
            QA_NAME_CUSTOM:     [txt(quickadd_name_custom)],
            QA_LOCATION:        [cq(quickadd_location,       pattern=r"^qa_loc:")],
            QA_SOIL:            [cq(quickadd_soil,           pattern=r"^qa_soil:")],
            QA_SOIL_CUSTOM:     [txt(quickadd_soil_custom)],
            QA_FACING:          [cq(quickadd_facing,         pattern=r"^qa_facing:")],
            QA_HEIGHT:          [cq(quickadd_height,         pattern=r"^qa_height:")],
            QA_HEIGHT_CUSTOM:   [txt(quickadd_height_custom)],
            QA_WATERING:        [cq(quickadd_watering,       pattern=r"^qa_water:")],
            QA_WATERING_CUSTOM: [txt(quickadd_watering_custom)],
        },
        fallbacks=[CommandHandler("cancel", quickadd_cancel)],
        per_message=False,
    )
