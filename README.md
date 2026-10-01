# Type 2 Diabetes Trial-Screening Case Study

## Table of Contents

- [Overview](#overview)
- [Motivation](#motivation)
- [Understanding Eligibility](#understanding-eligibility)
- [Business Aspect](#business-aspect)
- [Technical Aspect](#technical-aspect)
- [Installation](#installation)
- [Directory Tree](#directory-tree)
- [Technologies Used](#technologies-used)
- [Credits](#credits)

## Overview

This project looks at a familiar research-operations problem: a stack of recruiting diabetes protocols, and a panel of patients who might fit one of them. It has two parts.

The first is a screening fact. For every patient and every recruiting trial, it returns one status: `ELIGIBLE`, `REVIEW_REQUIRED`, or `INELIGIBLE`. The inputs are the patient's age, whether they have a type 2 diabetes condition, and their latest hemoglobin A1c. The second part is a small screening desk. A coordinator picks a protocol and sees who already clears those checks, who needs a person to read the criteria, and who is out. A copilot can answer questions about the protocol text. It does not change a status.

The fact table stops at those three statuses. Whether anyone is contacted, consented, or enrolled is outside this project.

On the loaded sample the Gold table has 58,550 rows: 1,171 patients crossed with 50 recruiting trials. Of those rows, 255 are eligible, 1,431 need a person to review the protocol, and 56,864 are ineligible.

## Motivation

A coordinator matching patients to type 2 diabetes studies does not start from the protocol PDF. They start from a short list. Most of the panel will never qualify. Some will fail an age bound. Some have no diabetes history. Some have a recent HbA1c that sits outside the range the inclusion text actually states. Reading all 50 protocols against all 1,171 charts by hand spends the review time on people who were never candidates.

The useful cut is the one that can be checked from the chart and the inclusion text before anyone opens the full criteria. Age is on the patient record. Type 2 diabetes is on the condition list. The latest HbA1c is on the lab history. What the protocol requires for that lab is in the inclusion section, when it is stated in a form a screen can read.

For a desk like this, the practical goal is narrow. Keep the call list to patients who clear age, a type 2 diabetes condition, and a stated HbA1c window. Send the rest of the diabetes-and-age matches to a person when the protocol never states a window. Leave everyone else off the list.

## Understanding Eligibility

Eligible, in this project, means four checks all pass.

The patient is living. Their age in years falls inside the protocol's minimum and maximum age, and both bounds were present on the trial record. They have a type 2 diabetes condition. The codes used for that flag were taken from this Synthea extract: SNOMED `44054006` (Diabetes) and the type 2 diabetes complication codes that appear in `conditions.csv`. Prediabetes (`15777000`) is not treated as type 2 diabetes. Their latest plausible HbA1c falls inside a window parsed from the inclusion text only.

HbA1c is LOINC `4548-4`, `Hemoglobin A1c/Hemoglobin.total in Blood`, and the unit on every one of those rows in this extract is `%`. The latest row per patient is the one used. Values below 0% or above 20% never enter that latest-value table. This extract has 339 patients with a plausible result, and 76 patients with a type 2 diabetes condition. All 76 of those patients also have an HbA1c.

The window is not a single cutoff copied onto every trial. The Silver trial model reads the inclusion section, before the words "Exclusion Criteria", and looks for an HbA1c range or a one-sided bound. Sixteen of the 50 protocols produced a usable window. An inverted pair of bounds is discarded. A missing age unit is discarded rather than assumed to be years. A protocol that says nothing parseable about HbA1c does not get a default range of 7% to 10%.

That last point is why `REVIEW_REQUIRED` exists. Age and diabetes history can pass while the inclusion text still does not state a lab window. Those rows are not called eligible. They are the queue for a person.

Two other outcomes sit next to that status, and they answer different questions.

`INELIGIBLE` means at least one required check failed: the patient is deceased, the age window is missing or missed, there is no type 2 diabetes condition, or a stated HbA1c window was missed or the lab is absent.

The copilot answer is not a status. It is a reading of the protocol text. A missing sentence in that text stays missing. The model is not allowed to fill it in, and nothing it writes is written back to the fact table.

## Business Aspect

The case is built around one screening panel: the Synthea sample patients, settled against 50 ClinicalTrials.gov studies that were recruiting for type 2 diabetes when the extract was pulled. The trials carry an NCT id, a title, a phase, a minimum age, a maximum age, and the raw eligibility text. The patient side keeps what the screen needs and leaves direct identifiers in Bronze.

People at a desk like this usually have a little time. They do not re-read a 7,000-character protocol for every chart. The panel tends to fall into three stretches.

The ordinary stretch. The patient is outside the age window, has no type 2 diabetes condition, or is deceased. The fact table marks the row ineligible. A coordinator should not spend the call on that chart.

The decision stretch. The patient is living, the age fits, a type 2 diabetes condition is on the record, and the inclusion text states an HbA1c window. This is the check the fact table is built for. `NCT07401992` is one of those protocols: participants with diabetes need an HbA1c at or below 9.0%. On this panel that protocol returns 55 eligible patients out of 1,171 screened, a qualification rate of 4.7%.

The review stretch. Age and diabetes history pass, and the inclusion text does not state a usable HbA1c window. The row stays `REVIEW_REQUIRED` until someone reads the criteria. Thirty-four of the 50 protocols land in this stretch.

A single protocol, with the three outcomes side by side, comes out like this:

| Check | Chart A | Chart B | Chart C |
| --- | --- | --- | --- |
| Living, age inside the protocol window | yes | yes | yes |
| Type 2 diabetes condition | yes | no | yes |
| Inclusion text states an HbA1c window | 7.5% inside ≤ 9.0% | window present | window not stated |
| Status | ELIGIBLE | INELIGIBLE | REVIEW_REQUIRED |

The copilot only reads the protocol. Asking what the renal exclusions say does not change `MATCH_STATUS`. Enrollment is not a column in this project.

## Technical Aspect

The project is split the same way as the screening problem: one path that lands and types the source files, and one path that turns those types into a status.

### Landing the raw files

Synthea CSVs are read as text, so a LOINC code and a ZIP code are never guessed into numbers on the way in. Each load checks the header against the columns this extract actually has. A missing column or an extra column stops the job. The load replaces the Bronze table. It does not skip a file because yesterday's row count was already above zero, and a count that fails for a reason other than "table does not exist" fails the job.

The four Synthea tables land in `HEALTHCARE_LAKEHOUSE.BRONZE`:

| Bronze table | Source | Rows in this extract |
| --- | --- | --- |
| `RAW_PATIENTS` | `patients.csv` | 1,171 |
| `RAW_OBSERVATIONS` | `observations.csv` | 299,697 |
| `RAW_CONDITIONS` | `conditions.csv` | 8,376 |
| `RAW_MEDICATIONS` | `medications.csv` | 42,989 |
| `RAW_TRIALS` | `recruiting_diabetes_trials.json` | 50 |

`RAW_TRIALS.PAYLOAD` is the trial object as a JSON string. Silver parses it with `TRY_PARSE_JSON`. The fetch script does not fill a missing minimum age with 18 years or a missing maximum with 99. If the API omits an age, the field stays empty, and the age check fails closed.

Names, SSN, driver's license, passport, street address, and coordinates stay in Bronze. They are not selected into `stg_patients`.

### Building the screen

dbt writes views into `HEALTHCARE_LAKEHOUSE.SILVER` and the match table into `HEALTHCARE_LAKEHOUSE.GOLD`. The project macro uses the custom schema name as the schema, so a model tagged `SILVER` does not land in `SILVER_SILVER`.

Silver casts the Bronze strings. Dates, timestamps, and numbers use Snowflake `TRY_TO_*` functions. Medication and condition start columns are quoted because `START` is reserved. Numeric observation values below zero are flagged and collected in `audit_implausible_observations`. This extract has 59 of those rows. The latest-HbA1c model does not read them. A dbt test fails if a negative value is missing from that audit, and another fails if a screening HbA1c is outside 0% to 20% or is not LOINC `4548-4` in percent.

`fct_trial_patient_matches` is one row per patient per trial. `passes_age_check` and `passes_hba1c_check` are stored next to `match_status`, so a status can be traced to the check that produced it. When the protocol has no parsed window, `passes_hba1c_check` is null and the status is `REVIEW_REQUIRED` only if age and type 2 diabetes already passed.

### Reading a protocol, then showing the cohort

The Streamlit desk reads the Gold fact and joins Silver for the eligibility text. The trial id in the cohort query is a bound parameter. The page shows eligible, needs-review, and screened counts for the selected protocol.

The copilot sends the full criteria text to Gemini, first `gemini-3.5-flash` and then `gemini-3.8-flash` if the first call fails. It is instructed to say when the protocol does not state a requirement. That answer is rendered on the page and nowhere else.

A missing Gold table does not invent a cohort. The page tells you to run dbt.

## Installation

The code is written for current Python 3. Python 3.11 or newer matches the package pins in `requirements.txt`. If Python is missing, install it from [python.org](https://www.python.org/downloads/). From the project directory, after cloning:

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Open `.env` and fill in the Snowflake account, user, password, and role. The role needs to create and replace tables in `HEALTHCARE_LAKEHOUSE.BRONZE` and to build views and tables in `SILVER` and `GOLD`. Warehouse and database default to `COMPUTE_WH` and `HEALTHCARE_LAKEHOUSE` when those variables are set as in `.env.example`. `.env` is gitignored.

The raw files are not in git. Put the Synthea sample CSVs in `data/raw/synthea/` (`patients.csv`, `observations.csv`, `conditions.csv`, `medications.csv`). The April 2020 sample zip is published at `https://synthetichealth.github.io/synthea-sample-data/downloads/synthea_sample_data_csv_apr2020.zip`. Then, from the project root:

```bash
python src/ingestion/fetch_trails.py
python src/ingestion/stage_to_snowflake.py
dbt run --project-dir dbt_lakehouse --profiles-dir dbt_lakehouse
dbt test --project-dir dbt_lakehouse --profiles-dir dbt_lakehouse
streamlit run src/app/streamlit_app.py
```

`dbt run` should finish 9 models. `dbt test` should pass 29 tests. The desk is the local Streamlit URL, on port 8501 unless you pass another.

Success for the warehouse step is `HEALTHCARE_LAKEHOUSE.GOLD.FCT_TRIAL_PATIENT_MATCHES` with 58,550 rows, and `STG_PATIENTS` in `SILVER` with no name, SSN, street, or coordinate columns.

## Directory Tree

```text
├── dbt_lakehouse
│   ├── dbt_project.yml
│   ├── profiles.yml
│   ├── macros
│   │   └── generate_schema_name.sql
│   ├── models
│   │   ├── bronze
│   │   │   └── sources.yml
│   │   ├── silver
│   │   │   ├── schema.yml
│   │   │   ├── stg_patients.sql
│   │   │   ├── stg_observations.sql
│   │   │   ├── stg_conditions.sql
│   │   │   ├── stg_medications.sql
│   │   │   ├── stg_trials.sql
│   │   │   ├── int_patient_diabetes.sql
│   │   │   ├── int_patient_latest_hba1c.sql
│   │   │   └── audit_implausible_observations.sql
│   │   └── gold
│   │       ├── schema.yml
│   │       └── fct_trial_patient_matches.sql
│   └── tests
│       ├── assert_match_grain.sql
│       ├── assert_negative_labs_are_audited.sql
│       └── assert_no_implausible_hba1c.sql
├── src
│   ├── app
│   │   └── streamlit_app.py
│   └── ingestion
│       ├── fetch_trails.py
│       └── stage_to_snowflake.py
├── .env.example
├── requirements.txt
└── README.md
```

`data/raw/` is gitignored. So are dbt `target/`, `logs/`, and `.env`.

## Technologies Used

- Python
- pandas
- Snowflake Connector for Python
- dbt and Snowflake
- Streamlit
- Google Gen AI SDK
- requests
- python-dotenv

## Credits

Patient, observation, condition, and medication rows are the public Synthea synthetic sample (April 2020 CSV bundle). They are not a hospital extract. Trial records are a 50-study slice from the ClinicalTrials.gov API v2, filtered to recruiting studies for type 2 diabetes. The HbA1c code, the diabetes SNOMED codes, and the row counts in this write-up were taken from those files and from the Snowflake tables built from them.
