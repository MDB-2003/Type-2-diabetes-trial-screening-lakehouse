import json
from pathlib import Path
import requests

BASE_URL = "https://clinicaltrials.gov/api/v2/studies"
PARAMS = {
    "query.cond": "type 2 diabetes",
    "filter.overallStatus": "RECRUITING",
    "pageSize": 50,
}

OUTPUT_DIR = Path("data/raw/trials")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def fetch_and_save_trials():
    response = requests.get(BASE_URL, params=PARAMS)
    response.raise_for_status()
    payload = response.json()

    cleaned_trials = []
    for study in payload.get("studies", []):
        protocol = study.get("protocolSection", {})
        id_mod = protocol.get("identificationModule", {})
        design_mod = protocol.get("designModule", {})
        eligibility_mod = protocol.get("eligibilityModule", {})
        nct_id = id_mod.get("nctId")
        title = id_mod.get("briefTitle")
        phases = design_mod.get("phases") or []
        criteria_text = eligibility_mod.get("eligibilityCriteria") or ""
        min_age = eligibility_mod.get("minimumAge")
        max_age = eligibility_mod.get("maximumAge")

        if nct_id and criteria_text:
            cleaned_trials.append(
                {
                    "nct_id": nct_id,
                    "brief_title": title,
                    "phase": "|".join(phases) if phases else None,
                    "min_age": min_age,
                    "max_age": max_age,
                    "criteria_raw_text": criteria_text,
                }
            )

    output_path = OUTPUT_DIR / "recruiting_diabetes_trials.json"
    with open(output_path, "w") as f:
        json.dump(cleaned_trials, f, indent=2)

    print(f"Ingested {len(cleaned_trials)} clinical trials to {output_path}")


if __name__ == "__main__":
    fetch_and_save_trials()