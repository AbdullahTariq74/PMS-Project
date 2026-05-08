import pandas as pd
import collections
import re
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_CSV  = os.path.join(BASE_DIR, "data", "routes_clean.csv")
REPORT_DIR = os.path.join(BASE_DIR, "report")
os.makedirs(REPORT_DIR, exist_ok=True)

ROUTE_COLOURS = {
    "FR-01": "#e6194b", "FR-03A": "#3cb44b", "FR-04": "#ffe119",
    "FR-07": "#4363d8", "FR-08A": "#f58231", "FR-09": "#911eb4",
    "FR-11": "#f032e6", "FR-15":  "#bfef45",
}

MEMBERS = [
    {
        "name":    "Member 1",
        "address": "Street 15, I-10/4, Islamabad",
        "area":    "I-10 Sector",
        "stop":    "PTCL I-10",
    },
    {
        "name":    "Member 2",
        "address": "Near Khanna Pul Interchange, Islamabad",
        "area":    "Khanna Pul",
        "stop":    "Khanna Pul",
    },
    {
        "name":    "Member 3",
        "address": "House 7, Street 4, H-8/4, Islamabad",
        "area":    "H-8 Sector",
        "stop":    "PAEC General Hospital",
    },
    {
        "name":    "Member 4",
        "address": "House 22, H-8/1, Islamabad",
        "area":    "H-8 Sector",
        "stop":    "NORI Hospital",
    },
]


def _parse_hms(s):
    m = re.match(r"(\d{1,2}):(\d{2}):(\d{2})", str(s).strip())
    if m:
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
    return None


def fmt_dur(seconds):
    seconds = max(0, int(round(seconds)))
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}h {m}m"
    if m > 0:
        return f"{m} min {s} sec"
    return f"{s} sec"


def build_graph(df):
    dur_map  = collections.defaultdict(list)
    edge_set = []
    for trip_id, group in df.groupby("trip_id"):
        group    = group.sort_values("stop_sequence").reset_index(drop=True)
        route_id = group["route_id"].iloc[0]
        for i in range(len(group) - 1):
            src   = group.loc[i,   "stop_name"]
            tgt   = group.loc[i+1, "stop_name"]
            arr_s = _parse_hms(group.loc[i+1, "arrival_time"])
            dep_s = _parse_hms(group.loc[i,   "departure_time"])
            dur   = max(0, arr_s - dep_s) if (arr_s and dep_s) else 180
            dur_map[(src, tgt, route_id)].append(dur)
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
        adj[tgt].append((src, rid, "reverse", d))   # bidirectional
    return adj, avg_dur


def find_path(start_stop, end_stop, adj):
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


def group_legs(path):
    """Collapse consecutive same-route stops into legs."""
    if not path:
        return []
    legs      = []
    leg_rid   = path[0][2]
    leg_dir   = path[0][3]
    leg_start = path[0][0]
    leg_end   = path[0][1]
    leg_dur   = path[0][4]
    for src, tgt, rid, direction, dur in path[1:]:
        if rid == leg_rid and direction == leg_dir:
            leg_end  = tgt
            leg_dur += dur
        else:
            legs.append((leg_start, leg_end, leg_rid, leg_dir, leg_dur))
            leg_rid, leg_dir = rid, direction
            leg_start, leg_end, leg_dur = src, tgt, dur
    legs.append((leg_start, leg_end, leg_rid, leg_dir, leg_dur))
    return legs


