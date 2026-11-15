"""Booking rules: availability, double-booking prevention, alternatives, check-in, no-show release."""
import io
from datetime import datetime, timedelta
import uuid

import pandas as pd
import qrcode

GRACE_MIN = 10          # minutes after start before an unclaimed booking is released
CHECKIN_EARLY_MIN = 15  # check-in opens this long before start
SLOTS = [f"{h:02d}:{m:02d}" for h in range(8, 21) for m in (0, 30) if f"{h:02d}:{m:02d}" <= "20:00"]
CLOSE = "20:00"


def _dt(day, t):
    return datetime.strptime(f"{day} {t}", "%Y-%m-%d %H:%M")


def release_no_shows(conn, grace=GRACE_MIN):
    """Auto-release: booked slots nobody checked in to within `grace` minutes become no_show."""
    now = datetime.now()
    rows = conn.execute("SELECT id,date,start_time FROM bookings WHERE status='booked'").fetchall()
    ids = [r[0] for r in rows if _dt(r[1], r[2]) + timedelta(minutes=grace) < now]
    if ids:
        conn.execute(f"UPDATE bookings SET status='no_show' WHERE id IN ({','.join('?' * len(ids))})", ids)
        conn.commit()
    return len(ids)


def is_available(conn, rid, day, start, end):
    """Two bookings overlap when new_start < old_end AND new_end > old_start."""
    q = """SELECT COUNT(*) FROM bookings WHERE resource_id=? AND date=?
           AND status IN ('booked','checked_in') AND ? < end_time AND ? > start_time"""
    return conn.execute(q, (rid, day, start, end)).fetchone()[0] == 0


def availability_table(conn, day, start, end, rtype=None):
    q = """SELECT r.id AS id, r.name AS Resource, r.type AS Type, r.capacity AS Capacity,
           (SELECT b.status FROM bookings b WHERE b.resource_id=r.id AND b.date=?
              AND b.status IN ('booked','checked_in') AND ? < b.end_time AND ? > b.start_time LIMIT 1) AS st
           FROM resources r"""
    params = [day, start, end]
    if rtype and rtype != "All":
        q += " WHERE r.type=?"
        params.append(rtype)
    df = pd.read_sql(q + " ORDER BY r.type, r.name", conn, params=params)
    df["Status"] = df["st"].map({"booked": "Booked", "checked_in": "In use"}).fillna("Available")
    return df.drop(columns="st")


def resource_name(conn, rid):
    return conn.execute("SELECT name FROM resources WHERE id=?", (rid,)).fetchone()[0]


def create_booking(conn, rid, uid, day, start, end):
    if end <= start:
        return {"ok": False, "msg": "End time must be after start time."}
    if _dt(day, end) <= datetime.now():
        return {"ok": False, "msg": "That time has already passed."}
    if not is_available(conn, rid, day, start, end):
        return {"ok": False, "conflict": True,
                "msg": f"{resource_name(conn, rid)} is already booked for {start}-{end}."}
    token = uuid.uuid4().hex[:8].upper()
    cur = conn.execute(
        "INSERT INTO bookings(resource_id,user_id,date,start_time,end_time,status,qr_token) VALUES (?,?,?,?,?,'booked',?)",
        (rid, uid, day, start, end, token))
    conn.commit()
    return {"ok": True, "id": cur.lastrowid, "token": token, "resource": resource_name(conn, rid),
            "date": day, "start": start, "end": end}


def alternatives(conn, rid, day, start, end):
    """Other free resources of the same type, plus nearest free slots on the same resource."""
    rtype = conn.execute("SELECT type FROM resources WHERE id=?", (rid,)).fetchone()[0]
    others = [(r[0], r[1]) for r in conn.execute(
        "SELECT id,name FROM resources WHERE type=? AND id!=?", (rtype, rid))
        if is_available(conn, r[0], day, start, end)][:3]
    dur, now, close = _dt(day, end) - _dt(day, start), datetime.now(), _dt(day, CLOSE)
    slots = []
    for s in SLOTS:
        e_dt = _dt(day, s) + dur
        if s == start or e_dt > close or e_dt <= now:
            continue
        e = e_dt.strftime("%H:%M")
        if is_available(conn, rid, day, s, e):
            slots.append((s, e))
    slots.sort(key=lambda x: abs((_dt(day, x[0]) - _dt(day, start)).total_seconds()))
    return others, slots[:3]


def user_bookings(conn, uid):
    return pd.read_sql(
        """SELECT b.id AS ID, r.name AS Resource, b.date AS Date, b.start_time AS Start,
           b.end_time AS End, b.status AS Status, b.qr_token AS Token
           FROM bookings b JOIN resources r ON r.id=b.resource_id
           WHERE b.user_id=? ORDER BY b.date DESC, b.start_time DESC""", conn, params=(uid,))


def cancel_booking(conn, bid, uid):
    cur = conn.execute("UPDATE bookings SET status='cancelled' WHERE id=? AND user_id=? AND status='booked'",
                       (bid, uid))
    conn.commit()
    return cur.rowcount == 1


def check_in(conn, token, demo=False):
    """Returns (ok, message). demo=True skips the time-window rule so any booked token works."""
    row = conn.execute(
        """SELECT b.id,b.date,b.start_time,b.end_time,b.status,r.name FROM bookings b
           JOIN resources r ON r.id=b.resource_id WHERE b.qr_token=?""", (token.strip().upper(),)).fetchone()
    if not row:
        return False, "Booking code not found."
    bid, day, start, end, status, name = row
    if status == "checked_in":
        return False, f"Already checked in to {name}."
    if status == "no_show":
        return False, "This booking was released as a no-show."
    if status == "cancelled":
        return False, "This booking was cancelled."
    now = datetime.now()
    if not demo:
        if now < _dt(day, start) - timedelta(minutes=CHECKIN_EARLY_MIN):
            return False, f"Too early. Check-in opens {CHECKIN_EARLY_MIN} min before {start}."
        if now > _dt(day, end):
            return False, "This booking has already ended."
    conn.execute("UPDATE bookings SET status='checked_in', checked_in_at=? WHERE id=?",
                 (now.strftime("%Y-%m-%d %H:%M"), bid))
    conn.commit()
    return True, f"Checked in to {name} ({day} {start}-{end}). Resource status updated to In use."


def make_qr(token):
    buf = io.BytesIO()
    qrcode.make(token).save(buf, format="PNG")
    return buf.getvalue()
