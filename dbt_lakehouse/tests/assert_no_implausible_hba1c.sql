-- HbA1c values that reach screening must be a plausible percent on LOINC 4548-4.
select
    patient_id,
    observation_code,
    hba1c_units,
    latest_hba1c
from {{ ref('int_patient_latest_hba1c') }}
where latest_hba1c < 0
    or latest_hba1c > 20
    or hba1c_units <> '%'
    or observation_code <> '4548-4'
