select
    patient_id,
    encounter_id,
    observation_code,
    description,
    observation_at,
    value_numeric,
    units
from {{ ref('stg_observations') }}
where is_implausible_value
