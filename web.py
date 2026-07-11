import os
import sqlite3
from flask import Flask, render_template, Response, abort, request, redirect, url_for
from dotenv import load_dotenv
from db import estimate_soil_volume_l

load_dotenv()

app = Flask(__name__)
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plants.db")


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


@app.route("/")
def index():
    owner_id = os.getenv("OWNER_CHAT_ID", "")
    second_id = os.getenv("SECOND_USER_CHAT_ID", "")

    conn = get_db()
    rows = conn.execute("""
        SELECT p.*,
               MAX(wh.watered_at)    AS last_watered,
               COUNT(wh.id)          AS watering_count
        FROM plants p
        LEFT JOIN watering_history wh ON p.id = wh.plant_id
        GROUP BY p.id
        ORDER BY p.name
    """).fetchall()
    conn.close()

    plants = []
    for row in rows:
        p = dict(row)
        uid = str(p.get("user_id") or "")
        if uid == owner_id:
            p["user_label"] = "owner"
        elif uid == second_id:
            p["user_label"] = "guest"
        else:
            p["user_label"] = None
        plants.append(p)

    return render_template("plants_list.html", plants=plants, url_prefix="")


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
    issues = conn.execute(
        "SELECT * FROM issues WHERE plant_id = ? ORDER BY resolved ASC, observed_at DESC",
        (plant_id,),
    ).fetchall()
    treatments = conn.execute(
        "SELECT * FROM treatments WHERE plant_id = ? ORDER BY applied_at DESC",
        (plant_id,),
    ).fetchall()
    conn.close()
    return render_template("plant.html", plant=plant, history=history,
                           height_history=height_history, issues=issues, treatments=treatments,
                           url_prefix="")


@app.route("/plant/new", methods=["GET", "POST"])
def plant_new():
    if request.method == "GET":
        return render_template("add.html", url_prefix="")

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

    name = f.get("name", "").strip()
    if not name:
        return render_template("add.html", url_prefix="", error="Name is required.")

    location = _str("location")
    pot_depth = _float("pot_depth_cm")
    pot_width = _float("pot_width_cm")
    soil_volume = estimate_soil_volume_l(pot_depth, pot_width) if location == "pot" else None

    conn = get_db()
    try:
        cursor = conn.execute(
            """INSERT INTO plants (
                name, plant_type, location, pot_depth_cm, pot_width_cm, soil_volume_l,
                soil_alkalinity, soil_type, fertilizer_type, fertilizer_amount,
                fertilizer_frequency_days, facing, height_cm, sunlight_hours_actual,
                sunlight_hours_needed, watering_frequency_days, watering_amount_ml, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                name, _str("plant_type"), location, pot_depth, pot_width, soil_volume,
                _str("soil_alkalinity"), _str("soil_type"), _str("fertilizer_type"),
                _str("fertilizer_amount"), _int("fertilizer_frequency_days"),
                _str("facing"), _float("height_cm"), _float("sunlight_hours_actual"),
                _float("sunlight_hours_needed"),
                _int("watering_frequency_days") or 7,
                _int("watering_amount_ml") or 200,
                _str("notes"),
            ),
        )
        plant_id = cursor.lastrowid
        if _float("height_cm"):
            conn.execute(
                "INSERT INTO height_history (plant_id, height_cm) VALUES (?, ?)",
                (plant_id, _float("height_cm")),
            )
        photo = request.files.get("photo")
        if photo and photo.filename:
            conn.execute(
                "UPDATE plants SET image_data = ? WHERE id = ?",
                (photo.read(), plant_id),
            )
        conn.commit()
    except Exception as e:
        conn.close()
        return render_template("add.html", url_prefix="", error=str(e))
    conn.close()
    return redirect(url_for("plant_detail", plant_id=plant_id))


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
    return render_template("edit.html", plant=plant, url_prefix="")


@app.route("/plant/<int:plant_id>/issue", methods=["POST"])
def plant_log_issue(plant_id):
    conn = get_db()
    plant = conn.execute("SELECT id FROM plants WHERE id = ?", (plant_id,)).fetchone()
    if not plant:
        conn.close()
        abort(404)
    category = request.form.get("category", "other")
    description = request.form.get("description", "").strip()
    if description:
        conn.execute(
            "INSERT INTO issues (plant_id, category, description) VALUES (?, ?, ?)",
            (plant_id, category, description),
        )
        conn.commit()
    conn.close()
    return redirect(url_for("plant_detail", plant_id=plant_id))


@app.route("/plant/<int:plant_id>/issue/<int:issue_id>/resolve", methods=["POST"])
def plant_resolve_issue(plant_id, issue_id):
    conn = get_db()
    conn.execute(
        "UPDATE issues SET resolved = 1, resolved_at = CURRENT_TIMESTAMP WHERE id = ? AND plant_id = ?",
        (issue_id, plant_id),
    )
    conn.commit()
    conn.close()
    return redirect(url_for("plant_detail", plant_id=plant_id))


@app.route("/plant/<int:plant_id>/treat", methods=["POST"])
def plant_log_treatment(plant_id):
    conn = get_db()
    plant = conn.execute("SELECT id FROM plants WHERE id = ?", (plant_id,)).fetchone()
    if not plant:
        conn.close()
        abort(404)
    f = request.form
    soap     = 1 if f.get("soap")     else 0
    spinosad = 1 if f.get("spinosad") else 0
    neem     = 1 if f.get("neem")     else 0
    kaolin   = 1 if f.get("kaolin")   else 0
    notes    = f.get("notes", "").strip() or None
    conn.execute(
        "INSERT INTO treatments (plant_id, soap, spinosad, neem, kaolin, notes) VALUES (?, ?, ?, ?, ?, ?)",
        (plant_id, soap, spinosad, neem, kaolin, notes),
    )
    conn.commit()
    conn.close()
    return redirect(url_for("plant_detail", plant_id=plant_id))


@app.route("/plant/<int:plant_id>/water", methods=["POST"])
def plant_water(plant_id):
    conn = get_db()
    plant = conn.execute("SELECT id FROM plants WHERE id = ?", (plant_id,)).fetchone()
    if not plant:
        conn.close()
        abort(404)
    amount_ml = int(request.form.get("amount_ml") or 200)
    conn.execute(
        "INSERT INTO watering_history (plant_id, amount_ml) VALUES (?, ?)",
        (plant_id, amount_ml),
    )
    conn.commit()
    conn.close()
    return redirect(url_for("plant_detail", plant_id=plant_id))


@app.route("/plant/<int:plant_id>/photo")
def plant_photo(plant_id):
    conn = get_db()
    row = conn.execute("SELECT image_data FROM plants WHERE id = ?", (plant_id,)).fetchone()
    conn.close()
    if not row or not row["image_data"]:
        abort(404)
    return Response(bytes(row["image_data"]), mimetype="image/jpeg")


if __name__ == "__main__":
    port = int(os.getenv("CONTROL_PANEL_PORT", os.getenv("PORT_PLANTS", os.getenv("FLASK_PORT", 5060))))
    app.run(host="0.0.0.0", port=port, debug=False)
