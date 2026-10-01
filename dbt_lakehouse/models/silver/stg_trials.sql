with source as (

    select * from {{ source('bronze', 'raw_trials') }}

),

normalized as (

    select
        nullif(trim(nct_id), '') as nct_id,
        nullif(trim(brief_title), '') as brief_title,
        nullif(trim(phase), '') as phase,
        nullif(trim(min_age), '') as min_age_raw,
        nullif(trim(max_age), '') as max_age_raw,
        nullif(trim(criteria_raw_text), '') as criteria_raw_text,
        try_parse_json(payload) as payload,
        try_to_timestamp_tz(_loaded_at::varchar) as loaded_at,
        nullif(trim(_source_file), '') as source_file,
        replace(
            replace(
                replace(
                    replace(lower(criteria_raw_text), chr(92) || '>', '>'),
                    chr(92) || '<',
                    '<'
                ),
                '≥',
                '>='
            ),
            '≤',
            '<='
        ) as criteria_norm
    from source

),

ages as (

    select
        *,
        case
            when min_age_raw ilike '%year%' then try_to_number(regexp_substr(min_age_raw, '[0-9]+'))
            when min_age_raw ilike '%month%' then try_to_number(regexp_substr(min_age_raw, '[0-9]+')) / 12
            when min_age_raw ilike '%week%' then try_to_number(regexp_substr(min_age_raw, '[0-9]+')) / 52
            when min_age_raw ilike '%day%' then try_to_number(regexp_substr(min_age_raw, '[0-9]+')) / 365
            else null
        end as min_age_years,
        case
            when max_age_raw ilike '%year%' then try_to_number(regexp_substr(max_age_raw, '[0-9]+'))
            when max_age_raw ilike '%month%' then try_to_number(regexp_substr(max_age_raw, '[0-9]+')) / 12
            when max_age_raw ilike '%week%' then try_to_number(regexp_substr(max_age_raw, '[0-9]+')) / 52
            when max_age_raw ilike '%day%' then try_to_number(regexp_substr(max_age_raw, '[0-9]+')) / 365
            else null
        end as max_age_years,
        split_part(criteria_norm, 'exclusion criteria', 1) as inclusion_text
    from normalized

),

hba1c_text as (

    select
        *,
        replace(
            coalesce(regexp_substr(inclusion_text, '(hba1c|hemoglobin a1c|glycated hemoglobin|glycosylated haemoglobin|glycosylated hemoglobin).{0,140}', 1, 1, 'i'), '')
            || ' '
            || coalesce(regexp_substr(inclusion_text, '(hba1c|hemoglobin a1c|glycated hemoglobin|glycosylated haemoglobin|glycosylated hemoglobin).{0,140}', 1, 2, 'i'), '')
            || ' '
            || coalesce(regexp_substr(inclusion_text, '(hba1c|hemoglobin a1c|glycated hemoglobin|glycosylated haemoglobin|glycosylated hemoglobin).{0,140}', 1, 3, 'i'), '')
        , 'percent', '%') as hba1c_focus
    from ages

),

marked as (

    select
        *,
        replace(
            replace(
                replace(
                    replace(
                        replace(
                            replace(hba1c_focus, '> or equal to', ' gte '),
                            '< or equal to', ' lte '
                        ),
                        '>=', ' gte '
                    ),
                    '<=', ' lte '
                ),
                '>', ' gt '
            ),
            '<', ' lt '
        ) as hba1c_marked
    from hba1c_text

),

