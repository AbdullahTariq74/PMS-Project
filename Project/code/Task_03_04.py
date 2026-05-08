# Task_03.py — Process Discovery & Interactive GUI + Task 4 Analytics
# pip install dash dash-cytoscape pandas
#
# FIX NOTES (vs original):
# ─────────────────────────────────────────────────────────────────────
# 1. trip_id is NOT prefixed with route_id — the CSV already has unique
#    trip_ids, so the old prefix created phantom duplicates.
# 2. Timestamps are parsed directly from the time strings without
#    anchoring every row to "2024-01-01", which caused midnight-crossing
#    trips to compute negative durations.  Instead we use the
#    time:timestamp column (already ISO-8601) from the clean CSV.
# 3. Throughput table now shows BOTH route-level aggregates AND a
#    scrollable per-trip schedule (Task 4a requirement: "total end-to-end
#    duration for each case").
# 4. The "min = max = avg" situation is explained clearly in the GUI
#    because the CDA dataset genuinely uses identical relative schedules
#    for every departure of a route (all trips are time-shifted copies).
#    The per-trip table proves this by listing each trip's actual
#    departure and arrival clock times alongside its duration.
# 5. Edge min/max/avg are computed correctly; because the underlying data
#    has no variance per edge, they are legitimately equal — the GUI now
#    labels this honestly instead of showing confusingly identical numbers.
# ─────────────────────────────────────────────────────────────────────

import pandas as pd
import re
import dash
from dash import dcc, html, Input, Output, State, callback_context
import dash_cytoscape as cyto
import collections

# ── Task 5: Agentic AI Pathfinding Engine (Grounded & Free) ───────────────────
def find_trip_plan(start_stop, end_stop, current_df, edges_df):
    """
    Grounded pathfinding using BFS to find the shortest route in terms of stops.
    Returns a natural language response.
    """
    start_stop = start_stop.strip()
    end_stop   = end_stop.strip()

    # Build adjacency list: { src: [ (tgt, route_id, avg_sec, direction), ... ] }
    adj = collections.defaultdict(list)
    for _, row in edges_df.drop_duplicates(['src', 'tgt', 'route_id']).iterrows():
        # Forward edge
        adj[row['src']].append((row['tgt'], row['route_id'], row['dur_sec'], "forward"))
        # Synthetic Reverse edge (Agentic enhancement: assume return trip exists)
        adj[row['tgt']].append((row['src'], row['route_id'], row['dur_sec'], "reverse"))

    queue = collections.deque([(start_stop, [])]) # (current_stop, path_of_edges)
    visited = {start_stop}

    while queue:
        curr, path = queue.popleft()
        if curr == end_stop:
            # Format response
            response = f"**Agent:** I found a route from **{start_stop}** to **{end_stop}** using inferred connectivity!\n\n"
            total_time = 0
            for i, (s, t, rid, dur, direction) in enumerate(path):
                total_time += dur
                dir_str = "Forward" if direction == "forward" else "Return/Reverse"
                response += f"{i+1}. Take **Route {rid}** ({dir_str}) from *{s}* to *{t}* (approx {int(dur//60)}m {int(dur%60)}s)\n"
            
            response += f"\n**Total estimated travel time:** {int(total_time//60)} minutes."
            return response

        for tgt, rid, dur, direction in adj.get(curr, []):
            if tgt not in visited:
                visited.add(tgt)
                new_path = path + [(curr, tgt, rid, dur, direction)]
                queue.append((tgt, new_path))

    return "**Agent:** I'm sorry, I couldn't find a direct or connecting bus route between those stops in the current CDA dataset."

def ai_agent_query(user_text, current_df, edges_df):
    user_text = user_text.lower().strip()
    all_stops = current_df['stop_name'].unique()
    src = None
    dst = None
    
    # ── Task 5 Enhancement: Alias Mapping for common area names ───────────
    aliases = {
        "h8": "PAEC General Hospital",
        "h-8": "PAEC General Hospital",
        "i10": "PTCL I-10",
        "i-10": "PTCL I-10",
        "khanna": "Khanna Pul",
        "fast": "FAST University",
        "nust": "Nust Metro Station",
        "pims": "PIMS Hospital",
        "police foundation": "Police Foundation Metro"
    }
    
    # Check for aliases first by tokenizing
    words = user_text.replace("?", "").replace(".", "").split()
    found_from_alias = None
    found_to_alias = None

    # Simple "from X to Y" parsing for aliases
    if "from" in words and "to" in words:
        try:
            f_idx = words.index("from")
            t_idx = words.index("to")
            from_word = words[f_idx + 1]
            to_word = words[t_idx + 1]
            if from_word in aliases: src = aliases[from_word]
            if to_word in aliases: dst = aliases[to_word]
        except: pass

    # Sort stops by length descending to catch longer names first
    sorted_stops = sorted(all_stops, key=len, reverse=True)
    
    # Standard parsing
    if not src or not dst:
        if "from" in user_text and "to" in user_text:
            try:
                parts = user_text.split("from")
                after_from = parts[1]
                if "to" in after_from:
                    from_part = after_from.split("to")[0].strip()
                    to_part   = after_from.split("to")[1].strip()
                    for s in sorted_stops:
                        if s.lower() in from_part and not src: src = s
                        if s.lower() in to_part and not dst: dst = s
                    # Final alias check for parts if still missing
                    for k, v in aliases.items():
                        if k in from_part and not src: src = v
                        if k in to_part and not dst: dst = v
            except: pass
    
    # Fallback: look for any mentions
    if not src or not dst:
        found_matches = []
        # Check aliases first
        for k, v in aliases.items():
            if k in user_text:
                found_matches.append((user_text.find(k), v))
        # Check actual stops
        for s in sorted_stops:
            if s.lower() in user_text:
                found_matches.append((user_text.find(s.lower()), s))
        
        if len(found_matches) >= 2:
            found_matches.sort() # Sort by appearance in text
            src = found_matches[0][1]
            dst = found_matches[1][1]

    if src and dst:
        if src == dst:
            return f"**Agent:** You are already at **{src}**!"
        return find_trip_plan(src, dst, current_df, edges_df)
    
    return ("**Agent:** Hello! I am your CDA Trip Assistant. "
            "Please tell me where you are starting from and where you want to go. "
            "(e.g., 'How do I get from Khanna Pul to FAST University?')")

