import sqlite3
from pathlib import Path


DB_DIR = Path("data")
DB_DIR.mkdir(exist_ok=True)

DB_PATH = DB_DIR / "attendance.db"


def get_connection():
    return sqlite3.connect(DB_PATH)


def initialize_database():
    conn = get_connection()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            subject TEXT PRIMARY KEY,
            classes_held INTEGER NOT NULL,
            classes_present INTEGER NOT NULL,
            percentage REAL NOT NULL
        )
    """)

    conn.commit()
    conn.close()


def get_previous_attendance():
    conn = get_connection()

    rows = conn.execute("""
        SELECT subject, classes_held, classes_present, percentage
        FROM attendance
    """).fetchall()

    conn.close()

    result = {}

    for subject, held, present, percentage in rows:
        result[subject] = {
            "classes_held": held,
            "classes_present": present,
            "percentage": percentage
        }

    return result


def save_attendance(data):
    conn = get_connection()

    for item in data:
        conn.execute("""
            INSERT INTO attendance
            (
                subject,
                classes_held,
                classes_present,
                percentage
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(subject)
            DO UPDATE SET
                classes_held = excluded.classes_held,
                classes_present = excluded.classes_present,
                percentage = excluded.percentage
        """, (
            item["subject"],
            item["classes_held"],
            item["classes_present"],
            item["percentage"]
        ))

    conn.commit()
    conn.close()