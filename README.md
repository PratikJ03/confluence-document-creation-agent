# Confluence Document Creation Agent

An enterprise AI agent that generates grounded, high-quality technical documentation from user-supplied source materials and publishes them directly to **Atlassian Confluence** using the **Model Context Protocol (MCP)**, **Amazon OpenSearch**, and **Amazon Bedrock**.

---

## 🏛️ Architecture Workflow

```
User Topic + Source Notes + Target Space + Size
                     ↓
         1. Input Validation
                     ↓
    2. Amazon OpenSearch Passage Indexing
                     ↓
   3. Relevant Source Passage Retrieval
                     ↓
       4. Amazon Bedrock (Nova Micro)
                     ↓
   5. Anti-Hallucination & Citation Check
                     ↓
   6. Word Count & Coverage Validation
                     ↓
      7. User Preview & Quality Report
                     ↓
      8. User Explicit Confirmation
                     ↓
       9. Atlassian MCP Publishing
                     ↓
    10. Return Clickable Confluence URL
                     ↓
11. Final Document Indexed in OpenSearch
```

---

## 🚀 Getting Started

### 1. Prerequisites & Virtual Environment
From your powershell terminal:
```powershell
cd "I:\AI agent\Document_Creation_agent"
# You can use the existing virtual environment or create one:
..\book-ai-agent\venv\Scripts\pip install -r requirements.txt
```

### 2. Environment Variables
Copy `.env.example` to `.env` and configure your credentials:
```powershell
cp .env.example .env
```
Key settings:
- `LLM_PROVIDER=bedrock` (default)
- `BEDROCK_MODEL_ID=amazon.nova-micro-v1:0`
- `ATLASSIAN_MCP_URL=https://mcp.atlassian.com/v2/mcp`
- `OPENSEARCH_ENDPOINT=` (optional; falls back to in-memory store if blank)

### 3. Running with Docker (Recommended)

Build and launch the container with Docker Compose:
```powershell
cd "I:\AI agent\Document_Creation_agent"
docker compose up -d
```
Access the application at: **`http://localhost:8501`**

To stop the container:
```powershell
docker compose down
```

### 4. Running Locally (Without Docker)
```powershell
cd "I:\AI agent\Document_Creation_agent"
..\book-ai-agent\venv\Scripts\streamlit run app.py
```

### 5. Running the Automated Tests
```powershell
cd "I:\AI agent\Document_Creation_agent"
..\book-ai-agent\venv\Scripts\pytest tests
```

