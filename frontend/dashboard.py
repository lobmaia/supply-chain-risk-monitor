from datetime import datetime

import httpx
import streamlit as st

from app.core.config import get_settings

settings = get_settings()
api_base_url = settings.frontend_api_base_url.rstrip("/")

st.set_page_config(page_title="Supply Chain Risk Monitor", layout="wide")


def api_get(path: str, **params: object) -> object:
    response = httpx.get(f"{api_base_url}{path}", params=params or None, timeout=10.0)
    response.raise_for_status()
    return response.json()


def api_send(method: str, path: str, payload: dict[str, object] | None = None) -> object:
    response = httpx.request(method, f"{api_base_url}{path}", json=payload, timeout=20.0)
    response.raise_for_status()
    return response.json()


def risk_label(score: float) -> str:
    if score >= 0.75:
        return "Critical"
    if score >= 0.55:
        return "Elevated"
    if score >= 0.35:
        return "Moderate"
    return "Low"


def format_timestamp(value: str | None) -> str:
    if not value:
        return "N/A"
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.strftime("%Y-%m-%d %H:%M UTC")


def render_history_chart(history: list[dict[str, object]]) -> None:
    if not history:
        st.info("No trend history is available for the selected entity yet.")
        return

    points = [
        {
            "snapshot_date": str(item["snapshot_date"]),
            "aggregated_risk_score": item["aggregated_risk_score"],
            "article_volume": item["article_volume"],
        }
        for item in reversed(history)
    ]
    st.vega_lite_chart(
        {"values": points},
        {
            "mark": {"type": "line", "point": True, "strokeWidth": 3},
            "encoding": {
                "x": {"field": "snapshot_date", "type": "temporal", "title": "Date"},
                "y": {
                    "field": "aggregated_risk_score",
                    "type": "quantitative",
                    "title": "Risk Score",
                    "scale": {"domain": [0, 1]},
                },
                "tooltip": [
                    {"field": "snapshot_date", "type": "temporal", "title": "Date"},
                    {"field": "aggregated_risk_score", "type": "quantitative", "format": ".2f"},
                    {"field": "article_volume", "type": "quantitative", "title": "Articles"},
                ],
            },
            "height": 280,
        },
        use_container_width=True,
    )


def watchlist_form_defaults(items: list[dict[str, object]], item_id: int | None) -> dict[str, object]:
    default_item = next((item for item in items if item["id"] == item_id), None)
    if default_item is None:
        return {
            "display_name": "",
            "entity_type": "company",
            "query_hint": "",
            "is_active": True,
        }
    return {
        "display_name": default_item["display_name"],
        "entity_type": default_item["entity_type"],
        "query_hint": default_item["query_hint"] or "",
        "is_active": default_item["is_active"],
    }


def trigger_refresh() -> None:
    st.cache_data.clear()
    st.rerun()


@st.cache_data(ttl=30, show_spinner=False)
def load_dashboard_data() -> dict[str, object]:
    return {
        "health": api_get("/health"),
        "summary": api_get("/api/v1/summary"),
        "dashboard": api_get("/api/v1/dashboard/overview", entity_limit=10, flagged_limit=10),
        "watchlist": api_get("/api/v1/watchlist"),
        "risk_status": api_get("/api/v1/risk/status"),
    }


st.title("Supply Chain Risk Monitor")
st.caption("Watchlist-driven monitoring, trends, and alert evidence.")

try:
    data = load_dashboard_data()
except httpx.HTTPError as exc:
    st.error(f"Backend unavailable at {api_base_url}: {exc}")
    st.stop()

dashboard = data["dashboard"]
summary = data["summary"]
risk_status = data["risk_status"]
watchlist_items = data["watchlist"]
top_entities = dashboard["top_entities"]
flagged_events = dashboard["flagged_events"]

metric_cols = st.columns(5)
metric_cols[0].metric("Watchlist Targets", summary["watchlist_items"])
metric_cols[1].metric("Relevant Articles", summary["relevant_articles"])
metric_cols[2].metric("Risk Snapshots", risk_status["entity_risk_snapshots"])
metric_cols[3].metric("Spike Entities", dashboard["spike_entity_count"])
metric_cols[4].metric("Last Risk Refresh", format_timestamp(risk_status["last_scored_at"]))

status_col, action_col = st.columns([2, 1])
with status_col:
    st.subheader("System Status")
    st.json(data["health"])
with action_col:
    st.subheader("Pipeline Controls")
    if st.button("Run Ingestion", use_container_width=True):
        api_send("POST", "/api/v1/ingestion/run")
        trigger_refresh()
    if st.button("Run Processing + Risk", use_container_width=True):
        api_send("POST", "/api/v1/processing/run")
        trigger_refresh()

overview_col, watchlist_col = st.columns([1.5, 1])

with overview_col:
    st.subheader("Risk Summary By Entity")
    if not top_entities:
        st.info("No entity risk snapshots yet. Run ingestion and processing to populate the dashboard.")
    else:
        entity_rows = [
            {
                "Entity": entity["entity_name"],
                "Type": entity["entity_type"],
                "Risk": f'{entity["aggregated_risk_score"]:.2f} ({risk_label(entity["aggregated_risk_score"])})',
                "Articles": entity["article_volume"],
                "Spike": "Yes" if entity["spike_flag"] else "No",
                "Date": str(entity["snapshot_date"]),
            }
            for entity in top_entities
        ]
        st.dataframe(entity_rows, use_container_width=True, hide_index=True)

