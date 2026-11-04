# CCF Applicant Chatbot

A retrieval-augmented chatbot for [Cornwall Community Foundation](https://cornwallcommunityfoundation.com/), designed to answer applicant questions about grants, eligibility, and the application process — grounded entirely in the site's own content.

## Quick start

```bash
pip install -r requirements.txt
python crawl.py          # Fetch all pages
python index.py          # Build vector index
python server.py         # Start API server (port 8080)
```

Open `http://localhost:8080/widget/demo.html` to see the widget in action.

## Architecture

```
┌─────────────────┐     ┌─────────────────────────┐     ┌──────────────────┐
│  crawl.py        │ ──▶ │  index.py                │ ──▶ │  server.py        │
│  Fetches 27      │     │  Chunks + BM25 keyword   │     │  FastAPI backend  │
│  pages from      │     │  index (pure Python, no  │     │  POST /chat       │
│  pages.txt       │     │  ML deps)                │     │  POST /reindex    │
└─────────────────┘     └─────────────────────────┘     └──────────────────┘
                                                          │
                                                  ┌───────▼────────┐
                                                  │  widget/       │
                                                  │  embed.js      │
                                                  │  (embeddable)  │
                                                  └────────────────┘
```

### Components

| File | Purpose |
|------|---------|
| `crawl.py` | Fetches each page in `data/pages.txt`, extracts clean text, saves to `data/pages_content.json` |
| `index.py` | Chunks text into 500-char segments (80-char overlap), builds BM25 keyword index (pure Python, no heavy deps) |
| `server.py` | FastAPI server with `POST /chat` (question → BM25 search → answer + source citations), `POST /reindex`, `GET /health` |
| `widget/embed.js` | Self-contained JS widget. No framework dependencies. Adds a floating chat button to any page. |
| `widget/demo.html` | Demo page with embed instructions |

## How to embed

### Option 1: Script tag (recommended)

Add this just before `</body>` on any page:

```html
<script src="https://your-server.com/widget/embed.js"
        data-api-base="https://your-server.com"
        data-primary-color="#1E3A5F"
        data-position="bottom-right"
        data-title="Ask CCF"></script>
```

### Option 2: JavaScript init

```html
<script src="https://your-server.com/widget/embed.js"></script>
<script>
  CCFChatbot.init({
    apiBase: "https://your-server.com",
    primaryColor: "#1E3A5F",
    position: "bottom-right",
    title: "Ask CCF"
  });
</script>
```

### Configuration options

| Option | Default | Description |
|--------|---------|-------------|
| `apiBase` | `window.location.origin` | Backend server URL |
| `position` | `"bottom-right"` | `"bottom-right"` or `"bottom-left"` |
| `primaryColor` | `"#1E3A5F"` | Header/button colour |
| `title` | `"Ask CCF"` | Widget header text |
| `greeting` | `"Hi! I can answer..."` | Initial bot message |
| `placeholder` | `"Type your question..."` | Input placeholder text |

## API reference

### `POST /chat`

Request:
```json
{ "message": "What documents do I need to apply for a grant?", "top_k": 5 }
```

Response:
```json
{
  "answer": "Based on the CCF website... [Source 1]...",
  "sources": [
    { "url": "https://cornwallcommunityfoundation.com/eligibility-criteria/", "title": "Eligibility criteria" }
  ],
  "disclaimer": "Answers are generated from the CCF website content...",
  "contact_email": "office@cornwallfoundation.com",
  "contact_phone": "01566 779 333"
}
```

### `POST /reindex`

Re-crawls all pages and rebuilds the index. No request body needed.

### `GET /health`

Returns `{ "status": "ok", "index_size": 142, "num_chunks": 142 }`.

## How to re-index

The chatbot only knows about content it has indexed. When the CCF website content changes:

1. **Update `data/pages.txt`** — add or remove URLs as needed
2. **Run `python crawl.py`** — re-fetches all pages
3. **Run `python index.py`** — rebuilds the vector index
4. **(No server restart needed)** — the `POST /reindex` endpoint does all three steps

Or use the `POST /reindex` endpoint remotely (requires the server to have access to the page list).

## Updating the disclaimer

The disclaimer text is configured in `server.py` or via the `DISCLAIMER_TEXT` environment variable:

```bash
DISCLAIMER_TEXT="Answers may be incomplete. Contact us at help@ccf.org" python server.py
```

## Pages indexed

Indexed on **2026-07-19**. The following pages are included (27 pages successfully crawled):

| Category | Pages |
|----------|-------|
| **Home** | Homepage |
| **Grants** | Main grants page, available grants list, SWEF, Clare Milne Trust, Young & Talented, People in Mind, Resilience Fund, Headland Hotel |
| **Application** | Application process & guidance, FAQs, terms & conditions, applicant training |
| **Eligibility** | Eligibility criteria |
| **About** | About us, our people, our finances, our fundholders |
| **Giving** | Ways to give, give to your community |
| **Impact** | Impact strategy |
| **Support** | Contact us, policies, insights, news, community stories, careers |

> **Note:** 3 URLs from the original list returned 404 (Emily Bolitho Fund, Goonhilly Wind Farm Fund, One Programme) and were removed. Add replacement URLs to `data/pages.txt` and re-run `crawl.py` + `index.py`.

## GDPR & data privacy

- **No personal data is logged** by the chatbot. The server does not store chat history, IP addresses, or user identifiers.
- **No cookies or tracking** are used.
- **The widget is fully client-side** — no third-party analytics or CDN dependencies.
- **If the site collects applicant personal data** (names, application IDs) via the chat, a privacy notice should be added to the site explaining how this data is processed.

## Known limitations

1. **Content scope** — The chatbot can only answer questions based on pages listed in `data/pages.txt`. If a new page or grant programme is added, the index must be rebuilt.
2. **PDFs not indexed** — PDF documents (annual reports, resource booklets) are not automatically crawled. To include them, extract their text and add them as a separate step.
3. **JavaScript-rendered content** — `crawl.py` uses HTTP requests, not a headless browser. The CCF site is WordPress (server-rendered), so this is fine.
4. **Fallback answer** — The current server uses a template-based fallback answer that extracts the most relevant text. For best results, configure an LLM API key (OpenAI, Anthropic, or local) in `server.py`'s `generate_answer()` function.
5. **Similarity threshold** — Results below 0.3 cosine similarity are discarded. This prevents irrelevant answers but may cause the bot to decline questions about content that's only tangentially related.
6. **Mobile** — The widget is responsive and works on mobile viewports. The chatbox adapts to `calc(100vw - 24px)` on small screens.

## Deployment options

### Option A: Small VPS (recommended)

```bash
# Ubuntu/Debian
sudo apt install python3 python3-pip
git clone <this-repo> /opt/ccf-chatbot
cd /opt/ccf-chatbot
pip install -r requirements.txt
python crawl.py && python index.py

# Run with systemd or supervisor
python server.py
```

**Minimum requirements:** 1 vCPU, 1 GB RAM, 2 GB disk (the embedding model is ~80 MB).

### Option B: Serverless (AWS Lambda / Google Cloud Run)

The `server.py` is a standard FastAPI app. Package it in a Docker container and deploy to Cloud Run or similar. Note that the FAISS index (~2 MB) and embedding model (~80 MB) must be bundled with the container.

### Option C: Railway / Fly.io / Render

One-click deploy from a Git repo. Add `pip install -r requirements.txt` to the build step and `python server.py` as the start command.

## Development

```bash
# Install dependencies
pip install -r requirements.txt

# Crawl the site (27 pages)
python crawl.py

# Build the BM25 keyword index
python index.py

# Start the server
python server.py

# The server runs on http://0.0.0.0:8080
# If port 8080 is taken, set: PORT=9090 python server.py
# Widget available at http://your-server:8080/widget/embed.js

MIT — free to use, modify, and deploy.