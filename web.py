import os
import sqlite3
from flask import Flask, render_template, Response, abort
from dotenv import load_dotenv

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
    conn.close()
    return render_template("plant.html", plant=plant, history=history)


@app.route("/plant/<int:plant_id>/photo")
def plant_photo(plant_id):
    conn = get_db()
    row = conn.execute("SELECT image_data FROM plants WHERE id = ?", (plant_id,)).fetchone()
    conn.close()
    if not row or not row["image_data"]:
        abort(404)
    return Response(bytes(row["image_data"]), mimetype="image/jpeg")


if __name__ == "__main__":
    port = int(os.getenv("FLASK_PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
