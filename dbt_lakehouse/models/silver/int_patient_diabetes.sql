select
    patient_id,
    max(iff(is_type2_diabetes, 1, 0)) = 1 as has_type2_diabetes
from {{ ref('stg_conditions') }}
group by patient_id
