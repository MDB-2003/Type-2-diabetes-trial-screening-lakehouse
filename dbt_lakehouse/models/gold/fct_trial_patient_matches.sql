with patients as (

    select
        patient_id,
        birth_date,
        death_date,
        gender,
        city,
        state,
        case
            when birth_date is null then null
            else datediff('year', birth_date, current_date())
                - iff(
                    dateadd('year', datediff('year', birth_date, current_date()), birth_date) > current_date(),
                    1,
                    0
                )
        end as current_age
    from {{ ref('stg_patients') }}

),

trials as (

    select
        nct_id,
        brief_title,
        phase,
        min_age_years,
        max_age_years,
        hba1c_lower_bound,
        hba1c_lower_inclusive,
        hba1c_upper_bound,
        hba1c_upper_inclusive,
        hba1c_rule_parsed
    from {{ ref('stg_trials') }}

),

diabetes as (

    select
        patient_id,
        has_type2_diabetes
    from {{ ref('int_patient_diabetes') }}

),

hba1c as (

    select
        patient_id,
        latest_hba1c
    from {{ ref('int_patient_latest_hba1c') }}

),

screened as (

    select
        trials.nct_id,
        trials.brief_title,
        trials.phase,
        patients.patient_id,
        patients.current_age,
        patients.gender,
        patients.city,
        patients.state,
        coalesce(diabetes.has_type2_diabetes, false) as has_type2_diabetes,
        hba1c.latest_hba1c,
        patients.death_date is null
            and patients.current_age is not null
            and trials.min_age_years is not null
            and trials.max_age_years is not null
            and patients.current_age >= trials.min_age_years
            and patients.current_age <= trials.max_age_years as passes_age_check,
        case
            when not trials.hba1c_rule_parsed then null
            when hba1c.latest_hba1c is null then false
            when trials.hba1c_lower_bound is not null
                and coalesce(trials.hba1c_lower_inclusive, true)
                and hba1c.latest_hba1c < trials.hba1c_lower_bound then false
            when trials.hba1c_lower_bound is not null
                and not coalesce(trials.hba1c_lower_inclusive, true)
                and hba1c.latest_hba1c <= trials.hba1c_lower_bound then false
            when trials.hba1c_upper_bound is not null
                and coalesce(trials.hba1c_upper_inclusive, true)
                and hba1c.latest_hba1c > trials.hba1c_upper_bound then false
            when trials.hba1c_upper_bound is not null
                and not coalesce(trials.hba1c_upper_inclusive, true)
                and hba1c.latest_hba1c >= trials.hba1c_upper_bound then false
            else true
        end as passes_hba1c_check
    from patients
    cross join trials
    left join diabetes
        on patients.patient_id = diabetes.patient_id
    left join hba1c
        on patients.patient_id = hba1c.patient_id

)

select
    nct_id,
    brief_title,
    phase,
    patient_id,
    current_age,
    gender,
    city,
    state,
    has_type2_diabetes,
    latest_hba1c,
    passes_age_check,
    passes_hba1c_check,
    case
        when passes_age_check
            and has_type2_diabetes
            and passes_hba1c_check then 'ELIGIBLE'
        when passes_age_check
            and has_type2_diabetes
            and passes_hba1c_check is null then 'REVIEW_REQUIRED'
        else 'INELIGIBLE'
    end as match_status
from screened
