"""Streamlit front-end for the RAG chatbot.

Talks to the FastAPI server (main.py) over HTTP using only `requests`:
  - sidebar: API URL, health badge, PDF upload + ingest
  - main: chat history with per-answer source citations
Run with: `uv run streamlit run ui.py`
"""

import requests
import streamlit as st

DEFAULT_API = "http://localhost:8000"
# /chat can stall on Voyage's free-tier rate-limit backoff; give it room.
CHAT_TIMEOUT = 180
# A full PDF ingest embeds every chunk serially and can take many minutes.
INGEST_TIMEOUT = 1800

# Must be the first Streamlit call.
st.set_page_config(page_title="Document Q&A", page_icon="📄")

# Persist across Streamlit's top-to-bottom reruns.
st.session_state.setdefault("messages", [])   # chat history
st.session_state.setdefault("ingested", False)  # did we ingest a PDF this session?


def check_health(base_url: str) -> tuple[bool, dict]:
    """Return (connected, payload). Connected is False on any error or non-200."""
    try:
        r = requests.get(f"{base_url}/health", timeout=5)
        # /health is 200 when ok, 503 when the DB is unreachable.
        return r.status_code == 200, (r.json() if r.content else {})
    except requests.RequestException:
        # Server down / wrong URL / network error — treat as disconnected.
        return False, {}


# ---------------------------------------------------------------- Sidebar
# Empty slot first so the health badge renders at the very TOP of the sidebar,
# even though it's computed from the base-URL input rendered just below it.
health_slot = st.sidebar.empty()
# rstrip("/") so "http://localhost:8000/" and ".../" both work when we append paths.
base_url = st.sidebar.text_input("API base URL", value=DEFAULT_API).rstrip("/")

connected, health = check_health(base_url)
with health_slot.container():
    if connected:
        st.success(f"● Connected — {health.get('model', '')}")
    else:
        st.error("● Disconnected")

st.sidebar.divider()
st.sidebar.subheader("Ingest a PDF")
uploaded = st.sidebar.file_uploader("Upload a PDF", type=["pdf"])

if st.sidebar.button("Ingest PDF"):
    if uploaded is None:
        st.sidebar.warning("Choose a PDF first.")
    else:
        try:
            # Spinner runs for the whole (potentially long) ingest request.
            with st.spinner(f"Ingesting {uploaded.name}…"):
                resp = requests.post(
                    f"{base_url}/ingest",
                    # multipart/form-data field name "file" matches the FastAPI param.
                    files={"file": (uploaded.name, uploaded.getvalue(), "application/pdf")},
                    timeout=INGEST_TIMEOUT,
                )
            if resp.status_code == 200:
                s = resp.json()
                st.session_state.ingested = True
                st.sidebar.success(
                    f"Ingested **{s['source']}**\n\n"
                    f"- {s['total_chunks']} chunks\n"
                    f"- {len(s['stored_ids'])} stored\n"
                    f"- {len(s['failed_chunks'])} failed"
                )
            else:
                # FastAPI error bodies are {"detail": ...}.
                detail = resp.json().get("detail", resp.text) if resp.content else resp.text
                st.sidebar.error(f"Ingest failed ({resp.status_code}): {detail}")
        except requests.RequestException as exc:
            st.sidebar.error(f"Ingest request failed: {exc}")

st.sidebar.divider()
# Reset the conversation; rerun so the cleared history renders immediately.
if st.sidebar.button("Clear chat history"):
    st.session_state.messages = []
    st.rerun()


# -------------------------------------------------------------- Main area
st.title("Document Q&A")

if not connected:
    # API unreachable — explain how to fix it (the Ask button is disabled below).
    st.warning(
        "API unreachable. Start the server with `uv run uvicorn main:app` "
        "and confirm the base URL in the sidebar."
    )

# Render the conversation so far.
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        # Assistant turns carry their retrieved sources (None for error turns).
        if msg["role"] == "assistant" and msg.get("sources") is not None:
            with st.expander(f"Sources ({msg.get('chunks_used', 0)} chunks used)"):
                if msg["sources"]:
                    for src in msg["sources"]:
                        st.markdown(
                            f"- `{src['source']}` — chunk {src['chunk_index']} "
                            f"(similarity {src['similarity']:.3f})"
                        )
                else:
                    st.markdown("_No sources were retrieved for this answer._")

# Empty state: connected, but nothing ingested this session and no chat yet.
if connected and not st.session_state.ingested and not st.session_state.messages:
    st.info("Upload a PDF in the sidebar to get started.")

# ------------------------------------------------------ Question input (bottom)
question = st.text_input("Ask a question about your documents")
# Disabled while the API is unreachable so users can't fire doomed requests.
if st.button("Ask", disabled=not connected):
    if not question.strip():
        st.warning("Type a question first.")
    else:
        # Append the user turn immediately so it shows even if the call fails.
        st.session_state.messages.append({"role": "user", "content": question})
        try:
            with st.spinner("Thinking…"):
                resp = requests.post(
                    f"{base_url}/chat",
                    json={"question": question, "top_k": 5},
                    timeout=CHAT_TIMEOUT,
                )
            if resp.status_code == 200:
                data = resp.json()
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": data["answer"],
                    "sources": data.get("sources", []),
                    "chunks_used": data.get("chunks_used", 0),
                })
            else:
                detail = resp.json().get("detail", resp.text) if resp.content else resp.text
                # sources=None marks this as an error turn (no expander rendered).
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": f"⚠️ Error ({resp.status_code}): {detail}",
                    "sources": None,
                })
        except requests.RequestException as exc:
            st.session_state.messages.append({
                "role": "assistant",
                "content": f"⚠️ Request failed: {exc}",
                "sources": None,
            })
        # Re-run so the new turns render in the history above the input box.
        st.rerun()
