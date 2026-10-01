-- Fails when a negative numeric observation is missing from the audit view.
select
    observation.patient_id,
    observation.encounter_id,
    observation.observation_code,
    observation.observation_at,
    observation.value_numeric
from {{ ref('stg_observations') }} as observation
left join {{ ref('audit_implausible_observations') }} as audit
    on observation.patient_id = audit.patient_id
    and observation.encounter_id is not distinct from audit.encounter_id
    and observation.observation_code = audit.observation_code
    and observation.observation_at is not distinct from audit.observation_at
    and observation.value_numeric = audit.value_numeric
where observation.value_numeric < 0
    and audit.patient_id is null
