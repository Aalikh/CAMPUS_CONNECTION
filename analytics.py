"""Admin analytics with Pandas + Plotly."""
from datetime import datetime, date

import pandas as pd
import plotly.express as px

CYAN, OPEN_HOURS = "#22D3EE", 12  # resources are open 08:00-20:00


def load_df(conn):
    df = pd.read_sql(
        """SELECT b.*, r.name AS resource, r.type AS rtype, u.name AS user
           FROM bookings b JOIN resources r ON r.id=b.resource_id JOIN users u ON u.id=b.user_id""", conn)
    if df.empty:
        return df
    df["start_dt"] = pd.to_datetime(df["date"] + " " + df["start_time"])
    df["end_dt"] = pd.to_datetime(df["date"] + " " + df["end_time"])
    df["hours"] = (df["end_dt"] - df["start_dt"]).dt.total_seconds() / 3600
    return df


def _days(df):
    return max(1, (date.today() - pd.to_datetime(df["date"]).min().date()).days + 1)


def utilization(df, conn):
    names = pd.read_sql("SELECT name AS resource FROM resources", conn)
    used = df[df["status"] == "checked_in"].groupby("resource")["hours"].sum()
    out = names.set_index("resource").join(used.rename("used")).fillna(0)
    out["pct"] = (out["used"] / (OPEN_HOURS * _days(df)) * 100).round(1)
    return out.reset_index()


def metrics(df, conn):
    total = conn.execute("SELECT COUNT(*) FROM resources").fetchone()[0]
    now = pd.Timestamp(datetime.now())
    if df.empty:
        return dict(total=total, active=0, occupancy=0.0, no_show=0.0, utilization=0.0)
    live = df[df["status"].isin(["booked", "checked_in"])]
    now_busy = live[(live["start_dt"] <= now) & (live["end_dt"] > now)]["resource_id"].nunique()
    ci, ns = (df["status"] == "checked_in").sum(), (df["status"] == "no_show").sum()
    util = utilization(df, conn)["pct"].mean()
    return dict(total=total, active=int(((df["status"] == "booked") & (df["end_dt"] >= now)).sum()),
                occupancy=round(now_busy / total * 100, 1),
                no_show=round(ns / (ci + ns) * 100, 1) if ci + ns else 0.0,
                utilization=round(util, 1))


def _style(fig, title):
    fig.update_layout(title=title, template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)",
                      plot_bgcolor="rgba(0,0,0,0)", margin=dict(l=10, r=10, t=50, b=10),
                      showlegend=False, height=340)
    fig.update_traces(marker_color=CYAN)
    return fig


def peak_hours_fig(df):
    d = df[df["status"] != "cancelled"].copy()
    d["hour"] = d["start_time"].str[:2].astype(int)
    c = d.groupby("hour").size().reindex(range(8, 20), fill_value=0)
    fig = px.bar(x=[f"{h:02d}:00" for h in c.index], y=c.values, labels={"x": "Hour", "y": "Bookings"})
    return _style(fig, "Peak usage hours")


def top_facilities_fig(df):
    c = df[df["status"] != "cancelled"].groupby("resource").size().nlargest(6).sort_values()
    fig = px.bar(x=c.values, y=c.index, orientation="h", labels={"x": "Bookings", "y": ""})
    return _style(fig, "Most-used facilities")


def underused_fig(df, conn):
    u = utilization(df, conn).nsmallest(5, "pct").sort_values("pct", ascending=False)
    fig = px.bar(u, x="pct", y="resource", orientation="h", labels={"pct": "Utilization %", "resource": ""})
    return _style(fig, "Underutilized rooms")
