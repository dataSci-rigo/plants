import os
import base64
import logging
import anthropic

logger = logging.getLogger(__name__)


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
