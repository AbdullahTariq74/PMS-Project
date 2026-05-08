import pandas as pd
import collections
import os

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR = r"C:\Users\abdta\Desktop\PMS Project\Project"
INPUT_CSV = os.path.join(BASE_DIR, "data", "routes_clean.csv")

def find_path(start_stop, end_stop, df):
    # Build edges
    records = []
    for trip_id, group in df.groupby("trip_id"):
        group = group.sort_values("stop_sequence").reset_index(drop=True)
        for i in range(len(group) - 1):
            records.append({
                "src": group.loc[i, "stop_name"],
                "tgt": group.loc[i+1, "stop_name"],
                "rid": group.loc[i, "route_id"]
            })
    
    edges_df = pd.DataFrame(records).drop_duplicates()
    
    adj = collections.defaultdict(list)
    for _, row in edges_df.iterrows():
        adj[row['src']].append((row['tgt'], row['rid']))

    queue = collections.deque([(start_stop, [])])
    visited = {start_stop}

    while queue:
        curr, path = queue.popleft()
        if curr == end_stop:
            return path

        for tgt, rid in adj.get(curr, []):
            if tgt not in visited:
                visited.add(tgt)
                queue.append((tgt, path + [(curr, tgt, rid)]))
    return None

def main():
    df = pd.read_csv(INPUT_CSV)
    
    members = [
        {"name": "Member 1", "area": "I-10", "stop": "PTCL I-10"},
        {"name": "Member 2", "area": "Khanna Pul", "stop": "Khanna Pul"},
        {"name": "Member 3", "area": "H-8", "stop": "PAEC General Hospital"},
        {"name": "Member 4", "area": "H-8", "stop": "PAEC General Hospital"}
    ]
    
    target = "FAST University"
    
    print("=== Task 6: Personal Route Maps ===\n")
    
    for m in members:
        print(f"Member: {m['name']}")
        print(f"Home Area: {m['area']}")
        print(f"Nearest Stop: {m['stop']}")
        
        path = find_path(m['stop'], target, df)
        
        if path:
            print("Route Trace:")
            trace_str = m['stop']
            for s, t, rid in path:
                trace_str += f" --({rid})--> {t}"
            print(trace_str)
            # Estimate time (avg duration from data if we had it here, but let's just print trace)
            print(f"Estimated Time: ~{len(path)*3} min") # Rough estimate
        else:
            print("No direct route found in dataset.")
        print("-" * 30)

if __name__ == "__main__":
    main()
