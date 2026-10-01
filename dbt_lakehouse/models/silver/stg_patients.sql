with source as (

    select * from {{ source('bronze', 'raw_patients') }}

),

standardized as (

    select
        nullif(trim(id), '') as patient_id,
        try_to_date(nullif(trim(birthdate), '')) as birth_date,
        try_to_date(nullif(trim(deathdate), '')) as death_date,
        upper(nullif(trim(gender), '')) as gender,
        lower(nullif(trim(race), '')) as race,
        lower(nullif(trim(ethnicity), '')) as ethnicity,
        nullif(trim(city), '') as city,
        nullif(trim(state), '') as state,
        try_to_timestamp_tz(_loaded_at::varchar) as loaded_at,
        nullif(trim(_source_file), '') as source_file
    from source

)

select * from standardized