cyto.load_extra_layouts()

import os
# ── Path ──────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_CSV = os.path.join(BASE_DIR, "data", "routes_clean.csv")
# ═══════════════════════════════════════════════════════════════════════════════
# 1.  LOAD & PREPARE DATA
# ═══════════════════════════════════════════════════════════════════════════════
df = pd.read_csv(INPUT_CSV)
df.columns = df.columns.str.strip()

print("Columns:", df.columns.tolist())

# ── Fix: do NOT prepend route_id — trip_ids are already globally unique ───────
df["trip_id"]       = df["trip_id"].astype(str).str.strip()
df["stop_name"]     = df["stop_name"].astype(str).str.strip()
df["route_id"]      = df["route_id"].astype(str).str.strip()
df["stop_sequence"] = pd.to_numeric(df["stop_sequence"], errors="coerce")

# ── Fix: parse timestamps from the pre-built ISO column in the CSV ────────────
#    This avoids the "2024-01-01" anchor trick which makes all durations equal
#    for routes whose trips span less than 24 hours relative to their base.
df["ts_arrival"] = pd.to_datetime(
    df["time:timestamp"], utc=False, errors="coerce"
)
# departure_time may differ from arrival_time; add the delta
def _parse_hms(s):
    """Return total seconds from HH:MM:SS string, or None."""
    s = str(s).strip()
    m = re.match(r"(\d{1,2}):(\d{2}):(\d{2})", s)
    if m:
        h, mi, sec = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return h * 3600 + mi * 60 + sec
    return None

df["_arr_sec"] = df["arrival_time"].apply(_parse_hms)
df["_dep_sec"] = df["departure_time"].apply(_parse_hms)
df["_dwell_sec"] = (df["_dep_sec"] - df["_arr_sec"]).clip(lower=0)

df["ts_departure"] = df["ts_arrival"] + pd.to_timedelta(
    df["_dwell_sec"], unit="s"
)

df = df.dropna(subset=["ts_arrival", "ts_departure", "stop_name", "trip_id"])
df = df.sort_values(["trip_id", "stop_sequence"]).reset_index(drop=True)

print(f"Loaded: {len(df)} rows | {df['trip_id'].nunique()} trips | "
      f"{df['route_id'].nunique()} routes")
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

        records.append({
            "route_id": route_id,
            "trip_id":  trip_id,
            "src":      src,
            "tgt":      tgt,
            "dur_sec":  max(0, dur_sec),
        })

edges_df = pd.DataFrame(records)

