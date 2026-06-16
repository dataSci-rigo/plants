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
