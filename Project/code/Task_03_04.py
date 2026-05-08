# Task_03_04.py — Process Discovery, Interactive GUI, Analytics + Agentic AI
# pip install dash dash-cytoscape pandas
#
# FIX NOTES:
# 1. trip_id NOT prefixed with route_id (CSV already has globally unique trip IDs).
# 2. Timestamps parsed from ISO column — avoids negative durations on midnight-crossing.
# 3. Throughput table shows route-level aggregates AND per-trip schedule (Task 4a).
# 4. Min=Max=Avg is expected: CDA uses same schedule template for every departure.
# 5. Task 5 AI Agent handles 5 query types: trip planning, route lookup, departure
#    times, travel duration, and connectivity checks.
# 6. AI chat panel is a collapsible right sidebar — toggle button in header keeps
#    it off-screen until the user needs it.

import pandas as pd
import re
import datetime
import dash
from dash import dcc, html, Input, Output, State, callback_context
import dash_cytoscape as cyto
import collections
import os

# ═══════════════════════════════════════════════════════════════════════════════
# TASK 5 — AGENTIC AI ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

ALIASES = {
    "fast university": "FAST University",
    "fast uni":        "FAST University",
    "fast":            "FAST University",
    "nust":            "Nust Metro Station",
    "nust metro":      "Nust Metro Station",
    "pims":            "PIMS Hospital",
    "pims hospital":   "PIMS Hospital",
    "khanna":          "Khanna Pul",
    "khanna pul":      "Khanna Pul",
    "i10":             "PTCL I-10",
    "i-10":            "PTCL I-10",
    "ptcl":            "PTCL I-10",
    "h8":              "PAEC General Hospital",
    "h-8":             "PAEC General Hospital",
    "paec":            "PAEC General Hospital",
    "nori":            "NORI Hospital",
    "faizabad":        "Faizabad Metro Station",
    "faizabad metro":  "Faizabad Metro Station",
    "g9":              "G-9 Markaz",
    "g-9":             "G-9 Markaz",
    "g10":             "G-10 Markaz",
    "g-10":            "G-10 Markaz",
    "g11":             "G-11 Markaz",
    "g-11":            "G-11 Markaz",
    "g8":              "G-8 Markaz",
    "g-8":             "G-8 Markaz",
    "f7":              "F-7 Markaz",
    "f-7":             "F-7 Markaz",
    "f8":              "F-8 Markaz",
    "f-8":             "F-8 Markaz",
    "f9":              "F-9 Park",
    "f-9":             "F-9 Park",
    "f10":             "F-10 Markaz",
    "f-10":            "F-10 Markaz",
    "zero point":      "Zero Point",
    "abpara":          "Abpara Market",
    "police foundation": "Police Foundation Metro",
    "eme":             "NUST EME College",
    "comsats":         "COMSATS University",
    "bahria":          "Bahria University",
    "islamic uni":     "Islamic University",
}


def _fuzzy_stop(term, all_stops):
    """Return best matching stop name for a search term, or None."""
    t = term.strip().lower()
    if not t:
        return None
    # Check aliases (longest alias first to avoid partial hits)
    for alias in sorted(ALIASES.keys(), key=len, reverse=True):
        if alias in t:
            return ALIASES[alias]
    # Exact match
    for s in all_stops:
        if s.lower() == t:
            return s
    # Stop name is substring of query
    for s in sorted(all_stops, key=len, reverse=True):
        if s.lower() in t:
            return s
    # Query word is substring of stop name
    for s in sorted(all_stops, key=len):
        if t in s.lower():
            return s
    # Token-level partial match (any query token len>3 in stop name)
    tokens = [w for w in t.split() if len(w) > 3]
    for s in sorted(all_stops, key=len):
        if any(tok in s.lower() for tok in tokens):
            return s
    return None


def _extract_two_stops(text, all_stops):
    """Pull (src, dst) from 'from X to Y' or positional fallback."""
    t = text.lower()
    src = dst = None

    if "from" in t and "to" in t:
        try:
            after_from = t.split("from", 1)[1]
            if "to" in after_from:
                from_part = after_from.split("to", 1)[0]
                to_part   = after_from.split("to", 1)[1].split("?")[0]
                src = _fuzzy_stop(from_part, all_stops)
                dst = _fuzzy_stop(to_part,   all_stops)
        except Exception:
            pass

    # Fallback: scan full text for any two stop mentions
    if not src or not dst:
        hits = []
        for alias in sorted(ALIASES.keys(), key=len, reverse=True):
            idx = t.find(alias)
            if idx != -1:
                hits.append((idx, ALIASES[alias]))
        for s in sorted(all_stops, key=len, reverse=True):
            idx = t.find(s.lower())
            if idx != -1:
                hits.append((idx, s))
        hits.sort(key=lambda x: x[0])
        seen, unique = set(), []
        for _, s in hits:
            if s not in seen:
                seen.add(s)
                unique.append(s)
        if len(unique) >= 2:
            src = unique[0]
            dst = unique[1]

    return src, dst


def _detect_intent(text):
    t = text.lower()
    if any(kw in t for kw in [
        "which route", "what route", "what bus", "which bus",
        "goes through", "pass through", "routes through",
        "serve", "stops at", "stop at"
    ]):
        return "route_through"
    if any(kw in t for kw in [
        "what time", "when does", "when do", "next bus",
        "last bus", "first bus", "departs", "leaves from",
        "departure", "schedule", "timing"
    ]):
        return "departure_time"
    if any(kw in t for kw in [
        "how long", "how much time", "travel time",
        "takes to", "time does it", "duration", "minutes to"
    ]):
        return "travel_time"
    if any(kw in t for kw in [
        "connect", "do any routes", "is there a route",
        "any bus between", "can i get", "is there a bus"
    ]):
        return "connectivity"
    if any(kw in t for kw in [
        "from", "to", "how do i get", "options", "travel to",
        "go to", "reach", "i have to", "i want to", "i need to",
        "way to", "get to"
    ]):
        return "trip_plan"
    return "unknown"


def _handle_route_through(text, current_df, all_stops):
    # Try to extract the stop from after keywords
    t = text.lower()
    stop = None
    for kw in ["through ", "via ", "serves ", "stops at ", "at ", "for "]:
        if kw in t:
            candidate = t.split(kw, 1)[-1].strip().split("?")[0].strip()
            stop = _fuzzy_stop(candidate, all_stops)
            if stop:
                break
    if not stop:
        stop = _fuzzy_stop(t, all_stops)
    if not stop:
        return ("**Agent:** I couldn't identify which stop you're asking about. "
                "Try: *'Which route goes through Faizabad Metro Station?'*")

    routes = sorted(current_df[current_df["stop_name"] == stop]["route_id"].unique().tolist())
    if not routes:
        return f"**Agent:** No routes found serving **{stop}** in the dataset."

    routes_str = ", ".join([f"**{r}**" for r in routes])
    trips_total = current_df[current_df["stop_name"] == stop]["trip_id"].nunique()
    return (f"**Agent:** The stop **{stop}** is served by: {routes_str}  \n"
            f"A total of **{trips_total}** scheduled trips pass through this stop.")


def _handle_departure_time(text, current_df, all_stops):
    t = text.lower()
    stop = None
    for kw in ["from ", "at ", "leave from ", "depart from "]:
        if kw in t:
            candidate = t.split(kw, 1)[-1].strip().split("?")[0].strip()
            stop = _fuzzy_stop(candidate, all_stops)
            if stop:
                break
    if not stop:
        stop = _fuzzy_stop(t, all_stops)
    if not stop:
        return ("**Agent:** Please specify a stop name. "
                "E.g. *'What time does the last bus leave from PTCL I-10?'*")

    rows  = current_df[current_df["stop_name"] == stop]
    times = sorted(rows["departure_time"].dropna().str[:5].unique().tolist())
    if not times:
        return f"**Agent:** No departure times found for **{stop}**."

    if "last" in t:
        return (f"**Agent:** The **last departure** from **{stop}** is at **{times[-1]}**.  \n"
                f"This stop has {len(times)} scheduled departures throughout the day.")
    if "first" in t or "next" in t or "earliest" in t:
        return (f"**Agent:** The **first departure** from **{stop}** is at **{times[0]}**.  \n"
                f"This stop has {len(times)} scheduled departures throughout the day.")

    shown = times[:10]
    more  = f" *(+{len(times)-10} more)*" if len(times) > 10 else ""
    routes = sorted(rows["route_id"].unique().tolist())
    return (f"**Agent:** Departures from **{stop}** (routes: {', '.join(routes)}):  \n"
            f"{', '.join(shown)}{more}")


