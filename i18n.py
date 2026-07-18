import os

# ── English strings ───────────────────────────────────────────────────────────
_EN = {
    "start_help": (
        "🌱 *Plant Tracker*\n\n"
        "/add — Onboard a new plant (step-by-step)\n"
        "/quickadd — Add a plant from a photo (AI-assisted)\n"
        "/list — All plants & last watered\n"
        "/water `<plant>` `[ml]` — Log a watering\n"
        "/status `<plant>` — Watering history\n"
        "/photo `<plant>` — Get plant photo\n"
        "/health `<plant>` — AI health check\n"
        "/height `<plant>` `<cm>` — Log a new height reading\n"
        "/pest `<plant>` `<description>` — Log a bug infestation\n"
        "/disease `<plant>` `<description>` — Log rust/mold/fungal issue\n"
        "/treat `<plant>` `[soap]` `[neem]` `[spinosad]` `[kaolin]` — Log a treatment\n"
        "/issues `<plant>` — Show open pest/disease issues\n"
        "/startserver — Start the plant dashboard\n"
        "/stopserver — Stop the dashboard\n\n"
        "Reply to any daily recommendation to log watering or update a photo."
    ),
    # onboarding
    "ob_start":             "🌱 *Add a new plant*\n\nWhat's the plant's name?",
    "ob_name_dup":          "A plant named *{name}* already exists. Try a different name.",
    "ob_type":              "What *type* of plant is *{name}*?\n(e.g. succulent, fern, tomato, cactus)",
    "ob_location":          "Is it planted in a *pot* or in the *ground*?",
    "ob_location_invalid":  "Please answer `pot` or `ground`.",
    "ob_pot_depth":         "How deep is the pot? (cm, e.g. `15`) — or `?` to skip",
    "ob_pot_depth_invalid": "Enter a number in cm (e.g. `20`) or `?` to skip.",
    "ob_pot_width":         "How *wide* is the pot? (cm, e.g. `25`) — or `?` to skip",
    "ob_pot_width_invalid": "Enter a number in cm (e.g. `25`) or `?` to skip.",
    "ob_soil_alk":          "What's the soil alkalinity? (e.g. `acidic`, `neutral`, `alkaline`, pH like `6.5`) — or `?` to skip",
    "ob_soil_type":         "What soil type? (e.g. `potting mix`, `clay`, `sandy`, `loam`) — or `?` to skip",
    "ob_fert_type":         "What *type* of fertilizer do you use, if any? (e.g. `fish emulsion`, `10-10-10`) — or `none`/`?` to skip",
    "ob_fert_amount":       "How much fertilizer per application? (e.g. `1 tbsp`, `10 ml`) — or `?` to skip",
    "ob_fert_freq":         "How often do you fertilize? (days, e.g. `30`) — or `?` to skip",
    "ob_fert_freq_invalid": "Enter a whole number of days (e.g. `30`) or `?` to skip.",
    "ob_facing":            "Which way does it face? (`north`, `south`, `east`, `west`, `southwest`, etc. or `no shade`) — or `?` to skip",
    "ob_facing_invalid":    "Please answer a compass direction (e.g. `north`, `southwest`, `nw`) or `?` to skip.",
    "ob_height":            "How tall is the plant today? (cm, e.g. `30`) — or `?` to skip",
    "ob_height_invalid":    "Enter a number in cm (e.g. `30`) or `?` to skip.",
    "ob_sun_actual":        "How many hours of *direct sunlight* does it get per day? (e.g. `4`) — or `?` to skip",
    "ob_sun_actual_invalid":"Enter a number (e.g. `4`) or `?` to skip.",
    "ob_sun_needed":        "How many hours of sunlight does it *need*? (e.g. `6`) — or `?` for a suggestion",
    "ob_sun_looking_up":    "🔍 Looking up sunlight requirements…",
    "ob_sun_result":        "☀️ *{plant_type}* needs ~*{hours}h* of direct sun.{note}{gap}\n\nHow often does it need watering? (days, e.g. `7`) — or `?` for a suggestion",
    "ob_sun_gap_more":      "\n⚠️ Currently getting {actual}h — needs {diff:.1f}h more.",
    "ob_sun_gap_ok":        "\n✅ Getting {actual}h — more than enough.",
    "ob_sun_failed":        "Couldn't reach the AI. How often does it need watering? (days, e.g. `7`)",
    "ob_sun_invalid":       "Enter a number (e.g. `6`) or `?` for a suggestion.",
    "ob_freq":              "How often does it need watering? (days, e.g. `7`) — or `?` for a suggestion",
    "ob_freq_looking_up":   "🔍 Looking up care requirements for your plant…",
    "ob_freq_result":       "✅ Recommendation for *{plant_type}*:\n• Every *{freq} days*\n• *{ml} ml* per session{note}\n\nBoth saved! Last step: send a *photo* or type `skip`.",
    "ob_freq_failed":       "Couldn't reach the AI right now. Enter frequency in days (e.g. `7`):",
    "ob_freq_invalid":      "Enter a whole number of days (e.g. `7`), or `?` for a recommendation.",
    "ob_amount":            "How much water per session? (ml, e.g. `200`) — or `?` for a suggestion",
    "ob_amount_looking_up": "🔍 Looking up a recommendation…",
    "ob_amount_result":     "✅ Suggested *{ml} ml* per session for a {plant_type}. Saved!\n\nLast step: send a *photo* or type `skip`.",
    "ob_amount_failed":     "Couldn't reach the AI right now. Enter the amount in ml (e.g. `200`):",
    "ob_amount_invalid":    "Enter a whole number in ml (e.g. `200`) or `?` for a suggestion.",
    "ob_photo":             "Last step: send a *photo* of the plant, or type `skip` to add it later.",
    "ob_done": (
        "✅ *{name}* added!\n\n"
        "Type: {plant_type}\n"
        "{location_line}\n"
        "Soil: {soil_alk}, {soil_type}\n"
        "Fertilizer: {fert}\n"
        "Facing: {facing}\n"
        "Height: {height}\n"
        "Waters every {freq} days, {ml} ml\n\n"
        "Use /list to see all your plants. Use /height to update height anytime."
    ),
    "ob_cancel": "Cancelled. Use /add to start over.",
    "location_pot":    "Pot: {depth} deep × {width} wide{vol}",
    "location_ground": "Planted in the ground",
    # commands
    "no_plants":       "No plants yet — use /add to get started.",
    "list_header":     "🌿 *Your Plants*\n",
    "list_row":        "{icon}• *{name}* ({ptype}) — last watered: {last}",
    "plant_not_found": "Plant not found. Use /list to see all plants.",
    "water_usage":     "Usage: `/water <plant name> [ml]`",
    "water_logged":    "✅ Logged *{ml} ml* for *{name}*",
    "water_skipped":   "Skipped — *{name}* not watered today.",
    "status_usage":    "Usage: `/status <plant name>`",
    "status_fert":     "{type}, {amount}, every {freq} days",
    "status_no_fert":  "none",
    "status_no_hist":  "No history yet.",
    "photo_usage":     "Usage: `/photo <plant name>`",
    "photo_none":      "No photo stored for *{name}*. Send a photo as a reply to any recommendation.",
    "health_pick":     "Which plant would you like to analyze?",
    "health_header":   "🔬 *Health check — {name}*\n\n{response}",
    "height_usage":    "Usage: `/height <plant name> <cm>`\ne.g. `/height Monstera 45`",
    "height_logged":   "📏 Logged *{cm} cm* for *{name}*",
    # scheduler
    "daily_all_good":   "{weather}✅ All plants are on schedule today — no watering needed!",
    "daily_rec":        "{weather}🌿 *{name}*\n⏱️ {last}\n💧 Recommended: *{ml} ml*\n\nReply with the amount you gave (e.g. `{ml}`) or `skip`.",
    "daily_never":      "never watered",
    "daily_today":      "watered today",
    "daily_yesterday":  "watered yesterday",
    "daily_days_ago":   "last watered {days} days ago",
    "height_reminder":  "📏 *Time for a height check-in!*\n\nReply with `/height <plant> <cm>` for each:",
    # pest / disease / treatment
    "pest_usage":       "Usage: `/pest <plant name> <description>`\ne.g. `/pest Jasmine aphids on leaves`",
    "pest_logged":      "🐛 Logged bug issue on *{name}*: {desc}",
    "disease_usage":    "Usage: `/disease <plant name> <description>`\ne.g. `/disease Jasmine rust on lower leaves`",
    "disease_logged":   "🍂 Logged disease on *{name}*: {desc}",
    "treat_usage":      "Usage: `/treat <plant name> [soap] [neem] [spinosad] [kaolin] [notes]`\ne.g. `/treat Jasmine neem soap`",
    "treat_logged":     "💊 Logged treatment for *{name}*: {ingredients}",
    "treat_nothing":    "Specify at least one ingredient: `soap`, `neem`, `spinosad`, `kaolin`",
    "issues_usage":     "Usage: `/issues <plant name>`",
    "issues_none":      "No open issues for *{name}* — looking healthy! 🌿",
    "issues_header":    "⚠️ *Open issues for {name}*\n",
    "issue_row":        "• [{cat}] {desc} (since {date})",
}

