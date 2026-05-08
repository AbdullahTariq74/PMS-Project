import pdfplumber
import pandas as pd
import re
import os

# 🔹 Base project path (adjust if needed)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PDF_FOLDER = os.path.join(BASE_DIR, "data", "raw_pdfs")
OUTPUT_CSV = os.path.join(BASE_DIR, "data", "routes.csv")


def extract_route_data(pdf_path):
    route_id = os.path.basename(pdf_path).split("_")[0]

    all_rows = []

    with pdfplumber.open(pdf_path) as pdf:
        text = ""
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"

    # Split into trips
    trips = re.split(r'Trip ID\s+Start Time', text)

    for trip in trips[1:]:
        lines = trip.strip().split("\n")

        # Extract trip_id
        trip_id_match = re.search(r'(\d+-\d+)', lines[0])
        if not trip_id_match:
            continue

        trip_id = trip_id_match.group(1)
        stop_sequence = 1

        for line in lines:
            parts = line.split()

            if len(parts) >= 3:
                try:
                    arrival_time = parts[-2]
                    departure_time = parts[-1]

                    if ":" in arrival_time and ":" in departure_time:
                        stop_name = " ".join(parts[:-2])

                        all_rows.append({
                            "route_id": route_id,
                            "trip_id": trip_id,
                            "stop_sequence": stop_sequence,
                            "stop_name": stop_name,
                            "arrival_time": arrival_time,
                            "departure_time": departure_time
                        })

                        stop_sequence += 1

                except:
                    continue

    return pd.DataFrame(all_rows)


def main():
    all_data = []

    # Loop through all PDFs in folder
    for file in os.listdir(PDF_FOLDER):
        if file.endswith(".pdf"):
            pdf_path = os.path.join(PDF_FOLDER, file)
            print(f"Processing: {file}")

            df = extract_route_data(pdf_path)
            all_data.append(df)

    # Combine all routes
    final_df = pd.concat(all_data, ignore_index=True)

    # Save to CSV
    final_df.to_csv(OUTPUT_CSV, index=False)

    print("\nroutes.csv created at:")
    print(OUTPUT_CSV)
    print(f"Total rows: {len(final_df)}")


if __name__ == "__main__":
    main()