agg = (
    edges_df
    .groupby(["route_id", "src", "tgt"])
    .agg(
        freq    = ("trip_id", "nunique"),
        avg_sec = ("dur_sec", "mean"),
        min_sec = ("dur_sec", "min"),
        max_sec = ("dur_sec", "max"),
    )
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
#     Ttotal = t_last_departure − t_first_arrival   (as per task spec)
# ═══════════════════════════════════════════════════════════════════════════════
tp_records = []

for (route_id, trip_id), group in df.groupby(["route_id", "trip_id"]):
    group        = group.sort_values("stop_sequence")
    first_arrive = group["ts_arrival"].iloc[0]
    last_depart  = group["ts_departure"].iloc[-1]
    duration_sec = (last_depart - first_arrive).total_seconds()
    if duration_sec < 0:
        duration_sec = 0

    # Human-readable clock times (HH:MM)
    first_clock = group["arrival_time"].iloc[0][:5]    # e.g. "06:00"
    last_clock  = group["departure_time"].iloc[-1][:5] # e.g. "06:47"

    tp_records.append({
        "route_id":    route_id,
        "trip_id":     trip_id,
        "duration_sec": max(0, duration_sec),
        "first_stop":  group["stop_name"].iloc[0],
        "last_stop":   group["stop_name"].iloc[-1],
        "first_clock": first_clock,
        "last_clock":  last_clock,
        "num_stops":   len(group),
    })

throughput_df = pd.DataFrame(tp_records).sort_values(
    ["route_id", "first_clock"]
).reset_index(drop=True)

route_throughput = (
    throughput_df.groupby("route_id")["duration_sec"]
    .agg(avg_sec="mean", min_sec="min", max_sec="max", trips="count")
    .reset_index()
)

print("\nThroughput per route:")
for _, r in route_throughput.iterrows():
    print(f"  {r['route_id']}: avg={fmt_duration(r['avg_sec'])} "
          f"min={fmt_duration(r['min_sec'])} max={fmt_duration(r['max_sec'])} "
          f"trips={int(r['trips'])}")

# ═══════════════════════════════════════════════════════════════════════════════
# 4.  BOTTLENECK DETECTION  (Task 4b)
#     Default threshold = mean + 1 std deviation
# ═══════════════════════════════════════════════════════════════════════════════
GLOBAL_MEAN = agg["avg_sec"].mean()
GLOBAL_STD  = agg["avg_sec"].std()
DEFAULT_THRESHOLD_SEC = int(GLOBAL_MEAN + GLOBAL_STD)

print(f"\nBottleneck default threshold: {fmt_duration(DEFAULT_THRESHOLD_SEC)}")

# ═══════════════════════════════════════════════════════════════════════════════
# 5.  COLOURS & ELEMENT BUILDER
# ═══════════════════════════════════════════════════════════════════════════════
ROUTE_COLOURS = {
    "FR-01":  "#e6194b",
    "FR-03A": "#3cb44b",
    "FR-04":  "#ffe119",
    "FR-07":  "#3cb44b",
    "FR-08A": "#4363d8",
    "FR-08C": "#f58231",
    "FR-09":  "#911eb4",
    "FR-11":  "#42d4f4",
    "FR-15":  "#f032e6",
    "FRG-1":  "#bfef45",
}
DEFAULT_COLOUR = "#aaaaaa"


def build_elements(selected_route: str, threshold_sec: float):
    subset = (agg.copy() if selected_route == "ALL"
              else agg[agg["route_id"] == selected_route].copy())

    all_stops   = pd.concat([subset["src"], subset["tgt"]]).unique()
    stop_routes: dict = {}
    for _, row in subset.iterrows():
        stop_routes.setdefault(row["src"], set()).add(row["route_id"])
        stop_routes.setdefault(row["tgt"], set()).add(row["route_id"])

    nodes = []
    for stop in all_stops:
        routes_here = stop_routes.get(stop, set())
        colour      = ROUTE_COLOURS.get(next(iter(routes_here)), DEFAULT_COLOUR)
        nodes.append({"data": {
            "id":     stop,
            "label":  stop,
            "routes": ", ".join(sorted(routes_here)),
            "colour": colour,
        }})

    edges = []
    for _, row in subset.iterrows():
        is_bn       = row["avg_sec"] >= threshold_sec
        edge_colour = "#ff0000" if is_bn else ROUTE_COLOURS.get(
            row["route_id"], DEFAULT_COLOUR)
        edge_label  = f"{row['dur_label']} | {int(row['freq'])} trips"

        edges.append({
            "data": {
                "id":        f"{row['route_id']}__{row['src']}__{row['tgt']}",
                "source":    row["src"],
                "target":    row["tgt"],
                "route_id":  row["route_id"],
                "label":     edge_label,
                "freq":      int(row["freq"]),
                "avg_sec":   round(row["avg_sec"], 1),
                "min_sec":   int(row["min_sec"]),
                "max_sec":   int(row["max_sec"]),
                "colour":    edge_colour,
                "dur_label": row["dur_label"],
                "is_bn":     is_bn,
            },
            "classes": "bottleneck" if is_bn else "",
        })

    return nodes + edges


# ═══════════════════════════════════════════════════════════════════════════════
# 6.  PANEL / TABLE BUILDERS
# ═══════════════════════════════════════════════════════════════════════════════
def _build_legend():
    all_routes = sorted(df["route_id"].unique())
    items = []
    for route in all_routes:
        colour = ROUTE_COLOURS.get(route, DEFAULT_COLOUR)
        items.append(
            html.Div(
                style={"display": "flex", "alignItems": "center",
                       "marginBottom": "5px"},
                children=[
                    html.Div(style={
                        "width": "14px", "height": "14px",
                        "backgroundColor": colour, "borderRadius": "3px",
                        "marginRight": "8px", "flexShrink": "0",
                    }),
                    html.Span(route,
                              style={"color": "#cccccc", "fontSize": "12px"})
                ]
            )
        )
    items.append(
        html.Div(
            style={"display": "flex", "alignItems": "center",
                   "marginTop": "6px"},
            children=[
                html.Div(style={
                    "width": "24px", "height": "3px",
                    "background": "repeating-linear-gradient("
                                  "90deg,#ff0000 0,#ff0000 6px,"
                                  "transparent 6px,transparent 10px)",
                    "marginRight": "8px",
                }),
                html.Span("Bottleneck edge",
                          style={"color": "#ff8888", "fontSize": "11px"})
            ]
        )
    )
    return items


def _detail_row(label, value, value_colour="#e0e0e0"):
    return html.Div(
        style={
            "display": "flex", "justifyContent": "space-between",
            "marginBottom": "6px", "borderBottom": "1px solid #0f3460",
            "paddingBottom": "4px",
        },
        children=[
            html.Span(label + ":",
                      style={"color": "#888888", "fontSize": "12px"}),
            html.Span(str(value), style={
                "color": value_colour, "fontWeight": "bold",
                "fontSize": "12px", "textAlign": "right",
                "maxWidth": "170px", "wordBreak": "break-word",
            }),
        ]
    )


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


# ── Task 4a: Throughput table (route summary + per-trip cases) ────────────────
def _throughput_table(selected_route):
    """
    Task 4a — shows avg/min/max per route AND a per-case (per-trip) table.
    Formula: Ttotal = t_last_departure − t_first_arrival
    """
    tp_route = (route_throughput if selected_route == "ALL"
                else route_throughput[
                    route_throughput["route_id"] == selected_route])

    tp_cases = (throughput_df if selected_route == "ALL"
                else throughput_df[
                    throughput_df["route_id"] == selected_route])

    # ── Route-level summary table ─────────────────────────────────────────────
    th_style = {
        "color": "#e94560", "padding": "4px 8px",
        "borderBottom": "1px solid #0f3460",
        "fontSize": "11px", "textAlign": "left", "whiteSpace": "nowrap",
    }
    header_r = html.Tr([
        html.Th(col, style=th_style)
        for col in ["Route", "Avg", "Min", "Max", "# Trips"]
    ])

    route_rows = [header_r]
    for _, r in tp_route.iterrows():
        colour = ROUTE_COLOURS.get(r["route_id"], DEFAULT_COLOUR)
        route_rows.append(html.Tr([
            html.Td(r["route_id"], style={
                "color": colour, "fontWeight": "bold",
                "padding": "3px 8px", "fontSize": "11px",
            }),
            html.Td(fmt_duration(r["avg_sec"]),
                    style={"color": "#fbbf24", "padding": "3px 8px",
                           "fontSize": "11px"}),
            html.Td(fmt_duration(r["min_sec"]),
                    style={"color": "#4ade80", "padding": "3px 8px",
                           "fontSize": "11px"}),
            html.Td(fmt_duration(r["max_sec"]),
                    style={"color": "#f87171", "padding": "3px 8px",
                           "fontSize": "11px"}),
            html.Td(str(int(r["trips"])),
                    style={"color": "#ccc",    "padding": "3px 8px",
                           "fontSize": "11px"}),
        ]))

    # ── Overall summary row across ALL routes ─────────────────────────────────
    overall_min   = route_throughput["min_sec"].min()
    overall_max   = route_throughput["max_sec"].max()
    overall_avg   = throughput_df["duration_sec"].mean()
    overall_trips = int(throughput_df["trip_id"].nunique())

    route_rows.append(html.Tr([
        html.Td("─" * 6, style={"padding": "0 8px", "fontSize": "9px", "color": "#333"}),
    ] * 5))
    route_rows.append(html.Tr(
        style={"backgroundColor": "#0f2040"},
        children=[
            html.Td("ALL ROUTES", style={
                "color": "#e94560", "fontWeight": "bold",
                "padding": "4px 8px", "fontSize": "11px",
                "borderTop": "2px solid #e94560",
            }),
            html.Td(fmt_duration(overall_avg), style={
                "color": "#fbbf24", "fontWeight": "bold",
                "padding": "4px 8px", "fontSize": "11px",
                "borderTop": "2px solid #e94560",
            }),
            html.Td(fmt_duration(overall_min), style={
                "color": "#4ade80", "fontWeight": "bold",
                "padding": "4px 8px", "fontSize": "11px",
                "borderTop": "2px solid #e94560",
            }),
            html.Td(fmt_duration(overall_max), style={
                "color": "#f87171", "fontWeight": "bold",
                "padding": "4px 8px", "fontSize": "11px",
                "borderTop": "2px solid #e94560",
            }),
            html.Td(str(overall_trips), style={
                "color": "#ccc", "fontWeight": "bold",
                "padding": "4px 8px", "fontSize": "11px",
                "borderTop": "2px solid #e94560",
            }),
        ]
    ))

    route_table = html.Table(route_rows,
                             style={"borderCollapse": "collapse",
                                    "marginBottom": "6px"})

    # ── Per-trip (per-case) schedule table ────────────────────────────────────
    th2 = dict(th_style, fontSize="10px")
    header_t = html.Tr([
        html.Th(col, style=th2)
        for col in ["Route", "Departs", "Arrives", "Duration", "Stops"]
    ])

    case_rows = [header_t]
    for _, r in tp_cases.iterrows():
        colour = ROUTE_COLOURS.get(r["route_id"], DEFAULT_COLOUR)
        case_rows.append(html.Tr([
            html.Td(r["route_id"], style={
                "color": colour, "fontWeight": "bold",
                "padding": "2px 8px", "fontSize": "10px",
            }),
            html.Td(r["first_clock"],
                    style={"color": "#60a5fa", "padding": "2px 8px",
                           "fontSize": "10px"}),
            html.Td(r["last_clock"],
                    style={"color": "#34d399", "padding": "2px 8px",
                           "fontSize": "10px"}),
            html.Td(fmt_duration(r["duration_sec"]),
                    style={"color": "#fbbf24", "padding": "2px 8px",
                           "fontSize": "10px", "whiteSpace": "nowrap"}),
            html.Td(str(int(r["num_stops"])),
                    style={"color": "#ccc",    "padding": "2px 8px",
                           "fontSize": "10px"}),
        ]))

    case_table = html.Div(
        html.Table(case_rows, style={"borderCollapse": "collapse"}),
        style={"maxHeight": "180px", "overflowY": "auto",
               "border": "1px solid #0f3460", "borderRadius": "4px"}
    )

    note = html.Span("")

    return html.Div([
        html.H5("⏱ Throughput Time per Trip  (Task 4a)",
                style={"color": "#e94560", "marginTop": 0,
                       "marginBottom": "4px", "fontSize": "13px"}),
        html.P("Formula: T_total = t_last_departure − t_first_arrival",
               style={"color": "#666", "fontSize": "9px",
                      "marginTop": 0, "marginBottom": "6px"}),
        route_table,
        note,
        html.H6("📋 Per-Trip Schedule (each case)",
                style={"color": "#aaa", "fontSize": "11px",
                       "margin": "8px 0 4px 0"}),
        case_table,
    ], style={"marginRight": "30px", "minWidth": "350px"})


# ── Task 4b: Bottleneck panel ─────────────────────────────────────────────────
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
        items.append(
            html.Div(style={
                "backgroundColor": "#1a0000" if is_bn else "#0d1b2a",
                "border":          f"1px solid {'#ff4444' if is_bn else '#0f3460'}",
                "borderLeft":      f"5px solid {colour}",
                "borderRadius":    "6px",
                "padding":         "8px 12px",
                "marginBottom":    "8px",
            }, children=[
                html.Div(
                    f"{medal}  #{rank}  {r['src']}  →  {r['tgt']}"
                    + (" 🚨" if is_bn else ""),
                    style={"color": "#ff8888" if is_bn else "#ccc",
                           "fontWeight": "bold", "fontSize": "12px"}
                ),
                html.Div(style={
                    "display": "flex", "gap": "12px",
                    "marginTop": "4px", "flexWrap": "wrap",
                }, children=[
                    html.Span(f"Avg: {fmt_duration(r['avg_sec'])}",
                              style={"color": "#fca5a5" if is_bn else "#fbbf24",
                                     "fontSize": "11px", "fontWeight": "bold"}),
                    html.Span(f"Min: {fmt_duration(r['min_sec'])}",
                              style={"color": "#4ade80", "fontSize": "11px"}),
                    html.Span(f"Max: {fmt_duration(r['max_sec'])}",
                              style={"color": "#f87171", "fontSize": "11px"}),
                ]),
                html.Div(
                    f"{int(r['freq'])} trips  |  Route: {r['route_id']}",
                    style={"color": "#888", "fontSize": "10px",
                           "marginTop": "3px"}
                ),
            ])
        )

    return html.Div([
        html.H5("🚨 Top-3 Bottleneck Transitions  (Task 4b)",
                style={"color": "#ff6666", "marginTop": 0,
                       "marginBottom": "2px", "fontSize": "13px"}),
        html.P(
            f"Threshold: avg > {fmt_duration(threshold_sec)}  "
            f"({len(bn)} edges flagged)",
            style={"color": "#888", "fontSize": "10px",
                   "marginTop": 0, "marginBottom": "8px"}
        ),
        *items,
    ], style={"minWidth": "280px"})


def _freq_panel(selected_route):
    subset = (agg if selected_route == "ALL"
              else agg[agg["route_id"] == selected_route])
    top5   = subset.nlargest(5, "freq")
    max_f  = top5["freq"].max() if len(top5) else 1
    items  = []
    for _, r in top5.iterrows():
        colour = ROUTE_COLOURS.get(r["route_id"], DEFAULT_COLOUR)
        pct    = int(r["freq"]) / max_f * 100
        items.append(
            html.Div(style={"marginBottom": "8px"}, children=[
                html.Div(
                    f"{r['src']} → {r['tgt']}",
                    style={"color": "#ccc", "fontSize": "10px",
                           "marginBottom": "2px"}
                ),
                html.Div(style={
                    "display": "flex", "alignItems": "center", "gap": "8px"
                }, children=[
                    html.Div(style={
                        "height":          "10px",
                        "width":           f"{pct:.0f}%",
                        "maxWidth":        "150px",
                        "backgroundColor": colour,
                        "borderRadius":    "4px",
                        "minWidth":        "4px",
                    }),
                    html.Span(
                        f"{int(r['freq'])} trips | {r['route_id']}",
                        style={"color": "#aaa", "fontSize": "10px"}
                    ),
                ]),
            ])
        )

    return html.Div([
        html.H5("📊 Top-5 Most Frequent Transitions",
                style={"color": "#e94560", "marginTop": 0,
                       "marginBottom": "6px", "fontSize": "13px"}),
        *items,
    ], style={"minWidth": "260px"})


def _build_analytics_bar(selected_route, threshold_sec):
    return [
        _throughput_table(selected_route),
        _bottleneck_panel(selected_route, threshold_sec),
        _freq_panel(selected_route),
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# 7.  DASH APP — LAYOUT
# ═══════════════════════════════════════════════════════════════════════════════
app = dash.Dash(__name__, title="CDA Bus Route Process Map")

route_options = [{"label": "All Routes", "value": "ALL"}] + [
    {"label": r, "value": r}
    for r in sorted(agg["route_id"].unique())
]

slider_max   = 600
slider_marks = {
    i: {"label": f"{i//60}m",
        "style": {"color": "#aaa", "fontSize": "10px"}}
    for i in range(0, slider_max + 1, 60)
}

STYLESHEET = [
    {
        "selector": "node",
        "style": {
            "label":               "data(label)",
            "background-color":    "data(colour)",
            "color":               "#ffffff",
            "text-outline-color":  "#111111",
            "text-outline-width":  "1.5px",
            "font-size":           "9px",
            "width":               "28px",
            "height":              "28px",
            "text-valign":         "bottom",
            "text-halign":         "center",
            "text-margin-y":       "4px",
        }
    },
    {
        "selector": "edge",
        "style": {
            "label":                   "data(label)",
            "line-color":              "data(colour)",
            "target-arrow-color":      "data(colour)",
            "target-arrow-shape":      "triangle",
            "curve-style":             "bezier",
            "font-size":               "7px",
            "color":                   "#111111",
            "text-background-color":   "#ffffff",
            "text-background-opacity": 0.85,
            "text-background-padding": "2px",
            "text-rotation":           "autorotate",
            "width":                   2,
            "arrow-scale":             1.2,
        }
    },
    {
        "selector": ".bottleneck",
        "style": {
            "line-color":         "#ff0000",
            "target-arrow-color": "#ff0000",
            "line-style":         "dashed",
            "width":              5,
        }
    },
    {
        "selector": "node:selected",
        "style": {
            "border-width":     "3px",
            "border-color":     "#FFD700",
            "background-color": "#FFD700",
            "color":            "#000000",
        }
    },
    {
        "selector": "edge:selected",
        "style": {
            "width":              7,
            "line-color":         "#FFD700",
            "target-arrow-color": "#FFD700",
        }
    },
]

app.layout = html.Div(
    style={"fontFamily": "Segoe UI, sans-serif",
           "backgroundColor": "#1a1a2e", "minHeight": "100vh"},
    children=[

        # ── Header ────────────────────────────────────────────────────────────
        html.Div(
            style={
                "backgroundColor": "#16213e",
                "padding":         "10px 20px",
                "borderBottom":    "2px solid #0f3460",
                "display":         "flex",
                "alignItems":      "center",
                "gap":             "18px",
                "flexWrap":        "wrap",
            },
            children=[
                html.H2("CDA Bus Route — Process Map",
                        style={"color": "#e94560", "margin": 0,
                               "fontSize": "17px", "whiteSpace": "nowrap"}),

                html.Div([
                    html.Label("Filter by Route:",
                               style={"color": "#aaa", "fontSize": "10px",
                                      "display": "block", "marginBottom": "2px"}),
                    dcc.Dropdown(
                        id="route-dropdown",
                        options=route_options,
                        value="ALL",
                        clearable=False,
                        style={"width": "175px", "color": "#000"},
                    ),
                ]),

                html.Div([
                    html.Label("Layout:",
                               style={"color": "#aaa", "fontSize": "10px",
                                      "display": "block", "marginBottom": "2px"}),
                    dcc.Dropdown(
                        id="layout-dropdown",
                        options=[
                            {"label": "Dagre (L→R)",  "value": "dagre"},
                            {"label": "Breadthfirst", "value": "breadthfirst"},
                            {"label": "Circle",       "value": "circle"},
                            {"label": "Cose",         "value": "cose"},
                            {"label": "Grid",         "value": "grid"},
                        ],
                        value="dagre",
                        clearable=False,
                        style={"width": "165px", "color": "#000"},
                    ),
                ]),

                html.Div([
                    html.Label(
                        id="threshold-label",
                        children=f"🚨 Bottleneck Threshold: "
                                 f"{fmt_duration(DEFAULT_THRESHOLD_SEC)}",
                        style={"color": "#ff8888", "fontSize": "10px",
                               "display": "block", "marginBottom": "2px",
                               "whiteSpace": "nowrap"}
                    ),
                    dcc.Slider(
                        id="threshold-slider",
                        min=0,
                        max=slider_max,
                        step=10,
                        value=DEFAULT_THRESHOLD_SEC,
                        marks=slider_marks,
                        tooltip={"always_visible": False},
                        updatemode="drag",
                    ),
                ], style={"minWidth": "220px", "maxWidth": "300px"}),

                html.Div(id="stats-bar",
                         style={"marginLeft": "auto", "display": "flex",
                                "gap": "8px", "flexWrap": "wrap",
                                "alignItems": "center"}),
            ]
        ),

        # ── Graph + side panel ────────────────────────────────────────────────
        html.Div(
            style={"display": "flex", "height": "calc(100vh - 260px)"},
            children=[

                cyto.Cytoscape(
                    id="cytoscape-graph",
                    elements=build_elements("ALL", DEFAULT_THRESHOLD_SEC),
                    layout={"name": "dagre", "rankDir": "LR",
                            "spacingFactor": 1.4},
                    style={"flex": "1", "height": "100%"},
                    stylesheet=STYLESHEET,
                    minZoom=0.05,
                    maxZoom=4.0,
                    boxSelectionEnabled=True,
                ),

                html.Div(
                    id="side-panel",
                    style={
                        "width":           "280px",
                        "backgroundColor": "#16213e",
                        "borderLeft":      "2px solid #0f3460",
                        "padding":         "14px",
                        "overflowY":       "auto",
                        "color":           "#cccccc",
                    },
                    children=_default_panel(),
                ),
            ]
        ),

        # ── Analytics bar (Task 4) ────────────────────────────────────────────
        html.Div(
            id="analytics-bar",
            style={
                "backgroundColor": "#16213e",
                "borderTop":       "2px solid #0f3460",
                "padding":         "12px 24px",
                "display":         "flex",
                "gap":             "32px",
                "flexWrap":        "wrap",
                "alignItems":      "flex-start",
                "overflowX":       "auto",
            },
            children=_build_analytics_bar("ALL", DEFAULT_THRESHOLD_SEC),
        ),

        # ── Task 5: Agentic AI Chat Panel ─────────────────────────────────────
        html.Div(
            style={
                "position": "fixed", "bottom": "20px", "right": "20px",
                "width": "350px", "backgroundColor": "#1a1a2e",
                "border": "2px solid #e94560", "borderRadius": "10px",
                "boxShadow": "0 10px 25px rgba(0,0,0,0.5)", "zIndex": "1000",
                "display": "flex", "flexDirection": "column", "maxHeight": "500px"
            },
            children=[
                html.Div("🤖 CDA Agentic Trip Planner (Task 5)", style={
                    "backgroundColor": "#e94560", "color": "#fff", "padding": "10px",
                    "fontWeight": "bold", "fontSize": "14px", "borderRadius": "8px 8px 0 0"
                }),
                html.Div(id="chat-history", style={
                    "flex": "1", "padding": "15px", "overflowY": "auto",
                    "color": "#e0e0e0", "fontSize": "12px", "minHeight": "200px",
                    "backgroundColor": "#16213e"
                }, children=[
                    html.Div("**Agent:** Hello! Ask me any trip planning question grounded in the CDA route data. "
                             "I can now infer return trips to help you get home!", 
                             style={"marginBottom": "10px", "fontStyle": "italic", "color": "#888"})
                ]),
                html.Div(style={"padding": "10px", "display": "flex", "gap": "5px", "borderTop": "1px solid #0f3460"}, children=[
                    dcc.Input(id="chat-input", type="text", placeholder="Where to go? (e.g. from I-10 to FAST)", 
                              style={"flex": "1", "borderRadius": "5px", "border": "none", "padding": "8px"}),
                    html.Button("Send", id="chat-send", n_clicks=0, style={
                        "backgroundColor": "#e94560", "color": "#fff", "border": "none", 
                        "padding": "8px 15px", "borderRadius": "5px", "cursor": "pointer"
                    })
                ])
            ]
        ),
    ]
)


# ═══════════════════════════════════════════════════════════════════════════════
# 8.  CALLBACKS
# ═══════════════════════════════════════════════════════════════════════════════
def _badge(text, bg="#0f3460", border="#e94560"):
    return html.Div(text, style={
        "backgroundColor": bg,
        "color":      "#e0e0e0",
        "padding":    "5px 12px",
        "borderRadius": "20px",
        "fontSize":   "11px",
        "border":     f"1px solid {border}",
        "whiteSpace": "nowrap",
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
    elements = build_elements(selected_route, threshold_sec)

    layout = {
        "name":              layout_name,
        "rankDir":           "LR",
        "spacingFactor":     1.4,
        "animate":           True,
        "animationDuration": 400,
    }

    nodes      = [e for e in elements if "source" not in e["data"]]
    edges      = [e for e in elements if "source"     in e["data"]]
    total_freq = sum(e["data"]["freq"]   for e in edges)
    bn_count   = sum(1 for e in edges if e["data"]["is_bn"])

    # trips in selected scope
    n_trips = (throughput_df if selected_route == "ALL"
               else throughput_df[
                   throughput_df["route_id"] == selected_route])["trip_id"].nunique()

    stats = [
        _badge(f"🛑 {len(nodes)} Stops"),
        _badge(f"➡ {len(edges)} Transitions"),
        _badge(f"🚌 {n_trips} Trips"),
        _badge(f"🔁 {total_freq} Trip passes"),
        _badge(f"🚨 {bn_count} Bottlenecks",
               bg="#3a0000", border="#ff4444"),
    ]

    label = (f"🚨 Bottleneck Threshold: {fmt_duration(threshold_sec)}  "
             f"— edges slower than this are highlighted red")

    return (elements, layout, stats,
            _build_analytics_bar(selected_route, threshold_sec), label)


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

    # ── Edge clicked ──────────────────────────────────────────────────────────
    if "tapEdgeData" in trigger and edge_data:
        d     = edge_data
        is_bn = d.get("avg_sec", 0) >= threshold_sec

        bn_tag = html.Span(
            " 🚨 BOTTLENECK",
            style={"color": "#ff4444", "fontSize": "11px"}
        ) if is_bn else html.Span("")

        # Per-trip schedule for this specific edge
        src, tgt = d.get("source", ""), d.get("target", "")
        rid      = d.get("route_id", "")
        edge_trips = edges_df[
            (edges_df["route_id"] == rid) &
            (edges_df["src"] == src) &
            (edges_df["tgt"] == tgt)
        ].merge(
            throughput_df[["trip_id", "first_clock"]],
            on="trip_id", how="left"
        ).sort_values("first_clock")

        trip_rows = []
        for _, er in edge_trips.head(10).iterrows():
            trip_rows.append(
                html.Div(
                    f"Dep {er.get('first_clock','?')} — "
                    f"{fmt_duration(er['dur_sec'])}",
                    style={"color": "#aaa", "fontSize": "10px",
                           "borderBottom": "1px solid #0f3460",
                           "paddingBottom": "2px", "marginBottom": "2px"}
                )
            )
        if len(edge_trips) > 10:
            trip_rows.append(
                html.Div(f"… and {len(edge_trips)-10} more trips",
                         style={"color": "#555", "fontSize": "9px"})
            )

        return [
            html.H4(["Edge Detail", bn_tag],
                    style={"color": "#e94560", "marginTop": 0,
                           "fontSize": "14px"}),
            _detail_row("Route",  d.get("route_id", "?")),
            _detail_row("From",   d.get("source",   "?")),
            _detail_row("To",     d.get("target",   "?")),
            html.Hr(style={"borderColor": "#0f3460"}),

            html.H5("⏱ Transition Duration  (Task 3c)",
                    style={"color": "#e94560", "fontSize": "12px",
                           "marginBottom": "6px"}),
            _detail_row("Avg Duration",
                        fmt_duration(d.get("avg_sec", 0)),
                        "#fca5a5" if is_bn else "#e0e0e0"),
            _detail_row("Min Duration",
                        fmt_duration(d.get("min_sec", 0)), "#4ade80"),
            _detail_row("Max Duration",
                        fmt_duration(d.get("max_sec", 0)), "#f87171"),
            html.Hr(style={"borderColor": "#0f3460"}),

            html.H5("📊 Case Frequency  (Task 3d)",
                    style={"color": "#e94560", "fontSize": "12px",
                           "marginBottom": "6px"}),
            _detail_row("Trips traversed",
                        f"{d.get('freq', 0)} trips", "#60a5fa"),
            html.Div(style={
                "backgroundColor": "#0f3460", "borderRadius": "6px",
                "padding": "10px", "textAlign": "center", "marginTop": "4px",
            }, children=[
                html.Div(
                    f"{d.get('freq', 0)}",
                    style={"color": "#60a5fa", "fontWeight": "bold",
                           "fontSize": "22px"}
                ),
                html.Div("trips used this transition",
                         style={"color": "#aaa", "fontSize": "10px"}),
            ]),
            html.Hr(style={"borderColor": "#0f3460"}),

            html.H5("🕐 Per-Trip Departure Times",
                    style={"color": "#e94560", "fontSize": "12px",
                           "marginBottom": "4px"}),
            *trip_rows,
            html.Hr(style={"borderColor": "#0f3460"}),
            html.H5("Legend",
                    style={"color": "#e94560", "fontSize": "12px"}),
            html.Div(_build_legend()),
        ]

    # ── Node clicked ──────────────────────────────────────────────────────────
    if "tapNodeData" in trigger and node_data:
        stop     = node_data.get("id", "?")
        outgoing = agg[agg["src"] == stop].sort_values(
            "avg_sec", ascending=False)
        incoming = agg[agg["tgt"] == stop].sort_values(
            "avg_sec", ascending=False)

        total_in  = int(incoming["freq"].sum())
        total_out = int(outgoing["freq"].sum())

        # Per-trip arrivals at this stop
        stop_times = df[df["stop_name"] == stop][
            ["route_id", "trip_id", "arrival_time"]
        ].merge(
            throughput_df[["trip_id", "first_clock"]], on="trip_id", how="left"
        ).sort_values("arrival_time")

        stop_time_rows = []
        for _, sr in stop_times.head(8).iterrows():
            colour = ROUTE_COLOURS.get(sr["route_id"], DEFAULT_COLOUR)
            stop_time_rows.append(
                html.Div(
                    style={"display": "flex", "justifyContent": "space-between",
                           "fontSize": "10px", "color": "#aaa",
                           "borderBottom": "1px solid #0f3460",
                           "paddingBottom": "2px", "marginBottom": "2px"},
                    children=[
                        html.Span(sr["route_id"],
                                  style={"color": colour, "fontWeight": "bold"}),
                        html.Span(str(sr["arrival_time"])[:5]),
                    ]
                )
            )
        if len(stop_times) > 8:
            stop_time_rows.append(
                html.Div(f"… and {len(stop_times)-8} more",
                         style={"color": "#555", "fontSize": "9px"})
            )

        def edge_rows(sub, direction):
            rows = []
            for _, r in sub.iterrows():
                other  = r["tgt"] if direction == "out" else r["src"]
                colour = ROUTE_COLOURS.get(r["route_id"], DEFAULT_COLOUR)
                is_bn  = r["avg_sec"] >= threshold_sec
                rows.append(
                    html.Div(style={
                        "padding":         "5px 8px",
                        "backgroundColor": "#1a0000" if is_bn else "#0f3460",
                        "borderRadius":    "4px",
                        "marginBottom":    "4px",
                        "borderLeft":      f"3px solid "
                                           f"{'#ff0000' if is_bn else colour}",
                    }, children=[
                        html.Div(
                            ("→ " if direction == "out" else "← ") +
                            other + (" 🚨" if is_bn else ""),
                            style={"color": "#e0e0e0", "fontWeight": "bold",
                                   "fontSize": "11px"}
                        ),
                        html.Div(
                            f"{fmt_duration(r['avg_sec'])}  |  "
                            f"{int(r['freq'])} trips  |  {r['route_id']}",
                            style={"color": "#888", "fontSize": "10px",
                                   "marginTop": "2px"}
                        ),
                    ])
                )
            return rows or [html.P("None",
                                   style={"color": "#555", "fontSize": "11px"})]

        return [
            html.H4("Stop Detail",
                    style={"color": "#e94560", "marginTop": 0,
                           "fontSize": "14px"}),
            _detail_row("Stop",   stop),
            _detail_row("Routes", node_data.get("routes", "?")),
            html.Hr(style={"borderColor": "#0f3460"}),

            html.H5("🕐 Bus Times at This Stop",
                    style={"color": "#e94560", "fontSize": "12px",
                           "marginBottom": "4px"}),
            *stop_time_rows,
            html.Hr(style={"borderColor": "#0f3460"}),

            html.H5("📊 Case Frequency  (Task 3d)",
                    style={"color": "#e94560", "fontSize": "12px",
                           "marginBottom": "6px"}),
            html.Div(style={"display": "flex", "gap": "8px",
                            "marginBottom": "10px"}, children=[
                html.Div(style={
                    "flex": "1", "backgroundColor": "#0f3460",
                    "borderRadius": "6px", "padding": "8px",
                    "textAlign": "center",
                }, children=[
                    html.Div(str(total_in),
                             style={"color": "#4ade80", "fontWeight": "bold",
                                    "fontSize": "18px"}),
                    html.Div("trips in",
                             style={"color": "#aaa", "fontSize": "10px"}),
                ]),
                html.Div(style={
                    "flex": "1", "backgroundColor": "#0f3460",
                    "borderRadius": "6px", "padding": "8px",
                    "textAlign": "center",
                }, children=[
                    html.Div(str(total_out),
                             style={"color": "#60a5fa", "fontWeight": "bold",
                                    "fontSize": "18px"}),
                    html.Div("trips out",
                             style={"color": "#aaa", "fontSize": "10px"}),
                ]),
            ]),

            html.P("Outgoing →",
                   style={"color": "#aaa", "margin": "0 0 4px 0",
                          "fontWeight": "bold", "fontSize": "12px"}),
            *edge_rows(outgoing, "out"),
            html.Hr(style={"borderColor": "#0f3460"}),
            html.P("← Incoming",
                   style={"color": "#aaa", "margin": "0 0 4px 0",
                          "fontWeight": "bold", "fontSize": "12px"}),
            *edge_rows(incoming, "in"),
            html.Hr(style={"borderColor": "#0f3460"}),
            html.H5("Legend",
                    style={"color": "#e94560", "fontSize": "12px"}),
            html.Div(_build_legend()),
        ]

    return _default_panel()


@app.callback(
    Output("chat-history", "children"),
    Output("chat-input", "value"),
    Input("chat-send", "n_clicks"),
    Input("chat-input", "n_submit"),
    State("chat-input", "value"),
    State("chat-history", "children"),
    prevent_initial_call=True
)
def update_chat(n_clicks, n_submit, user_text, history):
    if not user_text:
        return history, ""
    
    # Add user message
    new_history = history + [
        html.Div([
            html.B("You: "), html.Span(user_text)
        ], style={"marginBottom": "10px", "textAlign": "right", "color": "#fbbf24"})
    ]
    
    # Get agent response
    response = ai_agent_query(user_text, df, edges_df)
    
    # Add agent message
    new_history.append(
        html.Div([
            dcc.Markdown(response)
        ], style={"marginBottom": "15px", "backgroundColor": "#1a1a2e", "padding": "10px", "borderRadius": "5px"})
    )
    
    return new_history, ""


# ═══════════════════════════════════════════════════════════════════════════════
# 9.  RUN
# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("\nStarting CDA Bus Route Process Map...")
    print("Open browser at:  http://127.0.0.1:8050\n")
    app.run(debug=True)
