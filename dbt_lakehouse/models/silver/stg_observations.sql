with source as (

    select * from {{ source('bronze', 'raw_observations') }}

),

standardized as (

    select
        try_to_timestamp_tz(nullif(trim(date), '')) as observation_at,
        nullif(trim(patient), '') as patient_id,
        nullif(trim(encounter), '') as encounter_id,
        nullif(trim(code), '') as observation_code,
        nullif(trim(description), '') as description,
        nullif(trim(value), '') as value_text,
        try_to_double(nullif(trim(value), '')) as value_numeric,
        nullif(trim(units), '') as units,
        lower(nullif(trim(type), '')) as observation_type,
        try_to_timestamp_tz(_loaded_at::varchar) as loaded_at,
        nullif(trim(_source_file), '') as source_file
    from source

)

select
    *,
    observation_type = 'numeric' and value_numeric < 0 as is_implausible_value
from standardized
