import json
import os
import re
import base64
import logging
import anthropic

logger = logging.getLogger(__name__)


async def suggest_watering_schedule(plant_name: str, plant_type: str, pot_depth_cm) -> dict:
    """Use Claude Haiku to recommend a watering schedule when the user doesn't know."""
    client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    depth_str = f"{pot_depth_cm} cm deep pot" if pot_depth_cm else "pot depth unknown"
    prompt = (
        f'Plant: "{plant_name}" ({plant_type}), {depth_str}.\n'
        "Give a watering recommendation as JSON only, no other text:\n"
        '{"frequency_days": <int>, "amount_ml": <int>, "note": "<one sentence why>"}'
    )
    try:
        resp = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=120,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        m = re.search(r"\{.*\}", text, re.DOTALL)
        data = json.loads(m.group()) if m else {}
        return {
            "frequency_days": int(data.get("frequency_days", 7)),
            "amount_ml": int(data.get("amount_ml", 200)),
            "note": data.get("note", ""),
        }
    except Exception as e:
        logger.error(f"suggest_watering_schedule failed: {e}")
        return {"frequency_days": 7, "amount_ml": 200, "note": ""}


async def suggest_sunlight_needs(plant_name: str, plant_type: str, facing: str = None) -> dict:
    client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    facing_str = f", facing {facing}" if facing else ""
    prompt = (
        f'Plant: "{plant_name}" ({plant_type}){facing_str}.\n'
        "How many hours of direct sunlight does this plant need per day? JSON only:\n"
        '{"hours_needed": <float>, "note": "<one sentence>"}'
    )
    try:
        resp = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=80,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        m = re.search(r"\{.*\}", text, re.DOTALL)
        data = json.loads(m.group()) if m else {}
        return {
            "hours_needed": float(data.get("hours_needed", 6.0)),
            "note": data.get("note", ""),
        }
    except Exception as e:
        logger.error(f"suggest_sunlight_needs failed: {e}")
        return {"hours_needed": 6.0, "note": ""}


async def analyze_plant_image(image_data: bytes) -> dict:
    """One-shot vision call: identify plant and return structured care suggestions."""
    client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    b64 = base64.standard_b64encode(image_data).decode()
    prompt = (
        "Look at this plant photo. Return ONLY a valid JSON object, no other text:\n"
        "{\n"
        '  "name_suggestions": ["<most likely>","<2nd>","<3rd>","<4th>","<5th>"],\n'
        '  "plant_type": "<e.g. succulent, tropical houseplant, fern>",\n'
        '  "location": "<pot|ground|null>",\n'
        '  "soil_type": "<potting mix|cactus mix|garden soil|null>",\n'
        '  "height_cm": <number or null>,\n'
        '  "pot_depth_cm": <number or null>,\n'
        '  "pot_width_cm": <number or null>,\n'
        '  "watering_frequency_days": <int>,\n'
        '  "watering_amount_ml": <int>,\n'
        '  "sunlight_hours_needed": <float>,\n'
        '  "notes": "<one sentence about the plant\'s apparent condition>"\n'
        "}"
    )
    try:
        resp = await client.messages.create(
            model="claude-opus-4-7",
            max_tokens=512,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                {"type": "text", "text": prompt},
            ]}],
        )
        text = resp.content[0].text.strip()
        m = re.search(r"\{.*\}", text, re.DOTALL)
        data = json.loads(m.group()) if m else {}
        names = data.get("name_suggestions", [])
        data["name_suggestions"] = [str(n) for n in names[:5]] if isinstance(names, list) else []
        return data
    except Exception as e:
        logger.error("analyze_plant_image failed: %s", e)
        return {
            "name_suggestions": [], "plant_type": None, "location": None,
            "soil_type": None, "height_cm": None, "pot_depth_cm": None, "pot_width_cm": None,
            "watering_frequency_days": 7, "watering_amount_ml": 200,
            "sunlight_hours_needed": 6.0, "notes": "",
        }


async def suggest_care(
    plant_name: str,
    plant_type: str | None,
    pot_width_cm: float | None,
    pot_depth_cm: float | None,
    perenual_data: dict,
) -> dict:
    """Return fertilizer, trimming, and pot-size recommendations."""
    client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    p_lines = []
    if perenual_data.get("scientific_name"):
        p_lines.append(f"Scientific name: {', '.join(perenual_data['scientific_name'])}")
    if perenual_data.get("care_level"):
        p_lines.append(f"Care level: {perenual_data['care_level']}")
    if perenual_data.get("growth_rate"):
        p_lines.append(f"Growth rate: {perenual_data['growth_rate']}")
    if perenual_data.get("pruning_month"):
        p_lines.append(f"Pruning months (from database): {', '.join(perenual_data['pruning_month'])}")
    if perenual_data.get("dimension"):
        p_lines.append(f"Mature size: {perenual_data['dimension']}")
    perenual_str = "\n".join(p_lines) if p_lines else "No database entry found."

    pot_str = (
        f"{pot_width_cm} cm wide, {pot_depth_cm} cm deep"
        if pot_width_cm or pot_depth_cm
        else "unknown"
    )
    prompt = (
        f'Plant: "{plant_name}" ({plant_type or "unknown type"})\n'
        f"Current pot: {pot_str}\n\n"
        f"Database info:\n{perenual_str}\n\n"
        "Return ONLY valid JSON, no other text:\n"
        "{\n"
        '  "fertilizer_type": "<e.g. balanced 10-10-10 or liquid kelp>",\n'
        '  "fertilizer_frequency": "<e.g. every 4 weeks in spring/summer, none in winter>",\n'
        '  "trimming_notes": "<when and how to trim/prune>",\n'
        '  "pot_upgrade": <true|false>,\n'
        '  "recommended_pot_cm": <number or null>,\n'
        '  "notes": "<one extra care tip>"\n'
        "}"
    )
    try:
        resp = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=350,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        m = re.search(r"\{.*\}", text, re.DOTALL)
        data = json.loads(m.group()) if m else {}
        return {
            "fertilizer_type":      str(data.get("fertilizer_type", "")),
            "fertilizer_frequency": str(data.get("fertilizer_frequency", "")),
            "trimming_notes":       str(data.get("trimming_notes", "")),
            "pot_upgrade":          bool(data.get("pot_upgrade", False)),
            "recommended_pot_cm":   data.get("recommended_pot_cm"),
            "notes":                str(data.get("notes", "")),
        }
    except Exception as e:
        logger.error("suggest_care failed: %s", e)
        return {
            "fertilizer_type": "", "fertilizer_frequency": "",
            "trimming_notes": "", "pot_upgrade": False,
            "recommended_pot_cm": None, "notes": "",
        }


