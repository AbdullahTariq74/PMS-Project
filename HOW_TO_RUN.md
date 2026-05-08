# How to Run — PMS Project

## Requirements

```
pip install pandas pdfplumber pm4py dash dash-cytoscape matplotlib
```

## Step-by-step

**Step 1 — Extract raw data from PDFs**
```
python Project/code/Task_01.py
```
Output: `data/routes.csv`

**Step 2 — Clean data and build XES log**
```
python Project/code/Task_02.py
```
Outputs: `data/routes_clean.csv`, `data/routes.xes`, `data/dfg_output.png`

**Step 3 — Launch the interactive dashboard (Tasks 3, 4, 5 & 6 GUI)**
```
python Project/code/Task_03_04.py
```
Then open `http://127.0.0.1:8050` in your browser.

- Process map, filters, and detail panels → main screen
- Performance analytics (throughput, bottlenecks, frequency) → scroll down
- AI Trip Planner → click "🤖 AI Planner" button in the header
- Personal Routes overlay → click "📍 Personal Routes" button in the header

**Step 4 — Generate Task 6 route diagram PNGs (optional, standalone)**
```
python Project/code/Task_06.py
```
Outputs: `report/task6_Member_1_route.png` through `report/task6_Member_4_route.png`

## Testing the AI Agent (Task 5)

With the dashboard running, click "🤖 AI Planner" and try these queries:

| Query type | Example |
|:-----------|:--------|
| Trip planning | `How do I get from Khanna Pul to FAST University?` |
| Route info | `Tell me about FR-01` |
| Stop info | `What routes serve I-10?` |
| Journey time | `How long does FR-09 take?` |
| Next bus | `When is the next bus from PTCL I-10?` |
