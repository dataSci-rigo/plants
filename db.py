import aiosqlite
import math
import os
from datetime import datetime, date
from typing import Optional

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plants.db")


def estimate_soil_volume_l(pot_depth_cm, pot_width_cm) -> Optional[float]:
    """Rough soil volume for a cylindrical pot, in liters."""
    if not pot_depth_cm or not pot_width_cm:
        return None
    radius_cm = pot_width_cm / 2
    volume_cm3 = math.pi * radius_cm ** 2 * pot_depth_cm
    return round(volume_cm3 / 1000, 2)


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS plants (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                name                    TEXT    NOT NULL UNIQUE,
                plant_type              TEXT,
                pot_depth_cm            REAL,
                pot_width_cm            REAL,
                location                TEXT,
                soil_alkalinity         TEXT,
                soil_type               TEXT,
                soil_volume_l           REAL,
                fertilizer_type         TEXT,
                fertilizer_amount       TEXT,
                fertilizer_frequency_days INTEGER,
                facing                  TEXT,
                height_cm               REAL,
                sunlight_hours_actual   REAL,
                sunlight_hours_needed   REAL,
                user_id                 INTEGER,
                watering_frequency_days INTEGER NOT NULL DEFAULT 7,
                watering_amount_ml      INTEGER NOT NULL DEFAULT 200,
                notes                   TEXT,
                image_data              BLOB,
                telegram_file_id        TEXT,
                created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS height_history (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                plant_id    INTEGER NOT NULL,
                height_cm   REAL NOT NULL,
                measured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (plant_id) REFERENCES plants(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS watering_history (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                plant_id   INTEGER NOT NULL,
                watered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                amount_ml  INTEGER,
                notes      TEXT,
                FOREIGN KEY (plant_id) REFERENCES plants(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS plant_messages (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                plant_id   INTEGER NOT NULL,
                chat_id    INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                FOREIGN KEY (plant_id) REFERENCES plants(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS weather_cache (
                date        TEXT NOT NULL PRIMARY KEY,
                temp_c      REAL,
                humidity    INTEGER,
                description TEXT,
                fetched_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS issues (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                plant_id    INTEGER NOT NULL,
                category    TEXT NOT NULL DEFAULT 'other',
                description TEXT NOT NULL,
                severity    TEXT DEFAULT 'mild',
                resolved    INTEGER DEFAULT 0,
                observed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                resolved_at TIMESTAMP,
                FOREIGN KEY (plant_id) REFERENCES plants(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS treatments (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                plant_id   INTEGER NOT NULL,
                soap       INTEGER DEFAULT 0,
                spinosad   INTEGER DEFAULT 0,
                neem       INTEGER DEFAULT 0,
                kaolin     INTEGER DEFAULT 0,
                notes      TEXT,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (plant_id) REFERENCES plants(id) ON DELETE CASCADE
            );
        """)
        await db.commit()
        # Migrations: add columns introduced after the initial schema, for existing databases
        for column_sql in (
            "ALTER TABLE plants ADD COLUMN pot_width_cm REAL",
            "ALTER TABLE plants ADD COLUMN location TEXT",
            "ALTER TABLE plants ADD COLUMN soil_alkalinity TEXT",
            "ALTER TABLE plants ADD COLUMN soil_type TEXT",
            "ALTER TABLE plants ADD COLUMN soil_volume_l REAL",
            "ALTER TABLE plants ADD COLUMN fertilizer TEXT",
            "ALTER TABLE plants ADD COLUMN fertilizer_type TEXT",
            "ALTER TABLE plants ADD COLUMN fertilizer_amount TEXT",
            "ALTER TABLE plants ADD COLUMN fertilizer_frequency_days INTEGER",
            "ALTER TABLE plants ADD COLUMN facing TEXT",
            "ALTER TABLE plants ADD COLUMN height_cm REAL",
            "ALTER TABLE plants ADD COLUMN sunlight_hours_actual REAL",
            "ALTER TABLE plants ADD COLUMN sunlight_hours_needed REAL",
            "ALTER TABLE plants ADD COLUMN user_id INTEGER",
        ):
            try:
                await db.execute(column_sql)
                await db.commit()
            except Exception:
                pass  # column already exists
        # Backfill user_id for plants that pre-date multi-user support
        owner_id = os.getenv("OWNER_CHAT_ID")
        if owner_id:
            await db.execute(
                "UPDATE plants SET user_id = ? WHERE user_id IS NULL", (int(owner_id),)
            )
            await db.commit()


async def add_plant(
    name, plant_type, pot_depth_cm, pot_width_cm, location, soil_alkalinity,
    soil_type, fertilizer_type, fertilizer_amount, fertilizer_frequency_days,
    facing, height_cm, sunlight_hours_actual, sunlight_hours_needed,
    watering_frequency_days, watering_amount_ml, user_id=None,
) -> int:
    soil_volume_l = estimate_soil_volume_l(pot_depth_cm, pot_width_cm) if location == "pot" else None
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """INSERT INTO plants (
                   name, plant_type, pot_depth_cm, pot_width_cm, location,
                   soil_alkalinity, soil_type, soil_volume_l, fertilizer_type,
                   fertilizer_amount, fertilizer_frequency_days, facing, height_cm,
                   sunlight_hours_actual, sunlight_hours_needed,
                   watering_frequency_days, watering_amount_ml, user_id
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                name, plant_type, pot_depth_cm, pot_width_cm, location,
                soil_alkalinity, soil_type, soil_volume_l, fertilizer_type,
                fertilizer_amount, fertilizer_frequency_days, facing, height_cm,
                sunlight_hours_actual, sunlight_hours_needed,
                watering_frequency_days, watering_amount_ml, user_id,
            ),
        )
        await db.commit()
        if height_cm is not None:
            await db.execute(
                "INSERT INTO height_history (plant_id, height_cm) VALUES (?, ?)",
                (cursor.lastrowid, height_cm),
            )
            await db.commit()
        return cursor.lastrowid


async def get_all_plants(user_id=None):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if user_id is not None:
            cursor = await db.execute(
                "SELECT * FROM plants WHERE user_id = ? ORDER BY name", (user_id,)
            )
        else:
            cursor = await db.execute("SELECT * FROM plants ORDER BY name")
        return await cursor.fetchall()


async def get_plant(plant_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM plants WHERE id = ?", (plant_id,))
        return await cursor.fetchone()


async def get_plant_by_name(name: str, user_id=None):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if user_id is not None:
            cursor = await db.execute(
                "SELECT * FROM plants WHERE LOWER(name) = LOWER(?) AND user_id = ?",
                (name, user_id),
            )
        else:
            cursor = await db.execute(
                "SELECT * FROM plants WHERE LOWER(name) = LOWER(?)", (name,)
            )
        return await cursor.fetchone()


async def update_plant_image(plant_id: int, image_data: bytes, file_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE plants SET image_data = ?, telegram_file_id = ? WHERE id = ?",
            (image_data, file_id, plant_id),
        )
        await db.commit()


async def update_plant(plant_id: int, **fields):
    """Update any subset of plant fields. Recomputes soil_volume_l if pot dims change."""
    if not fields:
        return
    # Recompute soil volume if relevant dims are being updated
    if "pot_depth_cm" in fields or "pot_width_cm" in fields:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            row = await (await db.execute("SELECT pot_depth_cm, pot_width_cm, location FROM plants WHERE id=?", (plant_id,))).fetchone()
        depth = fields.get("pot_depth_cm", row["pot_depth_cm"] if row else None)
        width = fields.get("pot_width_cm", row["pot_width_cm"] if row else None)
        loc = fields.get("location", row["location"] if row else None)
        fields["soil_volume_l"] = estimate_soil_volume_l(depth, width) if loc == "pot" else None

    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [plant_id]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE plants SET {set_clause} WHERE id = ?", values)
        await db.commit()


async def log_watering(plant_id: int, amount_ml: int, notes: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO watering_history (plant_id, amount_ml, notes) VALUES (?, ?, ?)",
            (plant_id, amount_ml, notes),
        )
        await db.commit()


async def get_last_watered(plant_id: int) -> Optional[tuple]:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT watered_at, amount_ml FROM watering_history WHERE plant_id = ? ORDER BY watered_at DESC LIMIT 1",
            (plant_id,),
        )
        return await cursor.fetchone()


async def get_watering_history(plant_id: int, limit: int = 10):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM watering_history WHERE plant_id = ? ORDER BY watered_at DESC LIMIT ?",
            (plant_id, limit),
        )
        return await cursor.fetchall()


async def save_plant_message(plant_id: int, chat_id: int, message_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO plant_messages (plant_id, chat_id, message_id) VALUES (?, ?, ?)",
            (plant_id, chat_id, message_id),
        )
        await db.commit()


async def get_plant_by_message(chat_id: int, message_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT p.* FROM plants p
               JOIN plant_messages pm ON p.id = pm.plant_id
               WHERE pm.chat_id = ? AND pm.message_id = ?""",
            (chat_id, message_id),
        )
        return await cursor.fetchone()


async def get_plants_by_message(chat_id: int, message_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT p.* FROM plants p
               JOIN plant_messages pm ON p.id = pm.plant_id
               WHERE pm.chat_id = ? AND pm.message_id = ?""",
            (chat_id, message_id),
        )
        return await cursor.fetchall()


async def get_plants_needing_water():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT p.*, MAX(wh.watered_at) AS last_watered
            FROM plants p
            LEFT JOIN watering_history wh ON p.id = wh.plant_id
            GROUP BY p.id
            HAVING last_watered IS NULL
               OR julianday('now') - julianday(last_watered) >= p.watering_frequency_days
        """)
        return await cursor.fetchall()


async def get_plants_needing_water_for_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT p.*, MAX(wh.watered_at) AS last_watered
            FROM plants p
            LEFT JOIN watering_history wh ON p.id = wh.plant_id
            WHERE p.user_id = ?
            GROUP BY p.id
            HAVING last_watered IS NULL
               OR julianday('now') - julianday(last_watered) >= p.watering_frequency_days
        """, (user_id,))
        return await cursor.fetchall()


async def log_height(plant_id: int, height_cm: float):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO height_history (plant_id, height_cm) VALUES (?, ?)",
            (plant_id, height_cm),
        )
        await db.execute(
            "UPDATE plants SET height_cm = ? WHERE id = ?", (height_cm, plant_id)
        )
        await db.commit()


async def get_height_history(plant_id: int, limit: int = 20):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM height_history WHERE plant_id = ? ORDER BY measured_at DESC LIMIT ?",
            (plant_id, limit),
        )
        return await cursor.fetchall()


async def get_setting(key: str) -> Optional[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = await cursor.fetchone()
        return row[0] if row else None


async def set_setting(key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value))
        )
        await db.commit()


async def cache_weather(temp_c: float, humidity: int, description: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO weather_cache (date, temp_c, humidity, description) VALUES (?, ?, ?, ?)",
            (date.today().isoformat(), temp_c, humidity, description),
        )
        await db.commit()


async def get_cached_weather() -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT temp_c, humidity, description FROM weather_cache WHERE date = ?",
            (date.today().isoformat(),),
        )
        row = await cursor.fetchone()
        return {"temp_c": row[0], "humidity": row[1], "description": row[2]} if row else None


async def log_issue(plant_id: int, category: str, description: str, severity: str = "mild") -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO issues (plant_id, category, description, severity) VALUES (?, ?, ?, ?)",
            (plant_id, category, description, severity),
        )
        await db.commit()
        return cursor.lastrowid


async def get_issues(plant_id: int, open_only: bool = False):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if open_only:
            cursor = await db.execute(
                "SELECT * FROM issues WHERE plant_id = ? AND resolved = 0 ORDER BY observed_at DESC",
                (plant_id,),
            )
        else:
            cursor = await db.execute(
                "SELECT * FROM issues WHERE plant_id = ? ORDER BY observed_at DESC",
                (plant_id,),
            )
        return await cursor.fetchall()


async def resolve_issue(issue_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE issues SET resolved = 1, resolved_at = CURRENT_TIMESTAMP WHERE id = ?",
            (issue_id,),
        )
        await db.commit()


async def log_treatment(
    plant_id: int,
    soap: bool = False, spinosad: bool = False, neem: bool = False, kaolin: bool = False,
    notes: str = None,
) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO treatments (plant_id, soap, spinosad, neem, kaolin, notes) VALUES (?, ?, ?, ?, ?, ?)",
            (plant_id, int(soap), int(spinosad), int(neem), int(kaolin), notes),
        )
        await db.commit()
        return cursor.lastrowid


async def get_treatments(plant_id: int, limit: int = 20):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM treatments WHERE plant_id = ? ORDER BY applied_at DESC LIMIT ?",
            (plant_id, limit),
        )
        return await cursor.fetchall()