def draw_route_diagram(member, legs, total_sec, output_path):
    """
    Draw a horizontal route diagram for a member and save as PNG.
    """
    # Collect stops in order (unique sequence)
    stops = []
    for ls, le, rid, direction, dur in legs:
        if not stops or stops[-1] != ls:
            stops.append(ls)
        stops.append(le)

    n = len(stops)
    fig_w = max(12, n * 2.2)
    fig, ax = plt.subplots(figsize=(fig_w, 4))
    fig.patch.set_facecolor("#1a1a2e")
    ax.set_facecolor("#1a1a2e")
    ax.axis("off")

    xs = [i * 2.0 for i in range(n)]
    y  = 1.5

    # Draw home address block at the very left
    ax.text(xs[0] - 0.05, y + 0.85, member["address"],
            ha="center", va="bottom", fontsize=8,
            color="#aaaaaa", style="italic",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="#0f3460",
                      edgecolor="#e94560", linewidth=1))
    ax.annotate("", xy=(xs[0], y + 0.28), xytext=(xs[0], y + 0.62),
                arrowprops=dict(arrowstyle="->", color="#888888", lw=1.2))

    # Draw leg-coloured arrows between stops
    stop_to_x = {s: xs[i] for i, s in enumerate(stops)}
    drawn_legs = set()
    stop_idx = 0
    for ls, le, rid, direction, dur in legs:
        x0 = stop_to_x[ls]
        x1 = stop_to_x[le]
        colour = ROUTE_COLOURS.get(rid, "#aaaaaa")
        dir_label = "Return" if direction == "reverse" else "Forward"
        mid_x = (x0 + x1) / 2.0
        leg_key = (ls, le)
        if leg_key not in drawn_legs:
            drawn_legs.add(leg_key)
            ax.annotate("",
                        xy=(x1 - 0.18, y),
                        xytext=(x0 + 0.18, y),
                        arrowprops=dict(arrowstyle="-|>",
                                        color=colour,
                                        lw=3.0,
                                        mutation_scale=18))
            ax.text(mid_x, y + 0.22,
                    f"{rid} ({dir_label})\n~{fmt_dur(dur)}",
                    ha="center", va="bottom", fontsize=8, color=colour,
                    fontweight="bold")

    # Draw stop circles
    for i, stop in enumerate(stops):
        x = xs[i]
        is_start = (stop == stops[0])
        is_end   = (stop == stops[-1])
        colour = "#00e676" if is_start else ("#e94560" if is_end else "#ffffff")
        size   = 160 if (is_start or is_end) else 100
        ax.scatter([x], [y], s=size, color=colour, zorder=5, linewidths=2,
                   edgecolors="#111111")
        ax.text(x, y - 0.28, stop, ha="center", va="top",
                fontsize=7.5, color="#cccccc",
                rotation=30, rotation_mode="anchor")

    # Title
    total_min = int(total_sec // 60)
    ax.set_title(
        f"{member['name']}   |   Home: {member['address']}   |   "
        f"Nearest Stop: {member['stop']}   |   Est. Time: ~{total_min} min",
        fontsize=10, color="#e94560", fontweight="bold", pad=12,
        loc="center"
    )

    # Legend
    seen_rids = {r for _, _, r, _, _ in legs}
    patches = [mpatches.Patch(color=ROUTE_COLOURS.get(r, "#aaa"), label=r)
               for r in sorted(seen_rids)]
    ax.legend(handles=patches, loc="lower right", fontsize=8,
              facecolor="#0f3460", edgecolor="#e94560", labelcolor="#ffffff")

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close()
    print(f"  Saved: {os.path.basename(output_path)}")


def main():
    df  = pd.read_csv(INPUT_CSV)
    adj, _ = build_graph(df)
    target  = "FAST University"

    print("=" * 65)
    print("  Task 6: Personal Route Maps — Home Address to FAST University")
    print("=" * 65)

    for m in MEMBERS:
        print(f"\nMember  : {m['name']}")
        print(f"Address : {m['address']}")
        print(f"Area    : {m['area']}")
        print(f"Stop    : {m['stop']}")

        path = find_path(m["stop"], target, adj)
        if not path:
            print("Result  : No route found in dataset.")
            print("-" * 65)
            continue

        total_sec = sum(dur for _, _, _, _, dur in path)
        legs      = group_legs(path)

        leg_parts = []
        for ls, le, rid, direction, dur in legs:
            d_label = "Return" if direction == "reverse" else "Forward"
            leg_parts.append(f"{ls} --[{rid} {d_label}]--> {le} (~{fmt_dur(dur)})")

        print(f"Route   : {' | '.join(leg_parts)}")
        print(f"Est.    : ~{fmt_dur(total_sec)}")

        # Generate route diagram PNG
        safe_name = m["name"].replace(" ", "_")
        out_png   = os.path.join(REPORT_DIR, f"task6_{safe_name}_route.png")
        draw_route_diagram(m, legs, total_sec, out_png)

        print("-" * 65)

    print("\nAll route diagrams saved to:", REPORT_DIR)


if __name__ == "__main__":
    main()
