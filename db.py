import aiosqlite
from datetime import datetime, date
from typing import Optional

DB_PATH = "plants.db"


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS plants (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                name                    TEXT    NOT NULL UNIQUE,
                plant_type              TEXT,
                pot_depth_cm            REAL,
                pot_width_cm            REAL,
                watering_frequency_days INTEGER NOT NULL DEFAULT 7,
                watering_amount_ml      INTEGER NOT NULL DEFAULT 200,
                notes                   TEXT,
                image_data              BLOB,
                telegram_file_id        TEXT,
                created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
        """)
        await db.commit()
        # Migration: add pot_width_cm to existing databases
        try:
            await db.execute("ALTER TABLE plants ADD COLUMN pot_width_cm REAL")
            await db.commit()
        except Exception:
            pass  # column already exists


async def add_plant(name, plant_type, pot_depth_cm, pot_width_cm, watering_frequency_days, watering_amount_ml) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """INSERT INTO plants (name, plant_type, pot_depth_cm, pot_width_cm, watering_frequency_days, watering_amount_ml)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (name, plant_type, pot_depth_cm, pot_width_cm, watering_frequency_days, watering_amount_ml),
        )
        await db.commit()
        return cursor.lastrowid


async def get_all_plants():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM plants ORDER BY name")
        return await cursor.fetchall()


async def get_plant(plant_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM plants WHERE id = ?", (plant_id,))
        return await cursor.fetchone()


async def get_plant_by_name(name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
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
