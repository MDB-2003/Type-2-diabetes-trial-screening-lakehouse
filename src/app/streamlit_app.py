import os
import time

import pandas as pd
import snowflake.connector
import streamlit as st
from dotenv import load_dotenv
from google import genai
from google.genai.errors import ClientError, ServerError

load_dotenv()

st.set_page_config(page_title="Type 2 Diabetes Trial Screening", layout="wide", page_icon="🏥")

CANDIDATE_MODELS = ("gemini-3.5-flash", "gemini-3.8-flash")


def query_df(connection: snowflake.connector.SnowflakeConnection, sql: str, params: dict | None = None) -> pd.DataFrame:
    cursor = connection.cursor()
    try:
        cursor.execute(sql, params or {})
        rows = cursor.fetchall()
        columns = [column[0] for column in cursor.description]
    finally:
        cursor.close()
    return pd.DataFrame(rows, columns=columns)


@st.cache_resource
def get_snowflake_conn() -> snowflake.connector.SnowflakeConnection:
    return snowflake.connector.connect(
        user=os.getenv("SNOWFLAKE_USER"),
        password=os.getenv("SNOWFLAKE_PASSWORD"),
        account=os.getenv("SNOWFLAKE_ACCOUNT"),
        warehouse=os.getenv("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH"),
        database=os.getenv("SNOWFLAKE_DATABASE", "HEALTHCARE_LAKEHOUSE"),
        schema=os.getenv("SNOWFLAKE_SCHEMA", "GOLD"),
        role=os.getenv("SNOWFLAKE_ROLE", "ACCOUNTADMIN"),
    )


@st.cache_resource
def get_ai_client():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None
    return genai.Client(api_key=api_key)


conn = get_snowflake_conn()
ai_client = get_ai_client()

st.title("Type 2 Diabetes Trial Screening")
st.caption(
    "A patient is ELIGIBLE only when they are living, inside the protocol age window, "
    "have a type 2 diabetes condition, and their latest HbA1c (LOINC 4548-4) falls inside "
    "a window parsed from that protocol's inclusion text. REVIEW_REQUIRED means age and "
    "diabetes history pass, but the inclusion text has no usable HbA1c window."
)

try:
    trials_df = query_df(
        conn,
        """
        SELECT DISTINCT
            t.NCT_ID,
            t.BRIEF_TITLE,
            t.PHASE,
            s.CRITERIA_RAW_TEXT
        FROM HEALTHCARE_LAKEHOUSE.GOLD.FCT_TRIAL_PATIENT_MATCHES t
        JOIN HEALTHCARE_LAKEHOUSE.SILVER.STG_TRIALS s
            ON t.NCT_ID = s.NCT_ID
        ORDER BY t.NCT_ID
        """,
    )
except snowflake.connector.errors.ProgrammingError as exc:
    st.error(
        "The screening fact is not available yet. From the project root, run "
        "`dbt run --project-dir dbt_lakehouse --profiles-dir dbt_lakehouse`."
    )
    st.exception(exc)
    st.stop()

if trials_df.empty:
    st.warning("GOLD.FCT_TRIAL_PATIENT_MATCHES has no rows.")
    st.stop()

trial_titles = dict(zip(trials_df["NCT_ID"], trials_df["BRIEF_TITLE"]))


def format_trial_option(nct_id: str) -> str:
    title = str(trial_titles.get(nct_id, ""))
    short_title = title[:45] + "..." if len(title) > 45 else title
    return f"{nct_id} - {short_title}"


tab_cohort, tab_copilot = st.tabs(["Patient match cohort", "Protocol copilot"])