extracted as (

    select
        *,
        try_to_double(regexp_substr(hba1c_marked, 'between[^0-9]{0,20}([0-9]+([.][0-9]+)?)', 1, 1, 'ie', 1)) as between_lo,
        try_to_double(regexp_substr(hba1c_marked, 'between[^0-9]{0,20}[0-9]+([.][0-9]+)?[^0-9]{0,20}(and|to)[^0-9]{0,20}([0-9]+([.][0-9]+)?)', 1, 1, 'ie', 3)) as between_hi,
        try_to_double(regexp_substr(hba1c_marked, '([0-9]+([.][0-9]+)?)[[:space:]]*%[[:space:]]*(to|-)[[:space:]]*([0-9]+([.][0-9]+)?)[[:space:]]*%', 1, 1, 'ie', 1)) as range_lo,
        try_to_double(regexp_substr(hba1c_marked, '([0-9]+([.][0-9]+)?)[[:space:]]*%[[:space:]]*(to|-)[[:space:]]*([0-9]+([.][0-9]+)?)[[:space:]]*%', 1, 1, 'ie', 4)) as range_hi,
        try_to_double(regexp_substr(hba1c_marked, '([0-9]+([.][0-9]+)?)[[:space:]]*(to|-)[[:space:]]*([0-9]+([.][0-9]+)?)[[:space:]]*%', 1, 1, 'ie', 1)) as loose_lo,
        try_to_double(regexp_substr(hba1c_marked, '([0-9]+([.][0-9]+)?)[[:space:]]*(to|-)[[:space:]]*([0-9]+([.][0-9]+)?)[[:space:]]*%', 1, 1, 'ie', 4)) as loose_hi,
        try_to_double(regexp_substr(hba1c_marked, 'gte[[:space:]]*([0-9]+([.][0-9]+)?)', 1, 1, 'ie', 1)) as gte_bound,
        try_to_double(regexp_substr(hba1c_marked, 'lte[[:space:]]*([0-9]+([.][0-9]+)?)', 1, 1, 'ie', 1)) as lte_bound,
        try_to_double(regexp_substr(hba1c_marked, 'gt[[:space:]]*([0-9]+([.][0-9]+)?)', 1, 1, 'ie', 1)) as gt_bound,
        try_to_double(regexp_substr(hba1c_marked, 'lt[[:space:]]*([0-9]+([.][0-9]+)?)', 1, 1, 'ie', 1)) as lt_bound
    from marked

),

candidates as (

    select
        *,
        case
            when between_lo is not null and between_hi is not null and between_lo <= between_hi then between_lo
            when range_lo is not null and range_hi is not null and range_lo <= range_hi then range_lo
            when loose_lo is not null and loose_hi is not null and loose_lo <= loose_hi then loose_lo
            else coalesce(gte_bound, gt_bound)
        end as candidate_lower,
        case
            when between_lo is not null and between_hi is not null and between_lo <= between_hi then between_hi
            when range_lo is not null and range_hi is not null and range_lo <= range_hi then range_hi
            when loose_lo is not null and loose_hi is not null and loose_lo <= loose_hi then loose_hi
            else coalesce(lte_bound, lt_bound)
        end as candidate_upper,
        case
            when between_lo is not null and between_hi is not null and between_lo <= between_hi then true
            when range_lo is not null and range_hi is not null and range_lo <= range_hi then true
            when loose_lo is not null and loose_hi is not null and loose_lo <= loose_hi then true
            when gte_bound is not null then true
            when gt_bound is not null then false
            else null
        end as candidate_lower_inclusive,
        case
            when between_lo is not null and between_hi is not null and between_lo <= between_hi then true
            when range_lo is not null and range_hi is not null and range_lo <= range_hi then true
            when loose_lo is not null and loose_hi is not null and loose_lo <= loose_hi then true
            when lte_bound is not null then true
            when lt_bound is not null then false
            else null
        end as candidate_upper_inclusive
    from extracted

),

resolved as (

    select
        *,
        (
            candidate_lower is not null
            or candidate_upper is not null
        )
        and (
            candidate_lower is null
            or candidate_upper is null
            or candidate_lower <= candidate_upper
        ) as hba1c_rule_parsed
    from candidates

)

select
    nct_id,
    brief_title,
    phase,
    min_age_raw,
    max_age_raw,
    min_age_years,
    max_age_years,
    criteria_raw_text,
    iff(hba1c_rule_parsed, candidate_lower, null) as hba1c_lower_bound,
    iff(hba1c_rule_parsed, candidate_lower_inclusive, null) as hba1c_lower_inclusive,
    iff(hba1c_rule_parsed, candidate_upper, null) as hba1c_upper_bound,
    iff(hba1c_rule_parsed, candidate_upper_inclusive, null) as hba1c_upper_inclusive,
    hba1c_rule_parsed,
    payload,
    loaded_at,
    source_file
from resolved