# ── Spanish strings ───────────────────────────────────────────────────────────
_ES = {
    "start_help": (
        "🌱 *Rastreador de Plantas*\n\n"
        "/add — Registrar una planta nueva (paso a paso)\n"
        "/quickadd — Agregar planta desde foto (asistido por IA)\n"
        "/list — Ver todas tus plantas\n"
        "/water `<planta>` `[ml]` — Registrar riego\n"
        "/status `<planta>` — Historial de riego\n"
        "/photo `<planta>` — Ver foto de la planta\n"
        "/health `<planta>` — Revisión de salud con IA\n"
        "/height `<planta>` `<cm>` — Registrar altura\n"
        "/pest `<planta>` `<descripción>` — Registrar plaga de insectos\n"
        "/disease `<planta>` `<descripción>` — Registrar roya/moho/hongo\n"
        "/treat `<planta>` `[soap]` `[neem]` `[spinosad]` `[kaolin]` — Registrar tratamiento\n"
        "/issues `<planta>` — Ver problemas abiertos\n"
        "/startserver — Abrir panel web\n"
        "/stopserver — Cerrar panel web\n\n"
        "Responde a cualquier recomendación diaria para registrar el riego o actualizar la foto."
    ),
    "ob_start":             "🌱 *Agregar una planta nueva*\n\n¿Cómo se llama la planta?",
    "ob_name_dup":          "Ya existe una planta llamada *{name}*. Prueba con otro nombre.",
    "ob_type":              "¿Qué *tipo* de planta es *{name}*?\n(ej. suculenta, helecho, tomate, cactus)",
    "ob_location":          "¿Está en una *maceta* o en el *suelo*?",
    "ob_location_invalid":  "Por favor responde `maceta` o `suelo`.",
    "ob_pot_depth":         "¿Qué tan profunda es la maceta? (cm, ej. `15`) — o `?` para omitir",
    "ob_pot_depth_invalid": "Ingresa un número en cm (ej. `20`) o `?` para omitir.",
    "ob_pot_width":         "¿Qué tan *ancha* es la maceta? (cm, ej. `25`) — o `?` para omitir",
    "ob_pot_width_invalid": "Ingresa un número en cm (ej. `25`) o `?` para omitir.",
    "ob_soil_alk":          "¿Cuál es la alcalinidad del suelo? (ej. `ácido`, `neutro`, `alcalino`, pH `6.5`) — o `?` para omitir",
    "ob_soil_type":         "¿Qué tipo de suelo? (ej. `tierra para macetas`, `arcilla`, `arenoso`, `marga`) — o `?` para omitir",
    "ob_fert_type":         "¿Qué *tipo* de fertilizante usas? (ej. `emulsión de pescado`, `10-10-10`) — o `ninguno`/`?` para omitir",
    "ob_fert_amount":       "¿Cuánto fertilizante por aplicación? (ej. `1 cda`, `10 ml`) — o `?` para omitir",
    "ob_fert_freq":         "¿Cada cuántos días fertilizas? (ej. `30`) — o `?` para omitir",
    "ob_fert_freq_invalid": "Ingresa un número entero de días (ej. `30`) o `?` para omitir.",
    "ob_facing":            "¿Hacia dónde da? (`norte`, `sur`, `este`, `oeste`, `suroeste`, etc. o `sin sombra`) — o `?` para omitir",
    "ob_facing_invalid":    "Indica una dirección (ej. `norte`, `suroeste`, `NO`) o `?` para omitir.",
    "ob_height":            "¿Qué tan alta está la planta hoy? (cm, ej. `30`) — o `?` para omitir",
    "ob_height_invalid":    "Ingresa un número en cm (ej. `30`) o `?` para omitir.",
    "ob_sun_actual":        "¿Cuántas horas de *luz solar directa* recibe al día? (ej. `4`) — o `?` para omitir",
    "ob_sun_actual_invalid":"Ingresa un número (ej. `4`) o `?` para omitir.",
    "ob_sun_needed":        "¿Cuántas horas de sol *necesita*? (ej. `6`) — o `?` para una sugerencia",
    "ob_sun_looking_up":    "🔍 Buscando requerimientos de luz solar…",
    "ob_sun_result":        "☀️ *{plant_type}* necesita ~*{hours}h* de sol directo.{note}{gap}\n\n¿Cada cuántos días necesita riego? (ej. `7`) — o `?` para una sugerencia",
    "ob_sun_gap_more":      "\n⚠️ Actualmente recibe {actual}h — necesita {diff:.1f}h más.",
    "ob_sun_gap_ok":        "\n✅ Recibe {actual}h — es suficiente.",
    "ob_sun_failed":        "No se pudo contactar la IA. ¿Cada cuántos días necesita riego? (ej. `7`)",
    "ob_sun_invalid":       "Ingresa un número (ej. `6`) o `?` para una sugerencia.",
    "ob_freq":              "¿Cada cuántos días necesita riego? (ej. `7`) — o `?` para una sugerencia",
    "ob_freq_looking_up":   "🔍 Buscando requerimientos de cuidado para tu planta…",
    "ob_freq_result":       "✅ Recomendación para *{plant_type}*:\n• Cada *{freq} días*\n• *{ml} ml* por sesión{note}\n\n¡Ambos guardados! Último paso: envía una *foto* o escribe `omitir`.",
    "ob_freq_failed":       "No se pudo contactar la IA. Ingresa la frecuencia en días (ej. `7`):",
    "ob_freq_invalid":      "Ingresa un número entero de días (ej. `7`) o `?` para una recomendación.",
    "ob_amount":            "¿Cuánta agua por sesión? (ml, ej. `200`) — o `?` para una sugerencia",
    "ob_amount_looking_up": "🔍 Buscando una recomendación…",
    "ob_amount_result":     "✅ Se sugieren *{ml} ml* por sesión para {plant_type}. ¡Guardado!\n\nÚltimo paso: envía una *foto* o escribe `omitir`.",
    "ob_amount_failed":     "No se pudo contactar la IA. Ingresa la cantidad en ml (ej. `200`):",
    "ob_amount_invalid":    "Ingresa un número entero en ml (ej. `200`) o `?` para una sugerencia.",
    "ob_photo":             "Último paso: envía una *foto* de la planta, o escribe `omitir` para hacerlo después.",
    "ob_done": (
        "✅ *{name}* agregada!\n\n"
        "Tipo: {plant_type}\n"
        "{location_line}\n"
        "Suelo: {soil_alk}, {soil_type}\n"
        "Fertilizante: {fert}\n"
        "Orientación: {facing}\n"
        "Altura: {height}\n"
        "Riega cada {freq} días, {ml} ml\n\n"
        "Usa /list para ver todas tus plantas. Usa /height para actualizar la altura."
    ),
    "ob_cancel":       "Cancelado. Usa /add para empezar de nuevo.",
    "location_pot":    "Maceta: {depth} de prof. × {width} de ancho{vol}",
    "location_ground": "Plantada en el suelo",
    "no_plants":       "Aún no tienes plantas — usa /add para comenzar.",
    "list_header":     "🌿 *Tus Plantas*\n",
    "list_row":        "{icon}• *{name}* ({ptype}) — último riego: {last}",
    "plant_not_found": "Planta no encontrada. Usa /list para ver todas tus plantas.",
    "water_usage":     "Uso: `/water <nombre planta> [ml]`",
    "water_logged":    "✅ Registré *{ml} ml* para *{name}*",
    "water_skipped":   "Omitido — *{name}* no regada hoy.",
    "status_usage":    "Uso: `/status <nombre planta>`",
    "status_fert":     "{type}, {amount}, cada {freq} días",
    "status_no_fert":  "ninguno",
    "status_no_hist":  "Sin historial aún.",
    "photo_usage":     "Uso: `/photo <nombre planta>`",
    "photo_none":      "No hay foto guardada para *{name}*. Envía una foto como respuesta a alguna recomendación.",
    "health_pick":     "¿Qué planta quieres analizar?",
    "health_header":   "🔬 *Revisión de salud — {name}*\n\n{response}",
    "height_usage":    "Uso: `/height <nombre planta> <cm>`\nej. `/height Monstera 45`",
    "height_logged":   "📏 Registré *{cm} cm* para *{name}*",
    "daily_all_good":  "{weather}✅ ¡Todas las plantas están al día — no se necesita riego hoy!",
    "daily_rec":       "{weather}🌿 *{name}*\n⏱️ {last}\n💧 Recomendado: *{ml} ml*\n\nResponde con la cantidad que le diste (ej. `{ml}`) o `omitir`.",
    "daily_never":     "nunca regada",
    "daily_today":     "regada hoy",
    "daily_yesterday": "regada ayer",
    "daily_days_ago":  "regada hace {days} días",
    "height_reminder": "📏 *¡Hora de medir la altura de tus plantas!*\n\nResponde con `/height <planta> <cm>` para cada una:",
    # pest / disease / treatment
    "pest_usage":       "Uso: `/pest <planta> <descripción>`\nej. `/pest Jazmín pulgones en las hojas`",
    "pest_logged":      "🐛 Registré plaga en *{name}*: {desc}",
    "disease_usage":    "Uso: `/disease <planta> <descripción>`\nej. `/disease Jazmín roya en hojas bajas`",
    "disease_logged":   "🍂 Registré enfermedad en *{name}*: {desc}",
    "treat_usage":      "Uso: `/treat <planta> [soap] [neem] [spinosad] [kaolin] [notas]`\nej. `/treat Jazmín neem soap`",
    "treat_logged":     "💊 Registré tratamiento para *{name}*: {ingredients}",
    "treat_nothing":    "Especifica al menos un ingrediente: `soap`, `neem`, `spinosad`, `kaolin`",
    "issues_usage":     "Uso: `/issues <planta>`",
    "issues_none":      "No hay problemas abiertos para *{name}* — ¡se ve saludable! 🌿",
    "issues_header":    "⚠️ *Problemas abiertos de {name}*\n",
    "issue_row":        "• [{cat}] {desc} (desde {date})",
}

_STRINGS = {"en": _EN, "es": _ES}


def t(key: str, lang: str = "en", **kwargs) -> str:
    s = _STRINGS.get(lang, _EN).get(key) or _EN.get(key, key)
    return s.format(**kwargs) if kwargs else s


def lang_for(chat_id: int) -> str:
    second = os.getenv("SECOND_USER_CHAT_ID", "")
    return "es" if second and str(chat_id) == second else "en"


# Spanish location aliases → canonical English values stored in DB
LOCATION_ALIASES = {
    "pot": "pot", "maceta": "pot",
    "ground": "ground", "suelo": "ground", "tierra": "ground",
}

# Expanded skip/unsure sets (English + Spanish)
SKIP_WORDS = {"?", "idk", "skip", "unknown", "omitir", "no sé", "desconozco"}
NONE_WORDS  = SKIP_WORDS | {"none", "ninguno", "ninguna"}
UNSURE      = SKIP_WORDS | {"i don't know", "not sure", "unsure", "help", "idc", "ayuda"}