with tab_cohort:
    col_left, col_right = st.columns([1, 2])

    with col_left:
        st.subheader("Active diabetes protocols")
        selected_trial = st.selectbox(
            "Select protocol",
            trials_df["NCT_ID"].tolist(),
            format_func=format_trial_option,
            key="cohort_trial_select",
        )
        trial_row = trials_df[trials_df["NCT_ID"] == selected_trial].iloc[0]
        st.markdown(f"**Trial ID:** `{trial_row['NCT_ID']}`")
        st.markdown(f"**Phase:** `{trial_row['PHASE']}`")
        st.info(f"**Study title:**\n\n{trial_row['BRIEF_TITLE']}")
        with st.expander("View full protocol eligibility text"):
            st.write(trial_row["CRITERIA_RAW_TEXT"])

    with col_right:
        st.subheader("Candidate patient cohort")
        matches_df = query_df(
            conn,
            """
            SELECT
                PATIENT_ID,
                CURRENT_AGE,
                GENDER,
                CITY,
                HAS_TYPE2_DIABETES,
                LATEST_HBA1C,
                PASSES_AGE_CHECK,
                PASSES_HBA1C_CHECK,
                MATCH_STATUS
            FROM HEALTHCARE_LAKEHOUSE.GOLD.FCT_TRIAL_PATIENT_MATCHES
            WHERE NCT_ID = %(nct_id)s
            ORDER BY
                CASE MATCH_STATUS
                    WHEN 'ELIGIBLE' THEN 0
                    WHEN 'REVIEW_REQUIRED' THEN 1
                    ELSE 2
                END,
                LATEST_HBA1C DESC
            """,
            {"nct_id": selected_trial},
        )

        eligible_count = int((matches_df["MATCH_STATUS"] == "ELIGIBLE").sum())
        review_count = int((matches_df["MATCH_STATUS"] == "REVIEW_REQUIRED").sum())
        total_eval = len(matches_df)

        metric_eligible, metric_review, metric_screened, metric_rate = st.columns(4)
        metric_eligible.metric("Eligible", eligible_count)
        metric_review.metric("Needs review", review_count)
        metric_screened.metric("Screened patients", total_eval)
        metric_rate.metric(
            "Qualification rate",
            f"{(eligible_count / total_eval * 100):.1f}%" if total_eval else "0%",
        )
        st.dataframe(
            matches_df,
            column_config={
                "MATCH_STATUS": st.column_config.TextColumn("Status"),
                "HAS_TYPE2_DIABETES": st.column_config.CheckboxColumn("Type 2 diabetes"),
                "LATEST_HBA1C": st.column_config.NumberColumn("Latest HbA1c (%)", format="%.1f"),
                "PASSES_AGE_CHECK": st.column_config.CheckboxColumn("Age window"),
                "PASSES_HBA1C_CHECK": st.column_config.CheckboxColumn("HbA1c window"),
            },
            hide_index=True,
            use_container_width=True,
        )

with tab_copilot:
    st.subheader("Protocol copilot")
    st.caption("Answers are limited to the selected protocol text. They do not change the screening flags.")

    selected_copilot_trial = st.selectbox(
        "Protocol context",
        trials_df["NCT_ID"].tolist(),
        key="copilot_trial_select",
        format_func=format_trial_option,
    )
    copilot_trial_row = trials_df[trials_df["NCT_ID"] == selected_copilot_trial].iloc[0]

    if not ai_client:
        st.warning("Add GEMINI_API_KEY to `.env` to enable the protocol copilot.")
    else:
        user_query = st.text_input(
            "Ask about inclusion criteria, exclusions, or how a lab result would be read",
            value="What HbA1c range does this protocol require, and which exclusions mention kidney disease?",
        )
        if st.button("Analyze protocol") and user_query:
            criteria_text = copilot_trial_row["CRITERIA_RAW_TEXT"] or ""
            prompt = f"""
            You are a clinical research coordinator reading one protocol.
            Use only the protocol text below. If the text does not state a requirement, say that it does not.

            Protocol: {copilot_trial_row['NCT_ID']} - {copilot_trial_row['BRIEF_TITLE']}
            Protocol criteria text:
            {criteria_text}

            Question:
            {user_query}

            Answer with:
            1. Direct answer from the protocol text
            2. Inclusion and exclusion constraints that apply
            3. Safety items a screener should not skip
            """
            response_text = None
            used_model = None
            last_error = None

            with st.spinner("Reading the protocol..."):
                for model_candidate in CANDIDATE_MODELS:
                    for _attempt in range(3):
                        try:
                            response = ai_client.models.generate_content(
                                model=model_candidate,
                                contents=prompt,
                            )
                            if response and response.text:
                                response_text = response.text
                                used_model = model_candidate
                                break
                        except ServerError as exc:
                            last_error = exc
                            time.sleep(2)
                        except ClientError as exc:
                            last_error = exc
                            break
                    if response_text:
                        break

            if response_text:
                st.caption(f"Model: `{used_model}`")
                st.markdown(response_text)
            else:
                st.error(f"The protocol copilot did not return a response: {last_error}")
