import pandas as pd
import re
import os
import pm4py
from pm4py.algo.discovery.dfg import algorithm as dfg_discovery
from pm4py.visualization.dfg import visualizer as dfg_visualization
from pm4py.objects.conversion.log import converter as log_converter
from pm4py.objects.log.importer.xes import importer as xes_importer

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_CSV  = os.path.join(BASE_DIR, "data", "routes.csv")
CLEAN_CSV  = os.path.join(BASE_DIR, "data", "routes_clean.csv")
OUTPUT_XES = os.path.join(BASE_DIR, "data", "routes.xes")
OUTPUT_PNG = os.path.join(BASE_DIR, "data", "dfg_output.png")

# ── 1. Load CSV ────────────────────────────────────────────────────────────────
df = pd.read_csv(INPUT_CSV)
print(f"Loaded CSV: {len(df)} rows, {df['trip_id'].nunique()} unique trips")

# ── 2. Fix time columns ────────────────────────────────────────────────────────
def fix_time(value):
    if pd.isna(value):
        return None
    value = str(value)
    match = re.search(r'\d{1,2}:\d{2}:\d{2}', value)
    if match:
        return match.group(0)
    match = re.search(r'\d{1,2}:\d{2}', value)
    if match:
        return match.group(0) + ":00"
    return None

df["arrival_time"]   = df["arrival_time"].apply(fix_time)
df["departure_time"] = df["departure_time"].apply(fix_time)

# ── 3. Clean stop names ────────────────────────────────────────────────────────
df["stop_name"] = df["stop_name"].astype(str)
df["stop_name"] = df["stop_name"].str.replace(r'\d{1,2}:\d{2}(:\d{2})?', '', regex=True)
df["stop_name"] = df["stop_name"].str.replace(r'\s+', ' ', regex=True).str.strip()

# ── 4. Drop rows with missing critical fields ──────────────────────────────────
df = df.dropna(subset=["arrival_time", "departure_time", "stop_name"])

# ── 5. Build timestamp ────────────────────────────────────────────────────────
df["time:timestamp"] = pd.to_datetime(
    "2024-01-01 " + df["arrival_time"],
    errors="coerce"
).dt.tz_localize("Asia/Karachi")

df = df.dropna(subset=["time:timestamp"])

# ── 6. Ensure trip_id is clean string ─────────────────────────────────────────
df["trip_id"] = df["trip_id"].astype(str).str.strip()

# ── 7. Sort correctly ──────────────────────────────────────────────────────────
df = df.sort_values(by=["trip_id", "stop_sequence", "time:timestamp"])

# ── 8. Save clean CSV ──────────────────────────────────────────────────────────
df.to_csv(CLEAN_CSV, index=False)
print(f"Clean CSV saved: {len(df)} rows, {df['trip_id'].nunique()} unique trips")

# ── 9. Build XES dataframe ────────────────────────────────────────────────────
df_xes = df[["trip_id", "stop_name", "time:timestamp"]].copy()
df_xes = df_xes.rename(columns={
    "trip_id":   "case:concept:name",
    "stop_name": "concept:name"
})
df_xes["case:concept:name"] = df_xes["case:concept:name"].astype(str)
df_xes = df_xes.sort_values(by=["case:concept:name", "time:timestamp"])

print(f"\nXES prep check:")
print(f"  Unique cases (trips) : {df_xes['case:concept:name'].nunique()}")
print(f"  Total events (stops) : {len(df_xes)}")

# ── 10. Convert DataFrame → EventLog object directly (bypass read_xes issue) ──
event_log_df = pm4py.format_dataframe(
    df_xes,
    case_id="case:concept:name",
    activity_key="concept:name",
    timestamp_key="time:timestamp"
)

# Convert to proper EventLog object NOW, before writing
log = log_converter.apply(
    event_log_df,
    variant=log_converter.Variants.TO_EVENT_LOG
)

print(f"\nEventLog object check (before writing XES):")
print(f"  Traces (trips)  : {len(log)}")
print(f"  Events (stops)  : {sum(len(trace) for trace in log)}")

# ── 11. Write XES using the EventLog object ────────────────────────────────────
from pm4py.objects.log.exporter.xes import exporter as xes_exporter
xes_exporter.apply(log, OUTPUT_XES)
print(f"\nXES file written: {OUTPUT_XES}")

# ── 12. Read back XES properly using xes_importer (not pm4py.read_xes) ─────────
log_verified = xes_importer.apply(OUTPUT_XES)

num_traces = len(log_verified)
num_events = sum(len(trace) for trace in log_verified)

print(f"\nXES Validation (read back):")
print(f"  Traces (trips)  : {num_traces}")
print(f"  Events (stops)  : {num_events}")
print(f"  Avg stops/trip  : {num_events / num_traces:.1f}")

# Sanity check — print first trace
first_trace = log_verified[0]
print(f"\n  First trace ID  : {first_trace.attributes.get('concept:name', '?')}")
print(f"  Stops in trace  : {len(first_trace)}")
for event in first_trace:
    print(f"    -> {event['concept:name']}  @  {event['time:timestamp']}")

# ── 13. Discover DFG ──────────────────────────────────────────────────────────
print("\nDiscovering DFG...")
dfg = dfg_discovery.apply(log_verified)

# ── 14. Save DFG as PNG ───────────────────────────────────────────────────────
parameters = {
    dfg_visualization.Variants.FREQUENCY.value.Parameters.FORMAT: "png"
}

gviz = dfg_visualization.apply(
    dfg,
    log=log_verified,
    variant=dfg_visualization.Variants.FREQUENCY,
    parameters=parameters
)

dfg_visualization.save(gviz, OUTPUT_PNG)
print(f"\nDFG saved as PNG: {OUTPUT_PNG}")

try:
    os.startfile(OUTPUT_PNG)
except Exception:
    print("Open the PNG manually from the path above.")