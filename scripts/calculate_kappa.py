import argparse
import json
from pathlib import Path
from sklearn.metrics import cohen_kappa_score

def load_annotations(path, target_username):
    user_data = {}
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            if not line.strip(): continue
            row = json.loads(line)
            # Only consider completed records
            if row.get("completed", False) and row.get("username") == target_username:
                user_data[row["record_id"]] = row["responses"]
    return user_data

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--vladimir", required=True, help="Path to Vladimir's JSONL")
    parser.add_argument("--daria", required=True, help="Path to Daria's JSONL")
    args = parser.parse_args()

    vladimir_data = load_annotations(args.vladimir, "vladimir")
    daria_data = load_annotations(args.daria, "daria")

    common_ids = set(vladimir_data.keys()).intersection(set(daria_data.keys()))
    print(f"Found {len(common_ids)} common annotated records.")

    if not common_ids:
        print("No overlapping records to calculate Kappa.")
        return

    # Extract answers for document roles (we have 4 documents per record)
    vladimir_roles = []
    daria_roles = []

    for rid in common_ids:
        v_resp = vladimir_data[rid]
        d_resp = daria_data[rid]
        for i in range(1, 5):
            q_name = f"document_{i}_role"
            if q_name in v_resp and q_name in d_resp:
                vladimir_roles.append(v_resp[q_name])
                daria_roles.append(d_resp[q_name])

    print(f"Total overlapping document evaluations: {len(vladimir_roles)}")
    
    if len(vladimir_roles) > 0:
        kappa = cohen_kappa_score(vladimir_roles, daria_roles)
        print(f"Cohen's Kappa (Document Roles): {kappa:.4f}")
    else:
        print("Not enough data to calculate Kappa.")

if __name__ == "__main__":
    main()