def _handle_travel_time(text, current_df, edges_df, all_stops):
    src, dst = _extract_two_stops(text, all_stops)
    if not src or not dst:
        return ("**Agent:** Please specify both stops. "
                "E.g. *'How long does it take from Khanna Pul to Faizabad?'*")
    if src == dst:
        return f"**Agent:** You are already at **{src}**!"
    return find_trip_plan(src, dst, current_df, edges_df)


def _handle_connectivity(text, current_df, edges_df, all_stops):
    src, dst = _extract_two_stops(text, all_stops)
    if not src or not dst:
        return ("**Agent:** Please name two stops. "
                "E.g. *'Do any routes connect G-9 Markaz to F-8 Markaz?'*")
    result = find_trip_plan(src, dst, current_df, edges_df)
    if "couldn't find" in result.lower():
        return (f"**Agent:** No direct or connecting bus route was found between "
                f"**{src}** and **{dst}** in the current CDA dataset.")
    return result.replace(
        "I found a route",
        f"Yes — there is a connection between **{src}** and **{dst}**. Here's how"
    )


def _bfs_path(start_stop, end_stop, edges_df_arg):
    """
    Raw BFS — returns list of (src, tgt, route_id, dur_sec, direction) or None.
    Builds a bidirectional graph so return trips can be planned even though
    the CDA PDFs only publish the forward schedule.
    """
    adj = collections.defaultdict(list)
    for _, row in edges_df_arg.drop_duplicates(["src", "tgt", "route_id"]).iterrows():
        adj[row["src"]].append((row["tgt"], row["route_id"], row["dur_sec"], "forward"))
        adj[row["tgt"]].append((row["src"], row["route_id"], row["dur_sec"], "reverse"))

    queue   = collections.deque([(start_stop, [])])
    visited = {start_stop}
    while queue:
        curr, path = queue.popleft()
        if curr == end_stop:
            return path
        for tgt, rid, dur, direction in adj.get(curr, []):
            if tgt not in visited:
                visited.add(tgt)
                queue.append((tgt, path + [(curr, tgt, rid, dur, direction)]))
    return None


def find_trip_plan(start_stop, end_stop, current_df, edges_df_arg):
    """
    BFS trip planner with departure-time grounding.
    Response format matches the project spec example:
      'Route X stops at [start] (dep. HH:MM) and reaches [end] in ~N min.
       Next departure: HH:MM'
    """
    start_stop = start_stop.strip()
    end_stop   = end_stop.strip()

    path = _bfs_path(start_stop, end_stop, edges_df_arg)
    if path is None:
        return (f"**Agent:** Sorry, I couldn't find a direct or connecting bus route "
                f"between **{start_stop}** and **{end_stop}** in the current CDA dataset.")

    total      = sum(dur for _, _, _, dur, _ in path)
    first_rid  = path[0][2]

    # Departure times from start stop on the first route used
    dep_rows = current_df[
        (current_df["stop_name"] == start_stop) &
        (current_df["route_id"]  == first_rid)
    ]["departure_time"].dropna().str[:5].unique()
    dep_times = sorted(dep_rows.tolist())

    # "Next departure" — first scheduled time >= current clock time
    now_str  = datetime.datetime.now().strftime("%H:%M")
    next_dep = next((t for t in dep_times if t >= now_str), dep_times[0] if dep_times else None)
    first_dep = dep_times[0]  if dep_times else "N/A"
    last_dep  = dep_times[-1] if dep_times else "N/A"

    # Build step-by-step legs (collapse consecutive same-route hops)
    legs, leg_rid, leg_dir = [], path[0][2], path[0][4]
    leg_start, leg_end, leg_dur = path[0][0], path[0][1], path[0][3]
    for src, tgt, rid, dur, direction in path[1:]:
        if rid == leg_rid and direction == leg_dir:
            leg_end  = tgt
            leg_dur += dur
        else:
            legs.append((leg_start, leg_end, leg_rid, leg_dir, leg_dur))
            leg_rid, leg_dir = rid, direction
            leg_start, leg_end, leg_dur = src, tgt, dur
    legs.append((leg_start, leg_end, leg_rid, leg_dir, leg_dur))

    resp = (f"**Agent:** Based on the current schedule, "
            f"**Route {first_rid}** stops at **{start_stop}** "
            f"(dep. {first_dep}) and reaches **{end_stop}** "
            f"in approximately **{int(total // 60)} min** (avg).\n\n")

    if len(legs) == 1:
        ls, le, rid, direction, dur = legs[0]
        d_label = "Forward" if direction == "forward" else "Return"
        resp += f"Direct — **{rid}** ({d_label}): *{ls}* → *{le}* (~{int(dur//60)}m {int(dur%60)}s)\n"
    else:
        for i, (ls, le, rid, direction, dur) in enumerate(legs, 1):
            d_label = "Forward" if direction == "forward" else "Return"
            resp   += (f"{i}. **{rid}** ({d_label}): *{ls}* → *{le}* "
                       f"(~{int(dur//60)}m {int(dur%60)}s)\n")

    resp += (f"\n**Total travel time: ~{int(total//60)} min {int(total%60)} sec**  \n"
             f"Departures from **{start_stop}**: {first_dep} — {last_dep}  \n"
             f"**Next departure: {next_dep}**")
    return resp


