import os
import sqlite3
from flask import Flask, render_template, Response, abort, request, redirect, url_for
from dotenv import load_dotenv
from db import estimate_soil_volume_l

load_dotenv()

app = Flask(__name__)
DB_PATH = "plants.db"


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


@app.route("/")
def index():
    conn = get_db()
    plants = conn.execute("""
        SELECT p.*,
               MAX(wh.watered_at)    AS last_watered,
               COUNT(wh.id)          AS watering_count
        FROM plants p
        LEFT JOIN watering_history wh ON p.id = wh.plant_id
        GROUP BY p.id
        ORDER BY p.name
    """).fetchall()
    conn.close()
    return render_template("index.html", plants=plants)


@app.route("/plant/<int:plant_id>")
def plant_detail(plant_id):
    conn = get_db()
    plant = conn.execute("SELECT * FROM plants WHERE id = ?", (plant_id,)).fetchone()
    if not plant:
        abort(404)
    history = conn.execute(
        "SELECT * FROM watering_history WHERE plant_id = ? ORDER BY watered_at DESC",
        (plant_id,),
    ).fetchall()
    height_history = conn.execute(
        "SELECT * FROM height_history WHERE plant_id = ? ORDER BY measured_at DESC",
        (plant_id,),
    ).fetchall()
    conn.close()
    return render_template("plant.html", plant=plant, history=history, height_history=height_history)


@app.route("/plant/<int:plant_id>/edit", methods=["GET", "POST"])
def plant_edit(plant_id):
    conn = get_db()
    plant = conn.execute("SELECT * FROM plants WHERE id = ?", (plant_id,)).fetchone()
    if not plant:
        conn.close()
        abort(404)

    if request.method == "POST":
        f = request.form

        def _float(key):
            v = f.get(key, "").strip()
            return float(v) if v else None

        def _int(key):
            v = f.get(key, "").strip()
            return int(v) if v else None

        def _str(key):
            v = f.get(key, "").strip()
            return v if v else None

        location = _str("location")
        pot_depth = _float("pot_depth_cm")
        pot_width = _float("pot_width_cm")
        soil_volume = estimate_soil_volume_l(pot_depth, pot_width) if location == "pot" else None

        fields = dict(
            name=f.get("name", "").strip(),
            plant_type=_str("plant_type"),
            location=location,
            pot_depth_cm=pot_depth,
            pot_width_cm=pot_width,
            soil_volume_l=soil_volume,
            soil_alkalinity=_str("soil_alkalinity"),
            soil_type=_str("soil_type"),
            fertilizer_type=_str("fertilizer_type"),
            fertilizer_amount=_str("fertilizer_amount"),
            fertilizer_frequency_days=_int("fertilizer_frequency_days"),
            facing=_str("facing"),
            height_cm=_float("height_cm"),
            sunlight_hours_actual=_float("sunlight_hours_actual"),
            sunlight_hours_needed=_float("sunlight_hours_needed"),
            watering_frequency_days=_int("watering_frequency_days") or 7,
            watering_amount_ml=_int("watering_amount_ml") or 200,
            notes=_str("notes"),
        )

        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [plant_id]
        conn.execute(f"UPDATE plants SET {set_clause} WHERE id = ?", values)

        # Photo replacement
        photo = request.files.get("photo")
        if photo and photo.filename:
            image_data = photo.read()
            conn.execute(
                "UPDATE plants SET image_data = ?, telegram_file_id = NULL WHERE id = ?",
                (image_data, plant_id),
            )

        conn.commit()
        conn.close()
        return redirect(url_for("plant_detail", plant_id=plant_id))

    conn.close()
    return render_template("edit.html", plant=plant)


@app.route("/plant/<int:plant_id>/photo")
def plant_photo(plant_id):
    conn = get_db()
    row = conn.execute("SELECT image_data FROM plants WHERE id = ?", (plant_id,)).fetchone()
    conn.close()
    if not row or not row["image_data"]:
        abort(404)
    return Response(bytes(row["image_data"]), mimetype="image/jpeg")


if __name__ == "__main__":
    port = int(os.getenv("PORT_PLANTS", os.getenv("FLASK_PORT", 5060)))
    app.run(host="0.0.0.0", port=port, debug=False)
