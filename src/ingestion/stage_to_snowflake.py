"""Load Synthea CSVs and the diabetes trial extract into HEALTHCARE_LAKEHOUSE.BRONZE."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import snowflake.connector
from dotenv import load_dotenv
from snowflake.connector.errors import ProgrammingError
from snowflake.connector.pandas_tools import write_pandas

load_dotenv()

BASE_DIR = Path(__file__).resolve().parents[2]
SYNTHEA_DIR = BASE_DIR / "data" / "raw" / "synthea"
TRIALS_FILE = BASE_DIR / "data" / "raw" / "trials" / "recruiting_diabetes_trials.json"

CSV_TABLES: dict[str, Path] = {
    "RAW_PATIENTS": SYNTHEA_DIR / "patients.csv",
    "RAW_OBSERVATIONS": SYNTHEA_DIR / "observations.csv",
    "RAW_CONDITIONS": SYNTHEA_DIR / "conditions.csv",
    "RAW_MEDICATIONS": SYNTHEA_DIR / "medications.csv",
}

EXPECTED_COLUMNS: dict[str, set[str]] = {
    "RAW_PATIENTS": {
        "ID",
        "BIRTHDATE",
        "DEATHDATE",
        "SSN",
        "DRIVERS",
        "PASSPORT",
        "PREFIX",
        "FIRST",
        "LAST",
        "SUFFIX",
        "MAIDEN",
        "MARITAL",
        "RACE",
        "ETHNICITY",
        "GENDER",
        "BIRTHPLACE",
        "ADDRESS",
        "CITY",
        "STATE",
        "COUNTY",
        "ZIP",
        "LAT",
        "LON",
        "HEALTHCARE_EXPENSES",
        "HEALTHCARE_COVERAGE",
    },
    "RAW_OBSERVATIONS": {
        "DATE",
        "PATIENT",
        "ENCOUNTER",
        "CODE",
        "DESCRIPTION",
        "VALUE",
        "UNITS",
        "TYPE",
    },
    "RAW_CONDITIONS": {
        "START",
        "STOP",
        "PATIENT",
        "ENCOUNTER",
        "CODE",
        "DESCRIPTION",
    },
    "RAW_MEDICATIONS": {
        "START",
        "STOP",
        "PATIENT",
        "PAYER",
        "ENCOUNTER",
        "CODE",
        "DESCRIPTION",
        "BASE_COST",
        "PAYER_COVERAGE",
        "DISPENSES",
        "TOTALCOST",
        "REASONCODE",
        "REASONDESCRIPTION",
    },
}

TRIAL_KEYS = {
    "nct_id",
    "brief_title",
    "phase",
    "min_age",
    "max_age",
    "criteria_raw_text",
}


def require_snowflake_env() -> None:
    required = ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD")
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise RuntimeError(
            "Missing Snowflake environment variables: " + ", ".join(missing)
        )


def get_snowflake_connection() -> snowflake.connector.SnowflakeConnection:
    require_snowflake_env()
    return snowflake.connector.connect(
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        warehouse=os.getenv("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH"),
        database=os.getenv("SNOWFLAKE_DATABASE", "HEALTHCARE_LAKEHOUSE"),
        schema=os.getenv("SNOWFLAKE_SCHEMA", "BRONZE"),
        role=os.getenv("SNOWFLAKE_ROLE", "ACCOUNTADMIN"),
        client_session_keep_alive=True,
    )


def existing_row_count(cursor: snowflake.connector.cursor.SnowflakeCursor, table_name: str) -> int | None:
    try:
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        row = cursor.fetchone()
    except ProgrammingError as exc:
        message = str(exc).lower()
        if getattr(exc, "errno", None) == 2003 or "does not exist" in message:
            return None
        raise
    if row is None:
        raise RuntimeError(f"COUNT(*) returned no row for {table_name}")
    return int(row[0])


def read_synthea_frame(table_name: str, file_path: Path) -> pd.DataFrame:
    frame = pd.read_csv(file_path, dtype=str)
    frame.columns = [str(column).upper() for column in frame.columns]
    actual = set(frame.columns)
    expected = EXPECTED_COLUMNS[table_name]
    missing = expected - actual
    unexpected = actual - expected
    if missing or unexpected:
        raise ValueError(
            f"{file_path.name} columns do not match {table_name}. "
            f"Missing: {sorted(missing) or 'none'}. "
            f"Unexpected: {sorted(unexpected) or 'none'}."
        )
    frame["_LOADED_AT"] = pd.Timestamp.now(tz="UTC")
    frame["_SOURCE_FILE"] = file_path.name
    return frame


def load_frame(
    connection: snowflake.connector.SnowflakeConnection,
    cursor: snowflake.connector.cursor.SnowflakeCursor,
    table_name: str,
    frame: pd.DataFrame,
) -> None:
    previous = existing_row_count(cursor, table_name)
    if previous is None:
        print(f"Creating {table_name} and loading {len(frame)} rows...")
    else:
        print(f"Replacing {table_name} ({previous} existing rows) with {len(frame)} rows...")
    success, _, rows_loaded, _ = write_pandas(
        conn=connection,
        df=frame,
        table_name=table_name,
        auto_create_table=True,
        overwrite=True,
        use_logical_type=True,
        chunk_size=50000,
        parallel=1,
    )
    if not success:
        raise RuntimeError(f"Snowflake rejected the load for {table_name}")
    print(f"Loaded {rows_loaded} rows into {table_name}.")


def read_trials(file_path: Path) -> pd.DataFrame:
    with file_path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, list):
        raise ValueError(f"{file_path.name} must be a JSON array of trial objects")

    rows: list[dict[str, object]] = []
    for index, trial in enumerate(payload):
        if not isinstance(trial, dict):
            raise ValueError(f"Trial at index {index} is not an object")
        missing = TRIAL_KEYS - set(trial)
        if missing:
            raise ValueError(f"Trial at index {index} is missing keys: {sorted(missing)}")
        nct_id = trial.get("nct_id")
        if not isinstance(nct_id, str) or not nct_id.strip():
            raise ValueError(f"Trial at index {index} has an empty nct_id")
        rows.append(
            {
                "NCT_ID": nct_id.strip(),
                "BRIEF_TITLE": trial.get("brief_title"),
                "PHASE": trial.get("phase"),
                "MIN_AGE": trial.get("min_age"),
                "MAX_AGE": trial.get("max_age"),
                "CRITERIA_RAW_TEXT": trial.get("criteria_raw_text"),
                "PAYLOAD": json.dumps(trial),
                "_LOADED_AT": pd.Timestamp.now(tz="UTC"),
                "_SOURCE_FILE": file_path.name,
            }
        )
    return pd.DataFrame(rows)


def stage_data() -> None:
    connection = get_snowflake_connection()
    print("Connected to Snowflake successfully.")
    cursor = connection.cursor()
    try:
        for table_name, file_path in CSV_TABLES.items():
            if not file_path.exists():
                raise FileNotFoundError(file_path)
            print(f"Reading {file_path.name}...")
            load_frame(connection, cursor, table_name, read_synthea_frame(table_name, file_path))

        if not TRIALS_FILE.exists():
            raise FileNotFoundError(TRIALS_FILE)
        print(f"Reading {TRIALS_FILE.name}...")
        load_frame(connection, cursor, "RAW_TRIALS", read_trials(TRIALS_FILE))
    finally:
        cursor.close()
        connection.close()
    print("Staging complete.")


if __name__ == "__main__":
    stage_data()