def ai_agent_query(user_text, current_df, edges_df):
    """
    Entry point for the chat panel. Detects intent and dispatches
    to the appropriate handler. Handles 5 query types:
      1. route_through  — which routes serve stop X
      2. departure_time — what time does bus leave from X
      3. travel_time    — how long from X to Y
      4. connectivity   — do any routes connect X to Y
      5. trip_plan      — how do I get from X to Y (step-by-step)
    """
    t         = user_text.strip()
    all_stops = current_df["stop_name"].unique()
    intent    = _detect_intent(t.lower())

    if intent == "route_through":
        return _handle_route_through(t, current_df, all_stops)
    if intent == "departure_time":
        return _handle_departure_time(t, current_df, all_stops)
    if intent == "travel_time":
        return _handle_travel_time(t, current_df, edges_df, all_stops)
    if intent == "connectivity":
        return _handle_connectivity(t, current_df, edges_df, all_stops)
    if intent == "trip_plan":
        src, dst = _extract_two_stops(t, all_stops)
        if src and dst:
            if src == dst:
                return f"**Agent:** You are already at **{src}**!"
            return find_trip_plan(src, dst, current_df, edges_df)

    return (
        "**Agent:** Hi! I am your CDA Trip Assistant. Here are some things you can ask:\n\n"
        "- *How do I get from Khanna Pul to FAST University?*\n"
        "- *Which route goes through Faizabad?*\n"
        "- *What time does the last bus leave from PTCL I-10?*\n"
        "- *How long does it take from G-9 Markaz to NUST Metro Station?*\n"
        "- *Do any routes connect Abpara to Zero Point?*"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 1.  LOAD & PREPARE DATA
# ═══════════════════════════════════════════════════════════════════════════════
cyto.load_extra_layouts()

BASE_DIR  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_CSV = os.path.join(BASE_DIR, "data", "routes_clean.csv")

df = pd.read_csv(INPUT_CSV)
df.columns = df.columns.str.strip()

df["trip_id"]       = df["trip_id"].astype(str).str.strip()
df["stop_name"]     = df["stop_name"].astype(str).str.strip()
df["route_id"]      = df["route_id"].astype(str).str.strip()
df["stop_sequence"] = pd.to_numeric(df["stop_sequence"], errors="coerce")

df["ts_arrival"] = pd.to_datetime(df["time:timestamp"], utc=False, errors="coerce")


def _parse_hms(s):
    s = str(s).strip()
    m = re.match(r"(\d{1,2}):(\d{2}):(\d{2})", s)
    if m:
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
    return None


df["_arr_sec"]   = df["arrival_time"].apply(_parse_hms)
df["_dep_sec"]   = df["departure_time"].apply(_parse_hms)
df["_dwell_sec"] = (df["_dep_sec"] - df["_arr_sec"]).clip(lower=0)
df["ts_departure"] = df["ts_arrival"] + pd.to_timedelta(df["_dwell_sec"], unit="s")

df = df.dropna(subset=["ts_arrival", "ts_departure", "stop_name", "trip_id"])
df = df.sort_values(["trip_id", "stop_sequence"]).reset_index(drop=True)

print(f"Loaded: {len(df)} rows | {df['trip_id'].nunique()} trips | {df['route_id'].nunique()} routes")
print(f"Routes: {sorted(df['route_id'].unique())}")

# ═══════════════════════════════════════════════════════════════════════════════
# 2.  BUILD EDGE TABLE
# ═══════════════════════════════════════════════════════════════════════════════
records = []
for trip_id, group in df.groupby("trip_id", sort=False):
    group    = group.sort_values("stop_sequence").reset_index(drop=True)
    route_id = group["route_id"].iloc[0]
    for i in range(len(group) - 1):
        src      = group.loc[i,   "stop_name"]
        tgt      = group.loc[i+1, "stop_name"]
        t_depart = group.loc[i,   "ts_departure"]
        t_arrive = group.loc[i+1, "ts_arrival"]
        dur_sec  = (t_arrive - t_depart).total_seconds()
        records.append({"route_id": route_id, "trip_id": trip_id,
                        "src": src, "tgt": tgt, "dur_sec": max(0, dur_sec)})

edges_df = pd.DataFrame(records)

agg = (
    edges_df
    .groupby(["route_id", "src", "tgt"])
    .agg(freq=("trip_id", "nunique"), avg_sec=("dur_sec", "mean"),
         min_sec=("dur_sec", "min"), max_sec=("dur_sec", "max"))
    .reset_index()
)


def fmt_duration(seconds):
    seconds = max(0, int(round(seconds)))
    m, s = divmod(seconds, 60)
    if m == 0:
        return f"{s} sec"
    h, m = divmod(m, 60)
    if h == 0:
        return f"{m} min {s} sec"
    return f"{h} hr {m} min {s} sec"


agg["dur_label"] = agg["avg_sec"].apply(fmt_duration)
print(f"Edge table: {len(agg)} unique transitions")

# ═══════════════════════════════════════════════════════════════════════════════
# 3.  THROUGHPUT PER TRIP  (Task 4a)
# ═══════════════════════════════════════════════════════════════════════════════
tp_records = []
for (route_id, trip_id), group in df.groupby(["route_id", "trip_id"]):
    group        = group.sort_values("stop_sequence")
    first_arrive = group["ts_arrival"].iloc[0]
    last_depart  = group["ts_departure"].iloc[-1]
    duration_sec = max(0, (last_depart - first_arrive).total_seconds())
    tp_records.append({
        "route_id": route_id, "trip_id": trip_id,
        "duration_sec": duration_sec,
        "first_stop":   group["stop_name"].iloc[0],
        "last_stop":    group["stop_name"].iloc[-1],
        "first_clock":  group["arrival_time"].iloc[0][:5],
        "last_clock":   group["departure_time"].iloc[-1][:5],
        "num_stops":    len(group),
    })

throughput_df = pd.DataFrame(tp_records).sort_values(
    ["route_id", "first_clock"]).reset_index(drop=True)

route_throughput = (
    throughput_df.groupby("route_id")["duration_sec"]
    .agg(avg_sec="mean", min_sec="min", max_sec="max", trips="count")
    .reset_index()
)

# ═══════════════════════════════════════════════════════════════════════════════
# 4.  BOTTLENECK THRESHOLD  (Task 4b)
# ═══════════════════════════════════════════════════════════════════════════════
GLOBAL_MEAN = agg["avg_sec"].mean()
GLOBAL_STD  = agg["avg_sec"].std()
DEFAULT_THRESHOLD_SEC = int(GLOBAL_MEAN + GLOBAL_STD)

# ═══════════════════════════════════════════════════════════════════════════════
# 5.  COLOURS & ELEMENT BUILDER
# ═══════════════════════════════════════════════════════════════════════════════
ROUTE_COLOURS = {
    "FR-01":  "#e6194b", "FR-03A": "#3cb44b", "FR-04":  "#ffe119",
    "FR-07":  "#4363d8", "FR-08A": "#f58231", "FR-08C": "#42d4f4",
    "FR-09":  "#911eb4", "FR-11":  "#f032e6", "FR-15":  "#bfef45",
    "FRG-1":  "#a9a9a9",
}
DEFAULT_COLOUR = "#aaaaaa"

# ── Task 6: Member data ───────────────────────────────────────────────────────
MEMBERS = [
    {"label": "Member 1 — I-10",       "value": "m1", "name": "Member 1", "address": "Street 15, I-10/4, Islamabad",          "area": "I-10 Sector",   "stop": "PTCL I-10"},
    {"label": "Member 2 — Khanna Pul", "value": "m2", "name": "Member 2", "address": "Near Khanna Pul Interchange, Islamabad", "area": "Khanna Pul",    "stop": "Khanna Pul"},
    {"label": "Member 3 — H-8",        "value": "m3", "name": "Member 3", "address": "House 7, Street 4, H-8/4, Islamabad",   "area": "H-8 Sector",    "stop": "PAEC General Hospital"},
    {"label": "Member 4 — H-8",        "value": "m4", "name": "Member 4", "address": "House 22, H-8/1, Islamabad",            "area": "H-8 Sector",    "stop": "NORI Hospital"},
]

T6_STYLESHEET = [
    {"selector": "node", "style": {
        "label": "data(label)", "background-color": "#2a2a2a",
        "color": "#555", "text-outline-color": "#000", "text-outline-width": "1px",
        "font-size": "8px", "width": "18px", "height": "18px",
        "text-valign": "bottom", "text-halign": "center", "text-margin-y": "4px",
    }},
    {"selector": ".path-node", "style": {
        "background-color": "data(colour)", "color": "#fff",
        "text-outline-color": "#111", "text-outline-width": "2px",
        "font-size": "10px", "width": "28px", "height": "28px",
    }},
    {"selector": ".start-node", "style": {
        "background-color": "#00e676", "color": "#000",
        "text-outline-color": "#003300", "text-outline-width": "2px",
        "border-width": "3px", "border-color": "#ffffff",
        "font-size": "11px", "width": "38px", "height": "38px",
    }},
    {"selector": ".end-node", "style": {
        "background-color": "#e94560", "color": "#fff",
        "text-outline-color": "#550000", "text-outline-width": "2px",
        "border-width": "3px", "border-color": "#FFD700",
        "font-size": "11px", "width": "38px", "height": "38px",
    }},
    {"selector": "edge", "style": {
        "line-color": "#2a2a2a", "target-arrow-color": "#2a2a2a",
        "target-arrow-shape": "triangle", "curve-style": "bezier",
        "opacity": 0.25, "width": 1,
    }},
    {"selector": ".path-edge", "style": {
        "line-color": "data(colour)", "target-arrow-color": "data(colour)",
        "target-arrow-shape": "triangle", "curve-style": "bezier",
        "width": 6, "opacity": 1.0,
        "label": "data(label)", "font-size": "9px", "color": "#fff",
        "text-background-color": "#000", "text-background-opacity": 0.75,
        "text-background-padding": "2px", "text-rotation": "autorotate",
    }},
]


def build_member_path_elements(member_stop):
    """Build Cytoscape elements for Task 6 with the member's path highlighted."""
    target = "FAST University"
    path   = _bfs_path(member_stop, target, edges_df)
    if not path:
        return [], []

    path_edge_set = {(src, tgt) for src, tgt, _, _, _ in path}
    path_stop_set = {member_stop, target}
    for src, tgt, _, _, _ in path:
        path_stop_set.add(src)
        path_stop_set.add(tgt)

    routes_used = {rid for _, _, rid, _, _ in path}
    subset      = agg[agg["route_id"].isin(routes_used)]
    all_stops   = pd.concat([subset["src"], subset["tgt"]]).unique()

    # Build leg summary for info card
    legs, leg_rid, leg_dir = [], path[0][2], path[0][4]
    leg_start, leg_end, leg_dur = path[0][0], path[0][1], path[0][3]
    for src, tgt, rid, dur, direction in path[1:]:
        if rid == leg_rid and direction == leg_dir:
            leg_end = tgt; leg_dur += dur
        else:
            legs.append((leg_start, leg_end, leg_rid, leg_dir, leg_dur))
            leg_rid, leg_dir = rid, direction
            leg_start, leg_end, leg_dur = src, tgt, dur
    legs.append((leg_start, leg_end, leg_rid, leg_dir, leg_dur))

    stop_colour = {}
    for _, row in subset.iterrows():
        stop_colour.setdefault(row["src"], ROUTE_COLOURS.get(row["route_id"], DEFAULT_COLOUR))
        stop_colour.setdefault(row["tgt"], ROUTE_COLOURS.get(row["route_id"], DEFAULT_COLOUR))

    nodes = []
    for stop in all_stops:
        cls    = ("end-node"   if stop == target      else
                  "start-node" if stop == member_stop else
                  "path-node"  if stop in path_stop_set else "")
        colour = stop_colour.get(stop, DEFAULT_COLOUR)
        nodes.append({"data": {"id": stop, "label": stop, "colour": colour}, "classes": cls})

    edges = []
    for _, row in subset.iterrows():
        in_path = ((row["src"], row["tgt"]) in path_edge_set or
                   (row["tgt"], row["src"]) in path_edge_set)
        colour  = ROUTE_COLOURS.get(row["route_id"], DEFAULT_COLOUR) if in_path else "#2a2a2a"
        edges.append({"data": {
            "id":       f"{row['route_id']}__{row['src']}__{row['tgt']}",
            "source":   row["src"], "target": row["tgt"],
            "route_id": row["route_id"],
            "label":    f"{row['route_id']} — {row['dur_label']}" if in_path else "",
            "colour":   colour,
        }, "classes": "path-edge" if in_path else ""})

    return nodes + edges, legs


def build_elements(selected_route, threshold_sec):
    subset = (agg.copy() if selected_route == "ALL"
              else agg[agg["route_id"] == selected_route].copy())
    all_stops   = pd.concat([subset["src"], subset["tgt"]]).unique()
    stop_routes = {}
    for _, row in subset.iterrows():
        stop_routes.setdefault(row["src"], set()).add(row["route_id"])
        stop_routes.setdefault(row["tgt"], set()).add(row["route_id"])

    nodes = []
    for stop in all_stops:
        routes_here = stop_routes.get(stop, set())
        colour      = ROUTE_COLOURS.get(next(iter(routes_here)), DEFAULT_COLOUR)
        nodes.append({"data": {"id": stop, "label": stop,
                               "routes": ", ".join(sorted(routes_here)),
                               "colour": colour}})
    edges = []
    for _, row in subset.iterrows():
        is_bn       = row["avg_sec"] >= threshold_sec
        edge_colour = "#ff0000" if is_bn else ROUTE_COLOURS.get(row["route_id"], DEFAULT_COLOUR)
        edges.append({"data": {
            "id":       f"{row['route_id']}__{row['src']}__{row['tgt']}",
            "source":   row["src"], "target": row["tgt"],
            "route_id": row["route_id"],
            "label":    f"{row['dur_label']} | {int(row['freq'])} trips",
            "freq":     int(row["freq"]),
            "avg_sec":  round(row["avg_sec"], 1),
            "min_sec":  int(row["min_sec"]), "max_sec": int(row["max_sec"]),
            "colour":   edge_colour, "dur_label": row["dur_label"], "is_bn": is_bn,
        }, "classes": "bottleneck" if is_bn else ""})

    return nodes + edges


# ═══════════════════════════════════════════════════════════════════════════════
# 6.  PANEL / TABLE BUILDERS
# ═══════════════════════════════════════════════════════════════════════════════
def _build_legend():
    items = []
    for route in sorted(df["route_id"].unique()):
        colour = ROUTE_COLOURS.get(route, DEFAULT_COLOUR)
        items.append(html.Div(style={"display": "flex", "alignItems": "center", "marginBottom": "5px"}, children=[
            html.Div(style={"width": "14px", "height": "14px", "backgroundColor": colour,
                            "borderRadius": "3px", "marginRight": "8px", "flexShrink": "0"}),
            html.Span(route, style={"color": "#cccccc", "fontSize": "12px"})
        ]))
    items.append(html.Div(style={"display": "flex", "alignItems": "center", "marginTop": "6px"}, children=[
        html.Div(style={"width": "24px", "height": "3px",
                        "background": "repeating-linear-gradient(90deg,#ff0000 0,#ff0000 6px,transparent 6px,transparent 10px)",
                        "marginRight": "8px"}),
        html.Span("Bottleneck edge", style={"color": "#ff8888", "fontSize": "11px"})
    ]))
    return items


def _detail_row(label, value, value_colour="#e0e0e0"):
    return html.Div(style={"display": "flex", "justifyContent": "space-between",
                           "marginBottom": "6px", "borderBottom": "1px solid #0f3460",
                           "paddingBottom": "4px"}, children=[
        html.Span(label + ":", style={"color": "#888888", "fontSize": "12px"}),
        html.Span(str(value), style={"color": value_colour, "fontWeight": "bold",
                                     "fontSize": "12px", "textAlign": "right",
                                     "maxWidth": "170px", "wordBreak": "break-word"}),
    ])


def _default_panel():
    return [
        html.H4("ℹ Click a node or edge",
                style={"color": "#e94560", "marginTop": 0, "fontSize": "14px"}),
        html.P("Select any element to see details.",
               style={"color": "#888888", "fontSize": "12px"}),
        html.Hr(style={"borderColor": "#0f3460"}),
        html.H5("Legend", style={"color": "#e94560", "fontSize": "13px"}),
        html.Div(_build_legend()),
    ]


def _throughput_table(selected_route):
    tp_route = (route_throughput if selected_route == "ALL"
                else route_throughput[route_throughput["route_id"] == selected_route])
    tp_cases = (throughput_df if selected_route == "ALL"
                else throughput_df[throughput_df["route_id"] == selected_route])

    th_style = {"color": "#e94560", "padding": "4px 8px",
                "borderBottom": "1px solid #0f3460",
                "fontSize": "11px", "textAlign": "left", "whiteSpace": "nowrap"}
    route_rows = [html.Tr([html.Th(c, style=th_style) for c in ["Route", "Avg", "Min", "Max", "# Trips"]])]

    for _, r in tp_route.iterrows():
        colour = ROUTE_COLOURS.get(r["route_id"], DEFAULT_COLOUR)
        route_rows.append(html.Tr([
            html.Td(r["route_id"],                style={"color": colour, "fontWeight": "bold", "padding": "3px 8px", "fontSize": "11px"}),
            html.Td(fmt_duration(r["avg_sec"]),   style={"color": "#fbbf24", "padding": "3px 8px", "fontSize": "11px"}),
            html.Td(fmt_duration(r["min_sec"]),   style={"color": "#4ade80", "padding": "3px 8px", "fontSize": "11px"}),
            html.Td(fmt_duration(r["max_sec"]),   style={"color": "#f87171", "padding": "3px 8px", "fontSize": "11px"}),
            html.Td(str(int(r["trips"])),          style={"color": "#ccc",    "padding": "3px 8px", "fontSize": "11px"}),
        ]))

    overall_min   = route_throughput["min_sec"].min()
    overall_max   = route_throughput["max_sec"].max()
    overall_avg   = throughput_df["duration_sec"].mean()
    overall_trips = int(throughput_df["trip_id"].nunique())
    route_rows.append(html.Tr([html.Td("─"*6, style={"padding": "0 8px", "fontSize": "9px", "color": "#333"})] * 5))
    route_rows.append(html.Tr(style={"backgroundColor": "#0f2040"}, children=[
        html.Td("ALL ROUTES",              style={"color": "#e94560", "fontWeight": "bold", "padding": "4px 8px", "fontSize": "11px", "borderTop": "2px solid #e94560"}),
        html.Td(fmt_duration(overall_avg), style={"color": "#fbbf24", "fontWeight": "bold", "padding": "4px 8px", "fontSize": "11px", "borderTop": "2px solid #e94560"}),
        html.Td(fmt_duration(overall_min), style={"color": "#4ade80", "fontWeight": "bold", "padding": "4px 8px", "fontSize": "11px", "borderTop": "2px solid #e94560"}),
        html.Td(fmt_duration(overall_max), style={"color": "#f87171", "fontWeight": "bold", "padding": "4px 8px", "fontSize": "11px", "borderTop": "2px solid #e94560"}),
        html.Td(str(overall_trips),        style={"color": "#ccc",    "fontWeight": "bold", "padding": "4px 8px", "fontSize": "11px", "borderTop": "2px solid #e94560"}),
    ]))

    th2 = dict(th_style, fontSize="10px")
    case_rows = [html.Tr([html.Th(c, style=th2) for c in ["Route", "Departs", "Arrives", "Duration", "Stops"]])]
    for _, r in tp_cases.iterrows():
        colour = ROUTE_COLOURS.get(r["route_id"], DEFAULT_COLOUR)
        case_rows.append(html.Tr([
            html.Td(r["route_id"],                     style={"color": colour, "fontWeight": "bold", "padding": "2px 8px", "fontSize": "10px"}),
            html.Td(r["first_clock"],                  style={"color": "#60a5fa", "padding": "2px 8px", "fontSize": "10px"}),
            html.Td(r["last_clock"],                   style={"color": "#34d399", "padding": "2px 8px", "fontSize": "10px"}),
            html.Td(fmt_duration(r["duration_sec"]),   style={"color": "#fbbf24", "padding": "2px 8px", "fontSize": "10px", "whiteSpace": "nowrap"}),
            html.Td(str(int(r["num_stops"])),           style={"color": "#ccc",    "padding": "2px 8px", "fontSize": "10px"}),
        ]))

    return html.Div([
        html.H5("⏱ Throughput Time per Trip  (Task 4a)",
                style={"color": "#e94560", "marginTop": 0, "marginBottom": "4px", "fontSize": "13px"}),
        html.P("Formula: T_total = t_last_departure − t_first_arrival",
               style={"color": "#666", "fontSize": "9px", "marginTop": 0, "marginBottom": "6px"}),
        html.Table(route_rows, style={"borderCollapse": "collapse", "marginBottom": "6px"}),
        html.H6("📋 Per-Trip Schedule (each case)",
                style={"color": "#aaa", "fontSize": "11px", "margin": "8px 0 4px 0"}),
        html.Div(html.Table(case_rows, style={"borderCollapse": "collapse"}),
                 style={"maxHeight": "180px", "overflowY": "auto",
                        "border": "1px solid #0f3460", "borderRadius": "4px"}),
    ], style={"marginRight": "30px", "minWidth": "350px"})


def _bottleneck_panel(selected_route, threshold_sec):
    subset = (agg if selected_route == "ALL"
              else agg[agg["route_id"] == selected_route])
    top3 = subset.sort_values("avg_sec", ascending=False).head(3)
    bn   = subset[subset["avg_sec"] >= threshold_sec]
    items = []
    for rank, (_, r) in enumerate(top3.iterrows(), 1):
        colour = ROUTE_COLOURS.get(r["route_id"], DEFAULT_COLOUR)
        medal  = ["🥇", "🥈", "🥉"][rank - 1]
        is_bn  = r["avg_sec"] >= threshold_sec
        items.append(html.Div(style={
            "backgroundColor": "#1a0000" if is_bn else "#0d1b2a",
            "border":          f"1px solid {'#ff4444' if is_bn else '#0f3460'}",
            "borderLeft":      f"5px solid {colour}",
            "borderRadius":    "6px", "padding": "8px 12px", "marginBottom": "8px",
        }, children=[
            html.Div(f"{medal}  #{rank}  {r['src']}  →  {r['tgt']}" + (" 🚨" if is_bn else ""),
                     style={"color": "#ff8888" if is_bn else "#ccc", "fontWeight": "bold", "fontSize": "12px"}),
            html.Div(style={"display": "flex", "gap": "12px", "marginTop": "4px", "flexWrap": "wrap"}, children=[
                html.Span(f"Avg: {fmt_duration(r['avg_sec'])}", style={"color": "#fca5a5" if is_bn else "#fbbf24", "fontSize": "11px", "fontWeight": "bold"}),
                html.Span(f"Min: {fmt_duration(r['min_sec'])}", style={"color": "#4ade80", "fontSize": "11px"}),
                html.Span(f"Max: {fmt_duration(r['max_sec'])}", style={"color": "#f87171", "fontSize": "11px"}),
            ]),
            html.Div(f"{int(r['freq'])} trips  |  Route: {r['route_id']}",
                     style={"color": "#888", "fontSize": "10px", "marginTop": "3px"}),
        ]))
    return html.Div([
        html.H5("🚨 Top-3 Bottleneck Transitions  (Task 4b)",
                style={"color": "#ff6666", "marginTop": 0, "marginBottom": "2px", "fontSize": "13px"}),
        html.P(f"Threshold: avg > {fmt_duration(threshold_sec)}  ({len(bn)} edges flagged)",
               style={"color": "#888", "fontSize": "10px", "marginTop": 0, "marginBottom": "8px"}),
        *items,
    ], style={"minWidth": "280px"})


def _freq_panel(selected_route):
    subset = (agg if selected_route == "ALL"
              else agg[agg["route_id"] == selected_route])
    top5  = subset.nlargest(5, "freq")
    max_f = top5["freq"].max() if len(top5) else 1
    items = []
    for _, r in top5.iterrows():
        colour = ROUTE_COLOURS.get(r["route_id"], DEFAULT_COLOUR)
        pct    = int(r["freq"]) / max_f * 100
        items.append(html.Div(style={"marginBottom": "8px"}, children=[
            html.Div(f"{r['src']} → {r['tgt']}",
                     style={"color": "#ccc", "fontSize": "10px", "marginBottom": "2px"}),
            html.Div(style={"display": "flex", "alignItems": "center", "gap": "8px"}, children=[
                html.Div(style={"height": "10px", "width": f"{pct:.0f}%", "maxWidth": "150px",
                                "backgroundColor": colour, "borderRadius": "4px", "minWidth": "4px"}),
                html.Span(f"{int(r['freq'])} trips | {r['route_id']}",
                          style={"color": "#aaa", "fontSize": "10px"}),
            ]),
        ]))
    return html.Div([
        html.H5("📊 Top-5 Most Frequent Transitions",
                style={"color": "#e94560", "marginTop": 0, "marginBottom": "6px", "fontSize": "13px"}),
        *items,
    ], style={"minWidth": "260px"})


def _build_analytics_bar(selected_route, threshold_sec):
    return [_throughput_table(selected_route),
            _bottleneck_panel(selected_route, threshold_sec),
            _freq_panel(selected_route)]


# ═══════════════════════════════════════════════════════════════════════════════
# 7.  DASH APP — LAYOUT
# ═══════════════════════════════════════════════════════════════════════════════
app = dash.Dash(__name__, title="CDA Bus Route Process Map")

route_options = [{"label": "All Routes", "value": "ALL"}] + [
    {"label": r, "value": r} for r in sorted(agg["route_id"].unique())
]
slider_max   = 600
slider_marks = {i: {"label": f"{i//60}m", "style": {"color": "#aaa", "fontSize": "10px"}}
                for i in range(0, slider_max + 1, 60)}

STYLESHEET = [
    {"selector": "node", "style": {
        "label": "data(label)", "background-color": "data(colour)",
        "color": "#ffffff", "text-outline-color": "#111111", "text-outline-width": "1.5px",
        "font-size": "9px", "width": "28px", "height": "28px",
        "text-valign": "bottom", "text-halign": "center", "text-margin-y": "4px",
    }},
    {"selector": "edge", "style": {
        "label": "data(label)", "line-color": "data(colour)",
        "target-arrow-color": "data(colour)", "target-arrow-shape": "triangle",
        "curve-style": "bezier", "font-size": "7px", "color": "#111111",
        "text-background-color": "#ffffff", "text-background-opacity": 0.85,
        "text-background-padding": "2px", "text-rotation": "autorotate",
        "width": 2, "arrow-scale": 1.2,
    }},
    {"selector": ".bottleneck", "style": {
        "line-color": "#ff0000", "target-arrow-color": "#ff0000",
        "line-style": "dashed", "width": 5,
    }},
    {"selector": "node:selected", "style": {
        "border-width": "3px", "border-color": "#FFD700",
        "background-color": "#FFD700", "color": "#000000",
    }},
    {"selector": "edge:selected", "style": {
        "width": 7, "line-color": "#FFD700", "target-arrow-color": "#FFD700",
    }},
]

# ── AI panel styles ───────────────────────────────────────────────────────────
AI_PANEL_OPEN = {
    "display":         "flex",
    "flexDirection":   "column",
    "width":           "340px",
    "minWidth":        "340px",
    "backgroundColor": "#16213e",
    "borderLeft":      "2px solid #e94560",
    "overflowY":       "hidden",
}
AI_PANEL_CLOSED = {"display": "none"}

app.layout = html.Div(
    style={"fontFamily": "Segoe UI, sans-serif",
           "backgroundColor": "#1a1a2e", "minHeight": "100vh"},
    children=[

        # ── Header ────────────────────────────────────────────────────────────
        html.Div(
            style={"backgroundColor": "#16213e", "padding": "10px 20px",
                   "borderBottom": "2px solid #0f3460", "display": "flex",
                   "alignItems": "center", "gap": "18px", "flexWrap": "wrap"},
            children=[
                html.H2("CDA Bus Route — Process Map",
                        style={"color": "#e94560", "margin": 0,
                               "fontSize": "17px", "whiteSpace": "nowrap"}),

                html.Div([
                    html.Label("Filter by Route:", style={"color": "#aaa", "fontSize": "10px", "display": "block", "marginBottom": "2px"}),
                    dcc.Dropdown(id="route-dropdown", options=route_options,
                                 value="ALL", clearable=False,
                                 style={"width": "175px", "color": "#000"}),
                ]),

                html.Div([
                    html.Label("Layout:", style={"color": "#aaa", "fontSize": "10px", "display": "block", "marginBottom": "2px"}),
                    dcc.Dropdown(id="layout-dropdown",
                                 options=[{"label": "Dagre (L→R)",  "value": "dagre"},
                                          {"label": "Breadthfirst", "value": "breadthfirst"},
                                          {"label": "Circle",       "value": "circle"},
                                          {"label": "Cose",         "value": "cose"},
                                          {"label": "Grid",         "value": "grid"}],
                                 value="dagre", clearable=False,
                                 style={"width": "165px", "color": "#000"}),
                ]),

                html.Div([
                    html.Label(id="threshold-label",
                               children=f"🚨 Bottleneck Threshold: {fmt_duration(DEFAULT_THRESHOLD_SEC)}",
                               style={"color": "#ff8888", "fontSize": "10px",
                                      "display": "block", "marginBottom": "2px", "whiteSpace": "nowrap"}),
                    dcc.Slider(id="threshold-slider", min=0, max=slider_max, step=10,
                               value=DEFAULT_THRESHOLD_SEC, marks=slider_marks,
                               tooltip={"always_visible": False}, updatemode="drag"),
                ], style={"minWidth": "220px", "maxWidth": "300px"}),

                html.Div(id="stats-bar",
                         style={"marginLeft": "auto", "display": "flex",
                                "gap": "8px", "flexWrap": "wrap", "alignItems": "center"}),

                # ── Header buttons ────────────────────────────────────────────
                html.Div(style={"display": "flex", "gap": "8px", "alignItems": "center"}, children=[
                    html.Button(
                        "🤖 AI Planner",
                        id="ai-toggle-btn",
                        n_clicks=0,
                        style={
                            "backgroundColor": "#e94560", "color": "#fff",
                            "border": "none", "borderRadius": "20px",
                            "padding": "8px 16px", "cursor": "pointer",
                            "fontSize": "12px", "fontWeight": "bold",
                            "whiteSpace": "nowrap",
                        }
                    ),
                    html.Button(
                        "📍 Personal Routes",
                        id="t6-open-btn",
                        n_clicks=0,
                        style={
                            "backgroundColor": "#0f3460", "color": "#e94560",
                            "border": "2px solid #e94560", "borderRadius": "20px",
                            "padding": "8px 16px", "cursor": "pointer",
                            "fontSize": "12px", "fontWeight": "bold",
                            "whiteSpace": "nowrap",
                        }
                    ),
                ]),
            ]
        ),

        # ── Graph + side panel + AI panel ────────────────────────────────────
        html.Div(
            style={"display": "flex", "height": "calc(100vh - 260px)"},
            children=[

                cyto.Cytoscape(
                    id="cytoscape-graph",
                    elements=build_elements("ALL", DEFAULT_THRESHOLD_SEC),
                    layout={"name": "dagre", "rankDir": "LR", "spacingFactor": 1.4},
                    style={"flex": "1", "height": "100%"},
                    stylesheet=STYLESHEET,
                    minZoom=0.05, maxZoom=4.0, boxSelectionEnabled=True,
                ),

                # Detail panel
                html.Div(id="side-panel",
                         style={"width": "280px", "backgroundColor": "#16213e",
                                "borderLeft": "2px solid #0f3460",
                                "padding": "14px", "overflowY": "auto",
                                "color": "#cccccc"},
                         children=_default_panel()),

                # ── AI Chat Panel (collapsible sidebar) ───────────────────────
                html.Div(
                    id="ai-panel-container",
                    style=AI_PANEL_CLOSED,
                    children=[
                        html.Div(
                            style={"backgroundColor": "#e94560", "color": "#fff",
                                   "padding": "10px 14px", "fontWeight": "bold",
                                   "fontSize": "13px",
                                   "display": "flex", "justifyContent": "space-between",
                                   "alignItems": "center"},
                            children=[
                                html.Span("🤖 CDA Trip Planner  (Task 5)"),
                                html.Span("Ask me anything about CDA routes",
                                          style={"fontSize": "10px", "fontWeight": "normal",
                                                 "opacity": "0.8"}),
                            ]
                        ),
                        # Query hint chips
                        html.Div(
                            style={"padding": "8px 10px", "backgroundColor": "#0f3460",
                                   "fontSize": "10px", "color": "#aaa",
                                   "borderBottom": "1px solid #1a3a6e"},
                            children=[
                                html.Div("Try asking:", style={"marginBottom": "4px", "color": "#e94560"}),
                                html.Div("• Which route goes through Faizabad?"),
                                html.Div("• What time does the last bus leave from PTCL I-10?"),
                                html.Div("• How long from Khanna Pul to FAST?"),
                                html.Div("• Do any routes connect G-9 to Abpara?"),
                            ]
                        ),
                        html.Div(
                            id="chat-history",
                            style={"flex": "1", "padding": "12px",
                                   "overflowY": "auto", "color": "#e0e0e0",
                                   "fontSize": "12px", "backgroundColor": "#16213e"},
                            children=[
                                html.Div(
                                    "Hello! I am your CDA Bus Assistant. Use the hints above or ask your own question.",
                                    style={"color": "#888", "fontStyle": "italic",
                                           "marginBottom": "10px", "fontSize": "11px"}
                                )
                            ]
                        ),
                        html.Div(
                            style={"padding": "10px", "display": "flex", "gap": "6px",
                                   "borderTop": "1px solid #0f3460",
                                   "backgroundColor": "#16213e"},
                            children=[
                                dcc.Input(
                                    id="chat-input", type="text",
                                    placeholder="Type your question...",
                                    debounce=False,
                                    style={"flex": "1", "borderRadius": "6px",
                                           "border": "1px solid #0f3460",
                                           "padding": "8px", "fontSize": "12px",
                                           "backgroundColor": "#0f3460", "color": "#fff"}
                                ),
                                html.Button(
                                    "Send", id="chat-send", n_clicks=0,
                                    style={"backgroundColor": "#e94560", "color": "#fff",
                                           "border": "none", "padding": "8px 14px",
                                           "borderRadius": "6px", "cursor": "pointer",
                                           "fontSize": "12px"}
                                ),
                            ]
                        ),
                    ]
                ),
            ]
        ),

        # ── Analytics bar (Task 4) ────────────────────────────────────────────
        html.Div(
            id="analytics-bar",
            style={"backgroundColor": "#16213e", "borderTop": "2px solid #0f3460",
                   "padding": "12px 24px", "display": "flex", "gap": "32px",
                   "flexWrap": "wrap", "alignItems": "flex-start", "overflowX": "auto"},
            children=_build_analytics_bar("ALL", DEFAULT_THRESHOLD_SEC),
        ),

        # ── Task 6: Personal Routes full-screen overlay ───────────────────────
        html.Div(
            id="t6-overlay",
            style={"display": "none", "position": "fixed", "top": 0, "left": 0,
                   "width": "100vw", "height": "100vh",
                   "backgroundColor": "#1a1a2e", "zIndex": 2000,
                   "flexDirection": "column"},
            children=[
                # Header bar
                html.Div(style={
                    "backgroundColor": "#16213e", "padding": "12px 24px",
                    "borderBottom": "2px solid #e94560",
                    "display": "flex", "alignItems": "center", "gap": "20px"
                }, children=[
                    html.H2("📍 Task 6 — Personal Route Maps",
                            style={"color": "#e94560", "margin": 0, "fontSize": "18px"}),
                    html.P("Each member's home address to FAST University — verified on live route data",
                           style={"color": "#888", "margin": 0, "fontSize": "12px", "flex": 1}),
                    dcc.Dropdown(
                        id="member-dropdown",
                        options=[{"label": m["label"], "value": m["value"]} for m in MEMBERS],
                        value="m1",
                        clearable=False,
                        style={"width": "240px", "color": "#000"},
                    ),
                    html.Button("✕ Close", id="t6-close-btn", n_clicks=0,
                                style={"backgroundColor": "#e94560", "color": "#fff",
                                       "border": "none", "borderRadius": "8px",
                                       "padding": "8px 18px", "cursor": "pointer",
                                       "fontSize": "13px", "fontWeight": "bold"}),
                ]),
                # Body: info card (left) + Cytoscape graph (right)
                html.Div(style={"display": "flex", "flex": 1, "overflow": "hidden"}, children=[
                    # Left info card
                    html.Div(id="member-info-card",
                             style={"width": "340px", "backgroundColor": "#16213e",
                                    "borderRight": "2px solid #0f3460",
                                    "padding": "20px", "overflowY": "auto",
                                    "color": "#cccccc"}),
                    # Right Cytoscape
                    cyto.Cytoscape(
                        id="t6-graph",
                        elements=[],
                        layout={"name": "dagre", "rankDir": "LR", "spacingFactor": 1.6},
                        style={"flex": "1", "height": "100%", "backgroundColor": "#1a1a2e"},
                        stylesheet=T6_STYLESHEET,
                        minZoom=0.1, maxZoom=4.0,
                    ),
                ]),
            ]
        ),
    ]
)


# ═══════════════════════════════════════════════════════════════════════════════
# 8.  CALLBACKS
# ═══════════════════════════════════════════════════════════════════════════════
def _badge(text, bg="#0f3460", border="#e94560"):
    return html.Div(text, style={
        "backgroundColor": bg, "color": "#e0e0e0",
        "padding": "5px 12px", "borderRadius": "20px",
        "fontSize": "11px", "border": f"1px solid {border}", "whiteSpace": "nowrap",
    })


@app.callback(
    Output("cytoscape-graph", "elements"),
    Output("cytoscape-graph", "layout"),
    Output("stats-bar",       "children"),
    Output("analytics-bar",   "children"),
    Output("threshold-label", "children"),
    Input("route-dropdown",   "value"),
    Input("layout-dropdown",  "value"),
    Input("threshold-slider", "value"),
)
def update_graph(selected_route, layout_name, threshold_sec):
    elements   = build_elements(selected_route, threshold_sec)
    layout     = {"name": layout_name, "rankDir": "LR", "spacingFactor": 1.4,
                  "animate": True, "animationDuration": 400}
    nodes      = [e for e in elements if "source" not in e["data"]]
    edges      = [e for e in elements if "source"     in e["data"]]
    total_freq = sum(e["data"]["freq"]  for e in edges)
    bn_count   = sum(1 for e in edges if e["data"]["is_bn"])
    n_trips    = (throughput_df if selected_route == "ALL"
                  else throughput_df[throughput_df["route_id"] == selected_route])["trip_id"].nunique()
    stats      = [
        _badge(f"🛑 {len(nodes)} Stops"),
        _badge(f"➡ {len(edges)} Transitions"),
        _badge(f"🚌 {n_trips} Trips"),
        _badge(f"🔁 {total_freq} Trip passes"),
        _badge(f"🚨 {bn_count} Bottlenecks", bg="#3a0000", border="#ff4444"),
    ]
    label = (f"🚨 Bottleneck Threshold: {fmt_duration(threshold_sec)}"
             f"  — edges slower than this are highlighted red")
    return elements, layout, stats, _build_analytics_bar(selected_route, threshold_sec), label


@app.callback(
    Output("side-panel", "children"),
    Input("cytoscape-graph", "tapNodeData"),
    Input("cytoscape-graph", "tapEdgeData"),
    State("threshold-slider", "value"),
)
def show_detail(node_data, edge_data, threshold_sec):
    ctx     = callback_context
    if not ctx.triggered:
        return _default_panel()
    trigger = ctx.triggered[0]["prop_id"]

    if "tapEdgeData" in trigger and edge_data:
        d     = edge_data
        is_bn = d.get("avg_sec", 0) >= threshold_sec
        bn_tag = html.Span(" 🚨 BOTTLENECK", style={"color": "#ff4444", "fontSize": "11px"}) if is_bn else html.Span("")
        src, tgt, rid = d.get("source", ""), d.get("target", ""), d.get("route_id", "")
        edge_trips = edges_df[
            (edges_df["route_id"] == rid) & (edges_df["src"] == src) & (edges_df["tgt"] == tgt)
        ].merge(throughput_df[["trip_id", "first_clock"]], on="trip_id", how="left").sort_values("first_clock")

        trip_rows = []
        for _, er in edge_trips.head(10).iterrows():
            trip_rows.append(html.Div(
                f"Dep {er.get('first_clock','?')} — {fmt_duration(er['dur_sec'])}",
                style={"color": "#aaa", "fontSize": "10px",
                       "borderBottom": "1px solid #0f3460",
                       "paddingBottom": "2px", "marginBottom": "2px"}
            ))
        if len(edge_trips) > 10:
            trip_rows.append(html.Div(f"… and {len(edge_trips)-10} more trips",
                                      style={"color": "#555", "fontSize": "9px"}))

        return [
            html.H4(["Edge Detail", bn_tag],
                    style={"color": "#e94560", "marginTop": 0, "fontSize": "14px"}),
            _detail_row("Route", d.get("route_id", "?")),
            _detail_row("From",  d.get("source",   "?")),
            _detail_row("To",    d.get("target",   "?")),
            html.Hr(style={"borderColor": "#0f3460"}),
            html.H5("⏱ Transition Duration  (Task 3c)",
                    style={"color": "#e94560", "fontSize": "12px", "marginBottom": "6px"}),
            _detail_row("Avg Duration", fmt_duration(d.get("avg_sec", 0)), "#fca5a5" if is_bn else "#e0e0e0"),
            _detail_row("Min Duration", fmt_duration(d.get("min_sec", 0)), "#4ade80"),
            _detail_row("Max Duration", fmt_duration(d.get("max_sec", 0)), "#f87171"),
            html.Hr(style={"borderColor": "#0f3460"}),
            html.H5("📊 Case Frequency  (Task 3d)",
                    style={"color": "#e94560", "fontSize": "12px", "marginBottom": "6px"}),
            _detail_row("Trips traversed", f"{d.get('freq', 0)} trips", "#60a5fa"),
            html.Div(style={"backgroundColor": "#0f3460", "borderRadius": "6px",
                            "padding": "10px", "textAlign": "center", "marginTop": "4px"}, children=[
                html.Div(f"{d.get('freq', 0)}", style={"color": "#60a5fa", "fontWeight": "bold", "fontSize": "22px"}),
                html.Div("trips used this transition", style={"color": "#aaa", "fontSize": "10px"}),
            ]),
            html.Hr(style={"borderColor": "#0f3460"}),
            html.H5("🕐 Per-Trip Departure Times",
                    style={"color": "#e94560", "fontSize": "12px", "marginBottom": "4px"}),
            *trip_rows,
            html.Hr(style={"borderColor": "#0f3460"}),
            html.H5("Legend", style={"color": "#e94560", "fontSize": "12px"}),
            html.Div(_build_legend()),
        ]

    if "tapNodeData" in trigger and node_data:
        stop     = node_data.get("id", "?")
        outgoing = agg[agg["src"] == stop].sort_values("avg_sec", ascending=False)
        incoming = agg[agg["tgt"] == stop].sort_values("avg_sec", ascending=False)
        total_in  = int(incoming["freq"].sum())
        total_out = int(outgoing["freq"].sum())

        stop_times = df[df["stop_name"] == stop][["route_id", "trip_id", "arrival_time"]].merge(
            throughput_df[["trip_id", "first_clock"]], on="trip_id", how="left"
        ).sort_values("arrival_time")

        stop_time_rows = []
        for _, sr in stop_times.head(8).iterrows():
            colour = ROUTE_COLOURS.get(sr["route_id"], DEFAULT_COLOUR)
            stop_time_rows.append(html.Div(
                style={"display": "flex", "justifyContent": "space-between",
                       "fontSize": "10px", "color": "#aaa",
                       "borderBottom": "1px solid #0f3460",
                       "paddingBottom": "2px", "marginBottom": "2px"},
                children=[
                    html.Span(sr["route_id"], style={"color": colour, "fontWeight": "bold"}),
                    html.Span(str(sr["arrival_time"])[:5]),
                ]
            ))
        if len(stop_times) > 8:
            stop_time_rows.append(html.Div(f"… and {len(stop_times)-8} more",
                                           style={"color": "#555", "fontSize": "9px"}))

        def edge_rows(sub, direction):
            rows = []
            for _, r in sub.iterrows():
                other  = r["tgt"] if direction == "out" else r["src"]
                colour = ROUTE_COLOURS.get(r["route_id"], DEFAULT_COLOUR)
                is_bn  = r["avg_sec"] >= threshold_sec
                rows.append(html.Div(style={
                    "padding": "5px 8px",
                    "backgroundColor": "#1a0000" if is_bn else "#0f3460",
                    "borderRadius": "4px", "marginBottom": "4px",
                    "borderLeft": f"3px solid {'#ff0000' if is_bn else colour}",
                }, children=[
                    html.Div(("→ " if direction == "out" else "← ") + other + (" 🚨" if is_bn else ""),
                             style={"color": "#e0e0e0", "fontWeight": "bold", "fontSize": "11px"}),
                    html.Div(f"{fmt_duration(r['avg_sec'])}  |  {int(r['freq'])} trips  |  {r['route_id']}",
                             style={"color": "#888", "fontSize": "10px", "marginTop": "2px"}),
                ]))
            return rows or [html.P("None", style={"color": "#555", "fontSize": "11px"})]

        return [
            html.H4("Stop Detail", style={"color": "#e94560", "marginTop": 0, "fontSize": "14px"}),
            _detail_row("Stop",   stop),
            _detail_row("Routes", node_data.get("routes", "?")),
            html.Hr(style={"borderColor": "#0f3460"}),
            html.H5("🕐 Bus Times at This Stop",
                    style={"color": "#e94560", "fontSize": "12px", "marginBottom": "4px"}),
            *stop_time_rows,
            html.Hr(style={"borderColor": "#0f3460"}),
            html.H5("📊 Case Frequency  (Task 3d)",
                    style={"color": "#e94560", "fontSize": "12px", "marginBottom": "6px"}),
            html.Div(style={"display": "flex", "gap": "8px", "marginBottom": "10px"}, children=[
                html.Div(style={"flex": "1", "backgroundColor": "#0f3460", "borderRadius": "6px", "padding": "8px", "textAlign": "center"}, children=[
                    html.Div(str(total_in),  style={"color": "#4ade80", "fontWeight": "bold", "fontSize": "18px"}),
                    html.Div("trips in",     style={"color": "#aaa", "fontSize": "10px"}),
                ]),
                html.Div(style={"flex": "1", "backgroundColor": "#0f3460", "borderRadius": "6px", "padding": "8px", "textAlign": "center"}, children=[
                    html.Div(str(total_out), style={"color": "#60a5fa", "fontWeight": "bold", "fontSize": "18px"}),
                    html.Div("trips out",    style={"color": "#aaa", "fontSize": "10px"}),
                ]),
            ]),
            html.P("Outgoing →", style={"color": "#aaa", "margin": "0 0 4px 0", "fontWeight": "bold", "fontSize": "12px"}),
            *edge_rows(outgoing, "out"),
            html.Hr(style={"borderColor": "#0f3460"}),
            html.P("← Incoming", style={"color": "#aaa", "margin": "0 0 4px 0", "fontWeight": "bold", "fontSize": "12px"}),
            *edge_rows(incoming, "in"),
            html.Hr(style={"borderColor": "#0f3460"}),
            html.H5("Legend", style={"color": "#e94560", "fontSize": "12px"}),
            html.Div(_build_legend()),
        ]

    return _default_panel()


# ── AI panel toggle ───────────────────────────────────────────────────────────
@app.callback(
    Output("ai-panel-container", "style"),
    Output("ai-toggle-btn",      "children"),
    Input("ai-toggle-btn",       "n_clicks"),
    prevent_initial_call=True,
)
def toggle_ai_panel(n_clicks):
    if (n_clicks or 0) % 2 == 1:
        return AI_PANEL_OPEN, "✕ Close AI"
    return AI_PANEL_CLOSED, "🤖 AI Planner"


# ── AI chat callback ──────────────────────────────────────────────────────────
@app.callback(
    Output("chat-history", "children"),
    Output("chat-input",   "value"),
    Input("chat-send",     "n_clicks"),
    Input("chat-input",    "n_submit"),
    State("chat-input",    "value"),
    State("chat-history",  "children"),
    prevent_initial_call=True,
)
def update_chat(n_clicks, n_submit, user_text, history):
    if not user_text or not user_text.strip():
        return history, ""

    new_history = list(history) + [
        html.Div([html.B("You: "), html.Span(user_text)],
                 style={"marginBottom": "8px", "textAlign": "right", "color": "#fbbf24"})
    ]

    response = ai_agent_query(user_text, df, edges_df)

    new_history.append(
        html.Div(dcc.Markdown(response),
                 style={"marginBottom": "12px", "backgroundColor": "#1a1a2e",
                        "padding": "8px 10px", "borderRadius": "6px",
                        "borderLeft": "3px solid #e94560"})
    )
    return new_history, ""


# ── Task 6: overlay toggle ────────────────────────────────────────────────────
@app.callback(
    Output("t6-overlay", "style"),
    Input("t6-open-btn",  "n_clicks"),
    Input("t6-close-btn", "n_clicks"),
    prevent_initial_call=True,
)
def toggle_t6_overlay(open_clicks, close_clicks):
    trigger = callback_context.triggered[0]["prop_id"]
    if "t6-open-btn" in trigger:
        return {"display": "flex", "position": "fixed", "top": 0, "left": 0,
                "width": "100vw", "height": "100vh",
                "backgroundColor": "#1a1a2e", "zIndex": 2000, "flexDirection": "column"}
    return {"display": "none"}


# ── Task 6: member route visualization ───────────────────────────────────────
@app.callback(
    Output("t6-graph",        "elements"),
    Output("member-info-card", "children"),
    Input("member-dropdown",  "value"),
)
def update_member_route(member_val):
    member = next((m for m in MEMBERS if m["value"] == member_val), MEMBERS[0])
    elements, legs = build_member_path_elements(member["stop"])
    total_sec = sum(dur for _, _, _, _, dur in legs) if legs else 0

    def _row(label, value, colour="#cccccc"):
        return html.Div(style={"display": "flex", "justifyContent": "space-between",
                               "borderBottom": "1px solid #0f3460",
                               "padding": "6px 0", "marginBottom": "4px"}, children=[
            html.Span(label, style={"color": "#888", "fontSize": "12px"}),
            html.Span(value, style={"color": colour, "fontWeight": "bold", "fontSize": "12px",
                                    "maxWidth": "200px", "textAlign": "right", "wordBreak": "break-word"}),
        ])

    leg_items = []
    for i, (ls, le, rid, direction, dur) in enumerate(legs, 1):
        d_label = "Return" if direction == "reverse" else "Forward"
        colour  = ROUTE_COLOURS.get(rid, DEFAULT_COLOUR)
        leg_items.append(html.Div(style={
            "backgroundColor": "#0d1b2a", "border": f"1px solid {colour}",
            "borderLeft": f"5px solid {colour}", "borderRadius": "6px",
            "padding": "8px 12px", "marginBottom": "8px",
        }, children=[
            html.Div(f"Leg {i} — Route {rid} ({d_label})",
                     style={"color": colour, "fontWeight": "bold", "fontSize": "12px"}),
            html.Div(f"{ls}  →  {le}",
                     style={"color": "#ccc", "fontSize": "11px", "marginTop": "3px"}),
            html.Div(f"~{fmt_duration(dur)}",
                     style={"color": "#fbbf24", "fontSize": "11px", "marginTop": "2px"}),
        ]))

    # Departure times from member stop
    first_route = legs[0][2] if legs else None
    dep_times   = []
    if first_route:
        dep_times = sorted(df[
            (df["stop_name"] == member["stop"]) & (df["route_id"] == first_route)
        ]["departure_time"].dropna().str[:5].unique().tolist())

    card = [
        html.H3(member["name"],
                style={"color": "#e94560", "marginTop": 0, "marginBottom": "4px"}),
        html.Hr(style={"borderColor": "#0f3460", "marginBottom": "12px"}),
        _row("Home Address", member["address"]),
        _row("Area",         member["area"]),
        _row("Nearest Stop", member["stop"], "#60a5fa"),
        _row("Destination",  "FAST University", "#e94560"),
        _row("Total Time",   f"~{fmt_duration(total_sec)}", "#fbbf24"),
        html.Hr(style={"borderColor": "#0f3460", "margin": "12px 0"}),
        html.H5("Route Legs", style={"color": "#e94560", "fontSize": "13px", "marginBottom": "8px"}),
        *leg_items,
    ]
    if dep_times:
        card += [
            html.Hr(style={"borderColor": "#0f3460", "margin": "12px 0"}),
            html.H5("Departure Times from Stop",
                    style={"color": "#e94560", "fontSize": "13px", "marginBottom": "6px"}),
            html.P(f"First: {dep_times[0]}   Last: {dep_times[-1]}",
                   style={"color": "#fbbf24", "fontSize": "12px", "margin": 0}),
        ]
    card += [
        html.Hr(style={"borderColor": "#0f3460", "margin": "12px 0"}),
        html.Div(style={"display": "flex", "gap": "8px", "flexWrap": "wrap"}, children=[
            html.Div(style={"display": "flex", "alignItems": "center", "gap": "5px"}, children=[
                html.Div(style={"width": "12px", "height": "12px", "borderRadius": "50%",
                                "backgroundColor": "#00e676"}),
                html.Span("Start", style={"color": "#aaa", "fontSize": "11px"}),
            ]),
            html.Div(style={"display": "flex", "alignItems": "center", "gap": "5px"}, children=[
                html.Div(style={"width": "12px", "height": "12px", "borderRadius": "50%",
                                "backgroundColor": "#e94560", "border": "2px solid #FFD700"}),
                html.Span("FAST University", style={"color": "#aaa", "fontSize": "11px"}),
            ]),
        ]),
    ]

    return elements, card


# ═══════════════════════════════════════════════════════════════════════════════
# 9.  RUN
# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("\nStarting CDA Bus Route Process Map...")
    print("Open browser at:  http://127.0.0.1:8050\n")
    app.run(debug=True)
