select
    patient_id,
    nct_id
from {{ ref('fct_trial_patient_matches') }}
group by patient_id, nct_id
having count(*) > 1
