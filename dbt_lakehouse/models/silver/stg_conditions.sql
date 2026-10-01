with source as (

    select * from {{ source('bronze', 'raw_conditions') }}

),

standardized as (

    select
        try_to_date(nullif(trim("START"), '')) as condition_start_date,
        try_to_date(nullif(trim("STOP"), '')) as condition_stop_date,
        nullif(trim(patient), '') as patient_id,
        nullif(trim(encounter), '') as encounter_id,
        nullif(trim(code), '') as condition_code,
        nullif(trim(description), '') as description,
        try_to_timestamp_tz(_loaded_at::varchar) as loaded_at,
        nullif(trim(_source_file), '') as source_file
    from source

)

select
    *,
    condition_code in (
        '44054006',
        '368581000119106',
        '422034002',
        '90781000119102',
        '1551000119108',
        '97331000119101',
        '1501000119109'
    ) as is_type2_diabetes
from standardized