async def generate_plant_report(
    plant_name: str,
    plant_type: str | None,
    pot_width_cm: float | None,
    pot_depth_cm: float | None,
    image_data: bytes | None,
    perenual_data: dict,
) -> dict:
    """Full health + care analysis. Call 2 after user confirms species/pot/height."""
    client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    p_lines = []
    if perenual_data.get("scientific_name"):
        p_lines.append(f"Scientific name: {', '.join(perenual_data['scientific_name'])}")
    if perenual_data.get("care_level"):
        p_lines.append(f"Care level: {perenual_data['care_level']}")
    if perenual_data.get("growth_rate"):
        p_lines.append(f"Growth rate: {perenual_data['growth_rate']}")
    if perenual_data.get("pruning_month"):
        p_lines.append(f"Typical pruning months: {', '.join(perenual_data['pruning_month'])}")
    if perenual_data.get("dimension"):
        p_lines.append(f"Mature size: {perenual_data['dimension']}")
    perenual_str = "\n".join(p_lines) if p_lines else "No database entry found."

    pot_str = (
        f"{pot_width_cm} cm wide, {pot_depth_cm} cm deep"
        if (pot_width_cm or pot_depth_cm)
        else "unknown"
    )
    prompt = (
        f'Plant: "{plant_name}" ({plant_type or "unknown type"})\n'
        f"Current pot: {pot_str}\n\n"
        f"Database info:\n{perenual_str}\n\n"
        "Analyze this plant and return ONLY a valid JSON object, no other text:\n"
        "{\n"
        '  "health": "<assess: overwatering, underwatering, sun scorch, mold, overheating, pot size — one paragraph>",\n'
        '  "fertilizer": "<type and schedule, including seasonal rest periods>",\n'
        '  "repotting": "<when to repot, recommended pot size and soil mix>",\n'
        '  "pruning": "<when and how to prune or trim>",\n'
        '  "insecticide": "<preventive and reactive insecticide/pesticide recommendations>"\n'
        "}"
    )

    content: list = []
    if image_data:
        b64 = base64.standard_b64encode(image_data).decode()
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": b64},
        })
    content.append({"type": "text", "text": prompt})

    _empty = {"health": "", "fertilizer": "", "repotting": "", "pruning": "", "insecticide": ""}
    try:
        resp = await client.messages.create(
            model="claude-opus-4-7",
            max_tokens=900,
            messages=[{"role": "user", "content": content}],
        )
        text = resp.content[0].text.strip()
        m = re.search(r"\{.*\}", text, re.DOTALL)
        data = json.loads(m.group()) if m else {}
        return {k: str(data.get(k, "")) for k in _empty}
    except Exception as e:
        logger.error("generate_plant_report failed: %s", e)
        return _empty


async def analyze_plant_health(plant: dict, image_data: bytes | None) -> str:
    client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    content = []

    if image_data:
        b64 = base64.standard_b64encode(image_data).decode()
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": b64},
        })

    history = plant.get("history", [])
    if history:
        history_lines = "\n".join(
            f"  - {h['watered_at'][:16]}: {h['amount_ml']} ml" for h in history
        )
    else:
        history_lines = "  No watering history recorded."

    prompt = f"""How is this plant doing?

Plant details:
- Name: {plant['name']}
- Type: {plant.get('plant_type') or 'Unknown'}
- Pot depth: {plant.get('pot_depth_cm') or 'Unknown'} cm
- Watering schedule: every {plant.get('watering_frequency_days', '?')} days, {plant.get('watering_amount_ml', '?')} ml per session

Recent watering history (last 10 sessions):
{history_lines}

Please assess the plant's condition based on the image and data. Cover:
1. Overall health assessment
2. Any visible issues or concerns
3. Whether the watering schedule seems appropriate
4. Any other care tips
"""
    content.append({"type": "text", "text": prompt})

    try:
        response = await client.messages.create(
            model="claude-opus-4-7",
            max_tokens=1024,
            messages=[{"role": "user", "content": content}],
        )
        return response.content[0].text
    except Exception as e:
        logger.error(f"Anthropic API error: {e}")
        return f"Could not analyze plant health: {e}"
