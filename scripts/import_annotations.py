import argparse
import json
import os
import argilla as rg

def main():
    parser = argparse.ArgumentParser(description="Import annotations back to Argilla")
    parser.add_argument("--input", required=True, help="Path to annotations JSONL")
    args = parser.parse_args()

    client = rg.Argilla(
        api_url=os.getenv("ARGILLA_API_URL", "http://localhost:6900"),
        api_key=os.getenv("ARGILLA_API_KEY", "argilla.apikey")
    )
    
    dataset = client.datasets(
        name=os.getenv("ARGILLA_DATASET", "ru-promptriever-human-audit"), 
        workspace=os.getenv("ARGILLA_WORKSPACE", "default")
    )

    import_data = {}
    with open(args.input, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip(): continue
            row = json.loads(line)
            # Format responses correctly for Argilla 2.0 SDK
            formatted_responses = {}
            for q_name, value in row["responses"].items():
                formatted_responses[q_name] = [{"value": value}]
            import_data[row["record_id"]] = formatted_responses

    # Fetch existing records and add their fields and responses
    records_to_update = []
    for record in dataset.records():
        if str(record.id) in import_data:
            records_to_update.append({
                "id": str(record.id),
                "responses": import_data[str(record.id)]
            })

    if records_to_update:
        # In Argilla 2.0, updating might require fields, let's include them just in case
        try:
            dataset.records.log(records_to_update)
            print(f"Успешно импортировано {len(records_to_update)} записей обратно в базу!")
        except Exception as e:
            # Fallback: update record objects directly if supported
            updated = []
            for r in dataset.records():
                if str(r.id) in import_data:
                    # Append new responses to existing ones if any
                    r_dict = import_data[str(r.id)]
                    # Create a new dict with fields and responses
                    updated.append({
                        "id": str(r.id),
                        "fields": getattr(r, "fields", {}),
                        "responses": r_dict
                    })
            dataset.records.log(updated)
            print(f"Успешно импортировано {len(updated)} записей обратно в базу (через Fallback)!")
    else:
        print("Совпадений по ID не найдено, нечего обновлять.")

if __name__ == "__main__":
    main()
