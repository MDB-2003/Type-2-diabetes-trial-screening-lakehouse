with source as (

    select * from {{ source('bronze', 'raw_medications') }}

),

standardized as (

    select
        try_to_timestamp_tz(nullif(trim("START"), '')) as medication_start_at,
        try_to_timestamp_tz(nullif(trim("STOP"), '')) as medication_stop_at,
        nullif(trim(patient), '') as patient_id,
        nullif(trim(payer), '') as payer_id,
        nullif(trim(encounter), '') as encounter_id,
        nullif(trim(code), '') as medication_code,
        nullif(trim(description), '') as description,
        try_to_double(nullif(trim(base_cost), '')) as base_cost,
        try_to_double(nullif(trim(payer_coverage), '')) as payer_coverage,
        try_to_number(nullif(trim(dispenses), '')) as dispenses,
        try_to_double(nullif(trim(totalcost), '')) as total_cost,
        nullif(trim(reasoncode), '') as reason_code,
        nullif(trim(reasondescription), '') as reason_description,
        try_to_timestamp_tz(_loaded_at::varchar) as loaded_at,
        nullif(trim(_source_file), '') as source_file
    from source

)

select * from standardized
