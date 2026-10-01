with hba1c as (

    select
        patient_id,
        observation_at,
        value_numeric,
        units,
        observation_code
    from {{ ref('stg_observations') }}
    where observation_code = '4548-4'
        and observation_type = 'numeric'
        and units = '%'
        and value_numeric is not null
        and value_numeric >= 0
        and value_numeric <= 20

)

select
    patient_id,
    observation_code,
    units as hba1c_units,
    value_numeric as latest_hba1c,
    observation_at as hba1c_observed_at
from hba1c
qualify row_number() over (
    partition by patient_id
    order by observation_at desc
) = 1
