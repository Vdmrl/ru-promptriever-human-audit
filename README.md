# Argilla Human Audit for ru-Promptriever

## 🚀 Quick Start for Annotators

Assuming Docker Desktop and Git are installed and running, just follow these steps:

1. **Pull the latest updates and start the database:**
   ```powershell
   git pull
   docker compose up -d
   ```
2. **Open the interface:**
   Go to: [http://localhost:6900](http://localhost:6900) in your browser.
   * Login: `daria` (or `vladimir`)
   * Password: `password`
3. **Annotate all 64 records** (click Submit for each).
4. **Export the results:**
   When you are done (64/64), run this in your terminal:
   ```powershell
   docker compose run --rm setup python scripts/export_annotations.py
   ```
5. **Save the file:**
   The script will generate a file at `data/exports/annotations.jsonl`.

---

## 1. For Annotators

### Prerequisites

You only need:
1. **Docker Desktop** (must be installed and running)
2. **Git**

To verify Docker is installed and running, run in your terminal:
```bash
docker --version
docker compose version
```

### Quick Start

1. Clone the repository and navigate into the folder:
```bash
git clone https://github.com/Vdmrl/ru-promptriever-human-audit
cd ru-promptriever-human-audit
```

2. Start the Argilla server:
```bash
docker compose up -d --build
```
Wait approximately 1 minute for all containers to initialize.

3. Set up the dataset and users (only required on the first launch):
```bash
docker compose run --rm tools python scripts/setup_argilla.py
```

4. Open the Argilla login page in your browser:
[http://localhost:6900](http://localhost:6900)

5. Log in using your assigned annotator account:
- **Username**: `daria` or `vladimir`
- **Password**: `password` (default password)

> [!NOTE]
> All default passwords (for the administrator and the annotators) are set to `password` by default to simplify local runs. If you want to customize them, create a `.env` file next to `docker-compose.yml` prior to starting the containers:
> ```dotenv
> ARGILLA_OWNER_PASSWORD=new-owner-password
> ARGILLA_DARIA_PASSWORD=new-daria-password
> ARGILLA_VLADIMIR_PASSWORD=new-vladimir-password
> ```

### Annotation Guidelines

For each query record, you will be presented with:
1. **Query**: The final query string.
2. **Positive passage**: The expected positive document.
3. **Instruction**: The search instruction constraint.
4. **Four documents**: Shown in randomized order.

For each example, answer the following mandatory questions:
- **Query Acceptable**: Is the query written in understandable and acceptable Russian? (Yes / No)
- **Passage Acceptable**: Is the positive passage written in understandable and coherent Russian? (Yes / No)
- **Document Roles**: For each of the 4 documents, choose exactly one option:
  - `1`: The document does not answer the query.
  - `2`: The document answers the query but violates the instruction.
  - `3`: The document answers the query and satisfies the instruction.

*Note: The documents are blinded and shuffled. Do not try to guess which document was originally positive or negative.*

### Saving & Exporting Results

- If you cannot finish all examples in one session, click **Save as Draft** in the UI. Your progress is saved in persistent Docker volumes and will not be lost.
- To pause the server, run:
```bash
docker compose stop
```
- To resume the server, run:
```bash
docker compose start
```
- Once all records are annotated, export the results:
```bash
docker compose run --rm tools python scripts/export_annotations.py --output-dir data/exports
```
This script saves the results to:
`data/exports/annotations.jsonl`

Please send `annotations.jsonl` to the project owner. Do not share your `.env` or Docker volumes.

---

## 2. For Project Owners: Sample Preparation

The evaluation sample is pre-prepared from the final parquet dataset. If you need to regenerate the evaluation split, use the preparation script:
```bash
python scripts/prepare_from_final_dataset.py --dataset-dir <path_to_final_parquet_dataset> --out-dir data
```
This generates:
- `data/public_items.jsonl`: The public blinded split.
- `data/private_manifest.jsonl`: Ground-truth labels and document roles (**do not share this file with annotators**).
- `data/sample_metadata.json`: Metadata tracking of dataset hashes.

---

## Project Structure

- `docker-compose.yml`: Launches Argilla Server, PostgreSQL, Elasticsearch, Redis, and a tools container.
- `scripts/setup_argilla.py`: Registers workspaces, configures schema, creates annotator users, and uploads the dataset.
- `scripts/export_annotations.py`: Pulls completed annotator responses and saves them in CSV/JSONL formats.
- `data/public_items.jsonl`: Pre-randomized and blinded quality evaluation dataset.