with watchlist_col:
    st.subheader("Watchlist")
    if watchlist_items:
        for item in watchlist_items:
            status = "active" if item["is_active"] else "paused"
            hint = item["query_hint"] or "No query hint"
            st.markdown(f'`{item["entity_type"]}` **{item["display_name"]}**  \n{hint}  \nStatus: {status}')
    else:
        st.info("No watchlist targets configured.")

trend_col, evidence_col = st.columns([1.4, 1])

with trend_col:
    st.subheader("Trend Chart")
    if top_entities:
        entity_lookup = {
            f'{entity["entity_name"]} ({entity["entity_type"]})': entity["entity_id"] for entity in top_entities
        }
        selected_label = st.selectbox("Tracked entity", list(entity_lookup))
        selected_entity_id = entity_lookup[selected_label]
        history = api_get(f"/api/v1/risk/entities/{selected_entity_id}/history", limit=14)
        render_history_chart(history)
    else:
        st.info("Trend data will appear once relevant articles are scored.")

with evidence_col:
    st.subheader("Flagged Headline Feed")
    if not flagged_events:
        st.info("No flagged headlines meet the current threshold.")
    else:
        event_lookup = {
            f'{event["title"]} ({risk_label(event["risk_score"])})': event["article_id"] for event in flagged_events
        }
        selected_event_label = st.radio("Select alert", list(event_lookup), label_visibility="collapsed")
        selected_article_id = event_lookup[selected_event_label]
        detail = api_get(f"/api/v1/risk/events/{selected_article_id}")
        st.markdown(f'**{detail["title"]}**')
        st.caption(f'{detail["source_name"]} • {format_timestamp(detail["published_at"])}')
        st.write(detail["summary"] or "No source summary was captured for this alert.")
        st.link_button("Open Source Article", detail["url"], use_container_width=True)
        st.markdown(
            f'Risk score: `{detail["risk_score"]:.2f}`  \n'
            f'Relevance score: `{detail["relevance_score"]:.2f}`  \n'
            f'Watchlist matches: `{detail["matched_watchlist_count"]}`'
        )
        st.markdown("**Scoring Evidence**")
        st.json(detail["scoring_notes"])
        st.markdown("**Linked Entities**")
        if detail["entities"]:
            entity_evidence_rows = [
                {
                    "Entity": entity["entity_name"],
                    "Type": entity["entity_type"],
                    "Relation": entity["relation_type"],
                    "Confidence": round(entity["confidence"], 2),
                    "Snapshot Risk": entity["aggregated_risk_score"],
                    "Spike": "Yes" if entity["spike_flag"] else "No",
                }
                for entity in detail["entities"]
            ]
            st.dataframe(entity_evidence_rows, use_container_width=True, hide_index=True)
        else:
            st.info("No linked entities are stored for this alert.")

st.divider()
st.subheader("Manage Watchlist")

watchlist_ids = {f'{item["display_name"]} ({item["entity_type"]})': item["id"] for item in watchlist_items}
edit_label = st.selectbox(
    "Edit existing target",
    ["Create new target"] + list(watchlist_ids),
)
selected_watchlist_id = None if edit_label == "Create new target" else watchlist_ids[edit_label]
defaults = watchlist_form_defaults(watchlist_items, selected_watchlist_id)

with st.form("watchlist_form", clear_on_submit=False):
    display_name = st.text_input("Display name", value=defaults["display_name"])
    entity_type = st.selectbox(
        "Entity type",
        options=["company", "region", "commodity"],
        index=["company", "region", "commodity"].index(defaults["entity_type"])
        if defaults["entity_type"] in {"company", "region", "commodity"}
        else 0,
    )
    query_hint = st.text_input("Query hint", value=defaults["query_hint"])
    is_active = st.checkbox("Active", value=bool(defaults["is_active"]))

    save_col, delete_col = st.columns(2)
    save_pressed = save_col.form_submit_button("Save Target", use_container_width=True)
    delete_pressed = delete_col.form_submit_button(
        "Delete Target",
        use_container_width=True,
        disabled=selected_watchlist_id is None,
    )

if save_pressed:
    payload = {
        "display_name": display_name,
        "entity_type": entity_type,
        "query_hint": query_hint,
        "is_active": is_active,
    }
    try:
        if selected_watchlist_id is None:
            api_send("POST", "/api/v1/watchlist", payload)
        else:
            api_send("PUT", f"/api/v1/watchlist/{selected_watchlist_id}", payload)
    except httpx.HTTPError as exc:
        st.error(f"Unable to save watchlist target: {exc}")
    else:
        st.success("Watchlist updated. Articles were queued for reprocessing.")
        trigger_refresh()

if delete_pressed and selected_watchlist_id is not None:
    try:
        api_send("DELETE", f"/api/v1/watchlist/{selected_watchlist_id}")
    except httpx.HTTPError as exc:
        st.error(f"Unable to delete watchlist target: {exc}")
    else:
        st.success("Watchlist target deleted. Articles were queued for reprocessing.")
        trigger_refresh()
