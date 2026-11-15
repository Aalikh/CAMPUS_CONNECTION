"""SQLite setup and sample data for CampusConnect."""
import random
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).with_name("campusconnect.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS resources(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, type TEXT NOT NULL, capacity INTEGER);
CREATE TABLE IF NOT EXISTS bookings(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  resource_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
  date TEXT NOT NULL, start_time TEXT NOT NULL, end_time TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'booked',   -- booked | checked_in | cancelled | no_show
  qr_token TEXT UNIQUE, checked_in_at TEXT);
"""

USERS = [("Aalikh M", "student"), ("Priya S", "student"), ("Rahul K", "student"),
         ("Gopinathan", "faculty"), ("Dr. Meena R", "faculty"), ("Nishanth Kumar P", "admin")]

# (name, type, capacity, popularity weight for sample data)
RESOURCES = [
    ("Classroom A-101", "classroom", 60, 4), ("Classroom A-102", "classroom", 60, 4),
    ("Classroom B-201", "classroom", 40, 3), ("Classroom C-204", "classroom", 40, 1),
    ("Computer Lab 1", "lab", 30, 6), ("Computer Lab 2", "lab", 30, 5),
    ("Electronics Lab", "lab", 25, 2), ("Physics Lab", "lab", 25, 1),
    ("Library Floor 1", "library", 120, 6), ("Library Floor 2", "library", 100, 5),
    ("Study Room A", "study room", 6, 4), ("Study Room B", "study room", 6, 3),
    ("Study Room C", "study room", 8, 2), ("Study Room D", "study room", 8, 1),
    ("Seminar Hall", "seminar hall", 150, 3),
]
HOUR_WEIGHT = {8: .3, 9: .5, 10: .7, 11: .9, 12: .8, 13: .9, 14: .85, 15: .7, 16: .5, 17: .3}


def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.executescript(SCHEMA)
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        seed(conn)
    return conn


def seed(conn):
    """Illustrative sample data so the admin dashboard looks alive."""
    rng = random.Random(42)
    conn.executemany("INSERT INTO users(name, role) VALUES (?,?)", USERS)
    conn.executemany("INSERT INTO resources(name, type, capacity) VALUES (?,?,?)",
                     [r[:3] for r in RESOURCES])
    people = [r[0] for r in conn.execute("SELECT id FROM users WHERE role!='admin'")]
    now, today = datetime.now(), date.today()
    for rid, (_, _, _, weight) in enumerate(RESOURCES, start=1):
        for off in range(-14, 4):
            day = today + timedelta(days=off)
            for h, p in HOUR_WEIGHT.items():
                if rng.random() > p * weight / 6:
                    continue
                start, end = f"{h:02d}:00", f"{h + 1:02d}:00"
                end_dt = datetime.strptime(f"{day} {end}", "%Y-%m-%d %H:%M")
                status, ci = "booked", None
                if end_dt <= now:
                    r = rng.random()
                    status = "checked_in" if r < .74 else "no_show" if r < .87 else "cancelled"
                    if status == "checked_in":
                        ci = f"{day} {start}"
                conn.execute(
                    "INSERT INTO bookings(resource_id,user_id,date,start_time,end_time,status,qr_token,checked_in_at)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    (rid, rng.choice(people), str(day), start, end, status,
                     f"{rng.getrandbits(32):08X}", ci))
    conn.commit()
