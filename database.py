
import sqlite3
from datetime import datetime

DB_NAME = "macrosnap.db"


def get_connection():
    connection = sqlite3.connect(DB_NAME)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database():
    with get_connection() as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS meals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_email TEXT NOT NULL,
                meal_name TEXT NOT NULL,
                calories REAL NOT NULL DEFAULT 0,
                protein REAL NOT NULL DEFAULT 0,
                carbs REAL NOT NULL DEFAULT 0,
                fat REAL NOT NULL DEFAULT 0,
                eaten_at TEXT NOT NULL
            )
        """)


def save_meal(
    user_email,
    meal_name,
    calories,
    protein,
    carbs,
    fat,
):
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO meals (
                user_email, meal_name, calories,
                protein, carbs, fat, eaten_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_email,
                meal_name,
                calories,
                protein,
                carbs,
                fat,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )


def get_meals(user_email):
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM meals
            WHERE user_email = ?
            ORDER BY eaten_at DESC
            """,
            (user_email,),
        ).fetchall()

    return [dict(row) for row in rows]
