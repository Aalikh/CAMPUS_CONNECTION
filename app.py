"""CampusConnect - Smart Campus Resource Management System (hackathon prototype).
Run:  streamlit run app.py
"""
from datetime import date, datetime

import pandas as pd
import streamlit as st

import analytics
import db
import logic

st.set_page_config(page_title="CampusConnect", page_icon="🎓", layout="wide")
st.markdown("""<style>
h1,h2,h3{font-family:'Space Grotesk',sans-serif}
.tag{color:#22D3EE;font-weight:700;letter-spacing:2px;margin-top:-12px}
[data-testid="stMetric"]{background:#0B2150;border:1px solid rgba(34,211,238,.35);border-radius:16px;padding:14px 18px}
[data-testid="stMetricValue"]{color:#22D3EE}
</style>""", unsafe_allow_html=True)


@st.cache_resource
def get_conn():
    return db.get_conn()


conn = get_conn()
logic.release_no_shows(conn)  # auto-release unclaimed bookings on every page load

# ---------- sidebar: login + navigation ----------
users = pd.read_sql("SELECT * FROM users", conn)
st.sidebar.title("🎓 CampusConnect")
who = st.sidebar.selectbox("Sign in as", [f"{r.name} ({r.role})" for r in users.itertuples()])
user = users.iloc[[f"{r.name} ({r.role})" for r in users.itertuples()].index(who)]
pages = ["Find & Book", "My Bookings", "Check-in"] + (["Admin Dashboard"] if user["role"] == "admin" else [])
page = st.sidebar.radio("Go to", pages)
demo = st.sidebar.checkbox("Demo mode (skip check-in time window)", value=True)
st.sidebar.caption(f"No-show release: {logic.GRACE_MIN} min after start.")

st.title("CampusConnect")
st.markdown('<p class="tag">FIND. BOOK. USE. OPTIMIZE.</p>', unsafe_allow_html=True)


# ---------- helpers ----------
def do_book(rid, day, start, end):
    res = logic.create_booking(conn, rid, int(user["id"]), day, start, end)
    if res["ok"]:
        st.session_state.last = res
        st.session_state.pop("alts", None)
        st.rerun()
    st.error(res["msg"])
    if res.get("conflict"):
        others, slots = logic.alternatives(conn, rid, day, start, end)
        st.session_state.alts = dict(rid=rid, day=day, start=start, end=end, others=others, slots=slots)


def show_confirmation():
    b = st.session_state.last
    c1, c2 = st.columns([1, 2])
    c1.image(logic.make_qr(b["token"]), width=220)
    c2.success(f"Booking confirmed: {b['resource']}")
    c2.markdown(f"**Booking ID:** CC-{b['id']:04d}  \n**Check-in code:** `{b['token']}`  \n"
                f"**When:** {b['date']}, {b['start']}-{b['end']}")
    c2.caption("Show this QR / code at the venue and use the Check-in page.")


