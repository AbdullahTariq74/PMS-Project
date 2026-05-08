import pandas as pd
import collections
import re
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_CSV = os.path.join(BASE_DIR, "data", "routes_clean.csv")


def _parse_hms(s):
    m = re.match(r"(\d{1,2}):(\d{2}):(\d{2})", str(s).strip())
    if m:
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
    return None


def fmt_duration(seconds):
    seconds = max(0, int(round(seconds)))
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}h {m}m {s}s"
    if m > 0:
        return f"{m} min {s} sec"
    return f"{s} sec"


def build_graph(df):
    """
    Build a bidirectional adjacency list with average durations.
    Forward edges come from the PDF timetables.
    Reverse edges are synthesised so that return trips can be planned
    (the PDFs only contain the forward direction).
    Returns: adj dict  { stop: [(next_stop, route_id, direction, avg_sec), ...] }
    """
    dur_map = collections.defaultdict(list)
    edge_set = []

    for trip_id, group in df.groupby("trip_id"):
        group = group.sort_values("stop_sequence").reset_index(drop=True)
        route_id = group["route_id"].iloc[0]
        for i in range(len(group) - 1):
            src = group.loc[i,   "stop_name"]
            tgt = group.loc[i+1, "stop_name"]
            arr_s = _parse_hms(group.loc[i+1, "arrival_time"])
            dep_s = _parse_hms(group.loc[i,   "departure_time"])
            dur   = max(0, arr_s - dep_s) if (arr_s and dep_s) else 180
            key   = (src, tgt, route_id)
            dur_map[key].append(dur)
            edge_set.append((src, tgt, route_id))

    avg_dur = {k: sum(v) / len(v) for k, v in dur_map.items()}

    adj = collections.defaultdict(list)
    seen = set()
    for src, tgt, rid in edge_set:
        if (src, tgt, rid) in seen:
            continue
        seen.add((src, tgt, rid))
        d = avg_dur.get((src, tgt, rid), 180)
        adj[src].append((tgt, rid, "forward", d))
        # Synthetic return edge — PDFs only have forward schedules
        adj[tgt].append((src, rid, "reverse", d))

    return adj


def find_path(start_stop, end_stop, adj):
    """BFS over the bidirectional graph; returns list of (src, tgt, route_id, direction, dur_sec)."""
    if start_stop not in adj and end_stop not in adj:
        return None
    queue   = collections.deque([(start_stop, [])])
    visited = {start_stop}
    while queue:
        curr, path = queue.popleft()
        if curr == end_stop:
            return path
        for tgt, rid, direction, dur in adj.get(curr, []):
            if tgt not in visited:
                visited.add(tgt)
                queue.append((tgt, path + [(curr, tgt, rid, direction, dur)]))
    return None


def main():
    df = pd.read_csv(INPUT_CSV)

    adj = build_graph(df)
    target = "FAST University"

    members = [
        {"name": "Member 1", "area": "I-10",       "stop": "PTCL I-10"},
        {"name": "Member 2", "area": "Khanna Pul",  "stop": "Khanna Pul"},
        {"name": "Member 3", "area": "H-8",          "stop": "PAEC General Hospital"},
        {"name": "Member 4", "area": "H-8",          "stop": "NORI Hospital"},
    ]

    print("=" * 55)
    print("  Task 6: Personal Route Maps — Home to FAST University")
    print("=" * 55)

    for m in members:
        print(f"\nMember : {m['name']}")
        print(f"Area   : {m['area']}")
        print(f"Stop   : {m['stop']}")

        path = find_path(m["stop"], target, adj)

        if path:
            total_sec = sum(dur for _, _, _, _, dur in path)
            print(f"Route  :", end=" ")

            # Group consecutive stops on the same route+direction into legs
            legs = []
            if path:
                leg_rid, leg_dir = path[0][2], path[0][3]
                leg_start        = path[0][0]
                leg_end          = path[0][1]
                leg_dur          = path[0][4]
                for src, tgt, rid, direction, dur in path[1:]:
                    if rid == leg_rid and direction == leg_dir:
                        leg_end  = tgt
                        leg_dur += dur
                    else:
                        legs.append((leg_start, leg_end, leg_rid, leg_dir, leg_dur))
                        leg_rid, leg_dir = rid, direction
                        leg_start = src
                        leg_end   = tgt
                        leg_dur   = dur
                legs.append((leg_start, leg_end, leg_rid, leg_dir, leg_dur))

            parts = []
            for ls, le, rid, direction, dur in legs:
                d_label = "Return" if direction == "reverse" else "Forward"
                parts.append(f"{ls} --[{rid} {d_label}]--> {le} (~{fmt_duration(dur)})")
            print(" | ".join(parts))
            print(f"Est.   : ~{fmt_duration(total_sec)} total")
        else:
            print("Result : No route found in dataset.")

        print("-" * 55)


if __name__ == "__main__":
    main()
