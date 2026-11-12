"""
app.py — Streamlit UI for the Confluence Document Creation Agent.

Workflow:
1. User provides Topic, Source content notes, Size (short/medium/long), Confluence space, and parent page.
2. User clicks "Generate & Preview Document".
3. System runs OpenSearch indexing -> Bedrock generation -> Quality & citation validation.
4. User inspects preview, word count, and citation metrics.
5. User confirms creation.
6. System publishes page to Confluence via Atlassian MCP and indexes final document in OpenSearch.
7. Confluence URL is returned and displayed as a clickable link.
"""

from __future__ import annotations

import logging
import streamlit as st

import config
from auth_atlassian import AtlassianAuthManager
from document_generator import ConfluenceDocumentOrchestrator
from validators import DOCUMENT_SIZES

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

st.set_page_config(
    page_title="Confluence Document Creation Agent",
    page_icon="📝",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for styling
st.markdown(
    """
    <style>
    .reportview-container { background-color: #f7f9fc; }
    .stButton>button { font-weight: bold; border-radius: 6px; }
    .badge-success { background:#e3fcef; color:#006644; padding:4px 8px; border-radius:4px; font-weight:600; }
    .badge-warning { background:#fffae6; color:#974f0c; padding:4px 8px; border-radius:4px; font-weight:600; }
    .source-box { 
        background: #1e2638; 
        color: #e0e6ed; 
        border-left: 4px solid #4c9aff; 
        padding: 12px 16px; 
        border-radius: 6px; 
        margin-bottom: 12px; 
        font-size: 0.95rem; 
        line-height: 1.5;
    }
    .source-box b {
        color: #579dff;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def init_session_state() -> None:
    """Initialize persistent Streamlit session state."""
    if "orchestrator" not in st.session_state:
        st.session_state.orchestrator = ConfluenceDocumentOrchestrator()
    if "preview_data" not in st.session_state:
        st.session_state.preview_data = None
    if "published_result" not in st.session_state:
        st.session_state.published_result = None
    if "oauth_session_data" not in st.session_state:
        st.session_state.oauth_session_data = None
    if "jira_created_result" not in st.session_state:
        st.session_state.jira_created_result = None
    if "active_tab" not in st.session_state:
        st.session_state.active_tab = 0


init_session_state()
orch: ConfluenceDocumentOrchestrator = st.session_state.orchestrator


# ── Automatic OAuth Callback Handler ──────────────────────────────────────────
# If Atlassian redirected back with ?code=...
query_params = st.query_params
if "error" in query_params:
    error_code = query_params.get("error", "unknown_error")
    error_description = query_params.get("error_description", "Atlassian did not complete authorization.")
    st.error(f"Atlassian OAuth failed ({error_code}): {error_description}")
    st.info("Check that ATLASSIAN_OAUTH_REDIRECT_URI exactly matches this deployed app URL and is allowed by the Atlassian OAuth client.")
    st.query_params.clear()
elif "code" in query_params:
    auth_code = query_params["code"]
    oauth_session_data = st.session_state.oauth_session_data
    if not oauth_session_data and query_params.get("state"):
        oauth_session_data = orch.auth.load_pending_oauth(query_params["state"])
    try:
        if not oauth_session_data:
            raise RuntimeError("The pending OAuth transaction expired or could not be restored.")
        import asyncio
        with st.spinner("Completing Atlassian OAuth authentication..."):
            asyncio.run(
                orch.auth.complete_browser_oauth_exchange(
                    auth_code,
                    oauth_session_data,
                )
            )
        st.session_state.oauth_session_data = None
        st.query_params.clear()
        st.success("✅ Atlassian account successfully connected!")
        st.rerun()
    except Exception as exc:
        logger.exception("Atlassian OAuth callback failed")
        st.error(f"OAuth exchange failed: {exc}")


# ── Sidebar: Configuration & MCP Auth ─────────────────────────────────────────

with st.sidebar:
    st.title("📝 Doc Creator Agent")
    st.markdown("Automated, grounded Confluence page generation powered by Bedrock & OpenSearch.")

    st.divider()

    st.subheader("⚙️ System Status")
    provider = config.LLM_PROVIDER
    model = config.get_provider_model()
    st.success(f"🤖 LLM: **{provider.upper()}** (`{model}`)")

    if orch.opensearch.is_live:
        st.success(f"🔍 OpenSearch: **Connected** (`{config.OPENSEARCH_ENDPOINT}`)")
    else:
        st.info("🔍 OpenSearch: **Local Store Active** (Indexing ready)")

    st.divider()

    # ── Atlassian MCP Auth Panel ──────────────────────────────────────────────
    st.subheader("🔌 Atlassian MCP Integration")
    auth_mgr = orch.auth
    auth_status = auth_mgr.get_public_status()

    if auth_mgr.is_authenticated:
        st.markdown(
            f"""<div style="background:#1e2a3a;border-left:4px solid #36b37e;padding:8px 12px;border-radius:6px;font-size:0.85rem;margin-bottom:8px;color:#fff;">
            🟢 <b>Connected to Atlassian</b><br>
            User: <code>{auth_status['user_email']}</code><br>
            Cloud ID: <code>{auth_status.get('cloud_id') or config.ATLASSIAN_CLOUD_ID}</code><br>
            Token: <code>{auth_status['token_masked']}</code>
            </div>""",
            unsafe_allow_html=True,
        )
        if st.button("🚪 Disconnect Atlassian", key="btn_logout", use_container_width=True):
            auth_mgr.logout()
            st.rerun()
    else:
        st.warning("⚠️ Atlassian MCP is disconnected.")
        st.markdown(
            "Connect your Atlassian account in one click below. No terminal commands required."
        )

        if st.button("🔑 Connect with Atlassian (1-Click)", type="primary", key="btn_browser_oauth", use_container_width=True):
            import asyncio
            try:
                with st.spinner("Preparing Atlassian authorization link..."):
                    oauth_data = asyncio.run(orch.auth.generate_browser_oauth_url())
                    st.session_state.oauth_session_data = oauth_data
                    orch.auth.save_pending_oauth(oauth_data)
            except Exception as exc:
                st.error(f"Failed to generate authorization URL: {exc}")

        if st.session_state.oauth_session_data:
            auth_url = st.session_state.oauth_session_data["auth_url"]
            st.markdown(
                f"""
                <div style="background:#091e42;padding:12px;border-radius:6px;margin:8px 0;text-align:center;">
                    <a href="{auth_url}" target="_self" style="color:#ffffff;background:#0052cc;padding:8px 16px;border-radius:4px;text-decoration:none;font-weight:bold;display:inline-block;">
                        👉 Click to Authorize on Atlassian ↗
                    </a>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.caption("After approving in Atlassian, you will be redirected back here automatically.")

    st.divider()
    st.caption("Grounded Confluence Document Creator · Model Context Protocol v2")


# ── Main Content Area ─────────────────────────────────────────────────────────

st.header("📄 Confluence Document Creation Studio")
st.markdown(
    "Provide a topic, source materials, and target space. The agent indexes your source in "
    "**Amazon OpenSearch**, generates a grounded document via **Amazon Bedrock**, validates citations, "
    "and publishes to **Confluence** via Atlassian MCP with your approval."
)

tab1, tab2, tab3, tab4 = st.tabs(["1️⃣ Document Specification", "2️⃣ Review & Preview", "3️⃣ Publishing Status", "4️⃣ Create Jira Task"])

# ── TAB 1: Document Inputs ────────────────────────────────────────────────────
with tab1:
    with st.form("doc_input_form"):
        col1, col2 = st.columns([3, 2])

        with col1:
            topic_input = st.text_input(
                "Document Topic / Title *",
                placeholder="Enter the Confluence document title",
                help="The title of the document to be published in Confluence.",
            )

            source_input = st.text_area(
                "Source Content / Reference Notes *",
                placeholder="Paste source notes, requirements, meeting notes, or reference material here",
                height=220,
                help="Raw text, meeting notes, technical specifications, or compliance rules. Only facts in this source will be included.",
            )

        with col2:
            size_options = list(DOCUMENT_SIZES.keys())
            size_descriptions = [f"{k.capitalize()} ({DOCUMENT_SIZES[k].min_words}–{DOCUMENT_SIZES[k].max_words} words)" for k in size_options]
            selected_size_idx = st.selectbox(
                "Target Document Size *",
                range(len(size_options)),
                format_func=lambda i: size_descriptions[i],
                index=1,
            )
            selected_size = size_options[selected_size_idx]

            # Destination IDs are administrator configuration, not document
            # content. Keep them out of the user-facing form so users cannot
            # accidentally publish into the wrong Confluence location.
            space_input = config.CONFLUENCE_DEFAULT_SPACE
            parent_page_input = config.CONFLUENCE_PARENT_PAGE_ID or ""
            st.caption("📌 The Confluence destination is configured by the administrator.")

        submitted = st.form_submit_button("🚀 Generate & Preview Document", use_container_width=True)

        if submitted:
            if not topic_input.strip() or not source_input.strip():
                st.error("Please provide both a document title and source content.")
            else:
                with st.spinner("Processing..."):
                    preview = orch.prepare_document_preview(
                        topic=topic_input,
                        source_content=source_input,
                        size=selected_size,
                        space=space_input,
                        parent_page_id=parent_page_input or None,
                    )

                    if not preview.get("success"):
                        st.error(f"❌ Error during {preview.get('stage')}:")
                        for err in preview.get("errors", []):
                            st.write(f"- {err}")
                    else:
                        st.session_state.preview_data = preview
                        st.session_state.published_result = None
                        st.success("✅ Document generated and validated! Review the preview in Tab 2.")


# ── TAB 2: Review & Preview ───────────────────────────────────────────────────
with tab2:
    preview = st.session_state.preview_data
    if not preview:
        st.info("👈 Please enter your source content in Tab 1 and click **Generate & Preview Document**.")
    else:
        st.subheader(f"📑 Preview: {preview['topic']}")

        # Validation & Quality Report Cards
        q = preview["quality_report"]
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("Total Words", f"{q['word_count']} words")
        with c2:
            st.metric("Target Range", q["target_range"])
        with c3:
            st.metric("Inline Citations", f"{q['citation_count']} references")
        with c4:
            st.metric("LLM Provider", f"{preview['provider'].upper()}")

        if q["warnings"]:
            for w in q["warnings"]:
                st.warning(f"⚠️ {w}")
        else:
            st.success("🎯 Quality checks passed: Word count within target range & inline source citations verified.")

        with st.expander("🔍 View Retrieved Source Passages (Amazon OpenSearch)"):
            for p in preview["retrieved_passages"]:
                st.markdown(
                    f"""<div class="source-box">
                    <b>Passage [Source {p['id']}]</b> (Relevance Score: {p.get('score', 1.0)})<br>
                    {p['content']}
                    </div>""",
                    unsafe_allow_html=True,
                )

        st.divider()
        col_hdr, col_dl_md, col_dl_txt, col_dl_md5 = st.columns([2.5, 1, 1, 1])
        with col_hdr:
            st.markdown("### Document Content (Markdown Preview)")

        import hashlib
        doc_bytes = preview["document_markdown"].encode("utf-8")
        doc_md5_hash = hashlib.md5(doc_bytes).hexdigest()
        base_filename = preview["topic"].lower().replace(" ", "_")[:40]

        with col_dl_md:
            st.download_button(
                label="📥 Download .md",
                data=preview["document_markdown"],
                file_name=f"{base_filename}.md",
                mime="text/markdown",
                use_container_width=True,
            )
        with col_dl_txt:
            st.download_button(
                label="📥 Download .txt",
                data=preview["document_markdown"],
                file_name=f"{base_filename}.txt",
                mime="text/plain",
                use_container_width=True,
            )
        with col_dl_md5:
            # Checksum / MD5 verification file
            md5_content = f"{doc_md5_hash}  {base_filename}.md\n"
            st.download_button(
                label="📥 Download .md5",
                data=md5_content,
                file_name=f"{base_filename}.md5",
                mime="text/plain",
                use_container_width=True,
                help=f"MD5 checksum: {doc_md5_hash}",
            )

        st.markdown(preview["document_markdown"])

        st.divider()
        st.subheader("🛡️ User Confirmation & Publishing")
        st.markdown(
            f"Ready to publish to Confluence space `**{preview['space']}**` via **Atlassian MCP**?"
        )

        col_pub, col_cancel = st.columns([1, 4])
        with col_pub:
            if st.button("✅ Confirm & Publish to Confluence", type="primary", use_container_width=True):
                with st.spinner("Publishing page through Atlassian MCP & indexing final doc in OpenSearch..."):
                    res = orch.publish_confirmed_document(
                        topic=preview["topic"],
                        document_markdown=preview["document_markdown"],
                        space=preview["space"],
                        parent_page_id=preview.get("parent_page_id"),
                    )
                    st.session_state.published_result = res
                    st.success("🎉 Page published successfully! Check Tab 3.")
        with col_cancel:
            if st.button("❌ Discard Preview", use_container_width=False):
                st.session_state.preview_data = None
                st.rerun()


# ── TAB 3: Publishing Status ──────────────────────────────────────────────────
with tab3:
    pub = st.session_state.published_result
    if not pub:
        st.info("No published documents in this session yet.")
    else:
        st.success("🎉 Confluence Document Successfully Published!")
        st.markdown(
            f"""
            - **Target Space:** `{pub['space']}`
            - **Page ID:** `{pub['page_id']}`
            - **OpenSearch Final Document ID:** `{pub['opensearch_doc_id']}`
            """
        )
        if pub.get("page_url"):
            st.markdown(
                f"""
                <div style="background:#deebff;border:2px solid #0052cc;padding:16px;border-radius:8px;text-align:center;margin-top:16px;">
                <h3 style="color:#0747a6;margin:0 0 10px 0;">🔗 Click to View Your New Confluence Document</h3>
                <a href="{pub['page_url']}" target="_blank" style="font-size:1.1rem;font-weight:bold;color:#0052cc;text-decoration:none;">
                {pub['page_url']} ↗
                </a>
                </div>
                """,
                unsafe_allow_html=True,
            )


# ── TAB 4: Create Jira Task ───────────────────────────────────────────────────
with tab4:
    st.subheader("🎫 Create a Jira Task / Issue")
    st.markdown(
        "Directly create a new work item on your Jira board via **Atlassian MCP**. "
        "Every write operation displays a preview with full confirmation before being submitted."
    )

    with st.form("jira_issue_form"):
        col_j1, col_j2 = st.columns([3, 2])

        with col_j1:
            jira_summary = st.text_input(
                "Task Summary / Title *",
                placeholder="Enter a concise Jira task title",
                help="Brief title of the task to be created on the Jira board.",
            )
            jira_description = st.text_area(
                "Task Description (Markdown supported)",
                placeholder="Describe the task, acceptance criteria, or implementation notes",
                height=200,
                help="Detailed specifications, acceptance criteria, or implementation notes.",
            )

        with col_j2:
            jira_project = st.text_input(
                "Jira Project Key *",
                placeholder="Enter the Jira project key (e.g. KAN)",
                help="The key of the Jira project (e.g. KAN, DEV, PROJ).",
            )
            jira_issue_type = st.selectbox(
                "Issue Type *",
                ["Task", "Story", "Bug", "Epic", "Subtask"],
                index=0,
            )
            jira_priority = st.selectbox(
                "Priority",
                ["Medium", "High", "Highest", "Low", "Lowest"],
                index=0,
            )
            jira_labels_str = st.text_input(
                "Labels (Optional, comma-separated)",
                placeholder="e.g. compliance, backend, urgent",
                help="e.g. compliance, backend, urgent",
            )

        submit_jira = st.form_submit_button("🚀 Submit to Jira Board", type="primary", use_container_width=True)

        if submit_jira:
            if not jira_summary.strip() or not jira_project.strip():
                st.error("Please provide both a task title and Jira project key.")
            else:
                labels_list = [l.strip() for l in jira_labels_str.split(",") if l.strip()]
                with st.spinner("Submitting task to Jira via Atlassian MCP..."):
                    jira_res = orch.create_jira_task(
                        project_key=jira_project,
                        summary=jira_summary,
                        description=jira_description,
                        issue_type=jira_issue_type,
                        priority=jira_priority,
                        labels=labels_list,
                    )

                    if not jira_res.get("success"):
                        st.error("❌ Failed to create Jira issue:")
                        for err in jira_res.get("errors", []):
                            st.write(f"- {err}")
                    else:
                        st.session_state.jira_created_result = jira_res["issue"]
                        st.success(f"🎉 Jira issue **{jira_res['issue']['key']}** successfully created!")

    # Display Jira Result Card if available
    jira_created = st.session_state.jira_created_result
    if jira_created:
        st.markdown(
            f"""
            <div style="background:#e3fcef;border:2px solid #006644;padding:16px;border-radius:8px;margin-top:16px;">
                <h3 style="color:#006644;margin:0 0 8px 0;">✅ Jira Issue Created: {jira_created['key']}</h3>
                <p><b>Summary:</b> {jira_created['summary']}<br>
                <b>Project:</b> <code>{jira_created['project_key']}</code> &nbsp;·&nbsp;
                <b>Type:</b> {jira_created['issue_type']} &nbsp;·&nbsp;
                <b>Priority:</b> {jira_created['priority']}</p>
                <a href="{jira_created['url']}" target="_blank" style="font-size:1.05rem;font-weight:bold;color:#0052cc;text-decoration:none;">
                    🔗 View Issue on Jira Board: {jira_created['key']} ↗
                </a>
            </div>
            """,
            unsafe_allow_html=True,
        )