# ---------- pages ----------
def page_book():
    if "last" in st.session_state:
        show_confirmation()
        st.divider()
    st.subheader("Find & Book a Resource")
    now = datetime.now().strftime("%H:%M")
    i = next((k for k, s in enumerate(logic.SLOTS[:-2]) if s >= now), 2)
    c1, c2, c3, c4 = st.columns(4)
    day = str(c1.date_input("Date", value=date.today(), min_value=date.today()))
    start = c2.selectbox("Start", logic.SLOTS[:-1], index=i)
    end = c3.selectbox("End", logic.SLOTS[1:], index=min(i + 1, len(logic.SLOTS) - 2))
    rtype = c4.selectbox("Type", ["All", "classroom", "lab", "library", "study room", "seminar hall"])
    if end <= start:
        st.warning("End time must be after start time.")
        return
    df = logic.availability_table(conn, day, start, end, rtype)
    m1, m2, m3 = st.columns(3)
    m1.metric("Available", int((df["Status"] == "Available").sum()))
    m2.metric("Booked", int((df["Status"] == "Booked").sum()))
    m3.metric("In use", int((df["Status"] == "In use").sum()))
    st.dataframe(df.drop(columns="id").assign(
        Status=df["Status"].map({"Available": "🟢 Available", "Booked": "🔴 Booked", "In use": "🟠 In use"})),
        hide_index=True)
    ids = dict(zip(df["Resource"], df["id"]))
    pick = st.selectbox("Choose a resource", list(ids))
    if st.button("Confirm booking", type="primary"):
        do_book(int(ids[pick]), day, start, end)
    alts = st.session_state.get("alts")
    if alts:
        st.info("Smart suggestions: try one of these instead")
        for oid, oname in alts["others"]:
            if st.button(f"Book {oname} ({alts['start']}-{alts['end']})", key=f"ar{oid}"):
                do_book(int(oid), alts["day"], alts["start"], alts["end"])
        for s, e in alts["slots"]:
            if st.button(f"Same resource, {s}-{e}", key=f"as{s}"):
                do_book(int(alts["rid"]), alts["day"], s, e)
        if not alts["others"] and not alts["slots"]:
            st.write("No alternatives free at that time. Try another date.")


def page_mine():
    st.subheader("My Bookings")
    df = logic.user_bookings(conn, int(user["id"]))
    if df.empty:
        st.info("No bookings yet.")
        return
    st.dataframe(df.drop(columns="Token"), hide_index=True)
    active = df[df["Status"] == "booked"]
    if active.empty:
        return
    labels = {int(r.ID): f"CC-{r.ID:04d} · {r.Resource} · {r.Date} {r.Start}-{r.End}" for r in active.itertuples()}
    bid = st.selectbox("Select an active booking", list(labels), format_func=labels.get)
    token = active[active["ID"] == bid]["Token"].iloc[0]
    c1, c2 = st.columns([1, 2])
    c1.image(logic.make_qr(token), width=200)
    c2.markdown(f"**Check-in code:** `{token}`")
    if c2.button("Cancel this booking"):
        if logic.cancel_booking(conn, int(bid), int(user["id"])):
            st.success("Booking cancelled. The slot is free again.")
            st.rerun()


def page_checkin():
    st.subheader("QR Check-in")
    st.write("Enter the code from your QR (a scanner or phone camera can be added later).")
    token = st.text_input("Check-in code", max_chars=8)
    if st.button("Check in", type="primary") and token:
        ok, msg = logic.check_in(conn, token, demo)
        (st.success if ok else st.error)(msg)


def page_admin():
    st.subheader("Admin Dashboard")
    st.caption("Illustrative sample data (generated for the demo). Metrics are calculated live from the database.")
    df = analytics.load_df(conn)
    mt = analytics.metrics(df, conn)
    cols = st.columns(5)
    cols[0].metric("Total resources", mt["total"])
    cols[1].metric("Active bookings", mt["active"])
    cols[2].metric("Occupancy now", f"{mt['occupancy']}%")
    cols[3].metric("No-show rate", f"{mt['no_show']}%")
    cols[4].metric("Utilization", f"{mt['utilization']}%")
    if df.empty:
        return
    c1, c2, c3 = st.columns(3)
    c1.plotly_chart(analytics.peak_hours_fig(df), use_container_width=True)
    c2.plotly_chart(analytics.top_facilities_fig(df), use_container_width=True)
    c3.plotly_chart(analytics.underused_fig(df, conn), use_container_width=True)
    st.markdown("**Recent no-shows**")
    st.dataframe(df[df["status"] == "no_show"].sort_values("start_dt", ascending=False).head(8)[
        ["resource", "user", "date", "start_time", "end_time"]], hide_index=True)


{"Find & Book": page_book, "My Bookings": page_mine, "Check-in": page_checkin,
 "Admin Dashboard": page_admin}[page]()
