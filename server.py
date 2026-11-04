#!/usr/bin/env python3
"""
server.py — FastAPI backend for the CCF chatbot.

Provides:
  POST /chat       — Ask a question, get a grounded answer with source citations
  POST /reindex    — Re-crawl and re-index (admin endpoint)
  GET  /health     — Health check

Environment variables:
  PORT              — Server port (default: 8080)
  INDEX_DIR         — Path to data/ directory (default: ./data/)
  CRAWL_SCRIPT      — Path to crawl.py (default: ./crawl.py)
  INDEX_SCRIPT      — Path to index.py (default: ./index.py)
  DISCLAIMER_TEXT   — Override the default disclaimer
  CONTACT_EMAIL     — Contact email (default: office@cornwallfoundation.com)
  CONTACT_PHONE     — Contact phone (default: 01566 779 333)
  USE_LLM           — Set to "true" to enable LLM-powered answers
  OPENROUTER_API_KEY — API key for OpenRouter (required if USE_LLM=true)
"""

import json
import math
import os
import pickle
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

HERE = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("INDEX_DIR", HERE / "data"))
CRAWL_SCRIPT = Path(os.environ.get("CRAWL_SCRIPT", HERE / "crawl.py"))
INDEX_SCRIPT = Path(os.environ.get("INDEX_SCRIPT", HERE / "index.py"))
PORT = int(os.environ.get("PORT", "8080"))

DISCLAIMER = os.environ.get(
    "DISCLAIMER_TEXT",
    "Answers are generated from the CCF website content and may be incomplete. "
    "Always confirm critical information with the CCF team.",
)
CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "office@cornwallfoundation.com")
CONTACT_PHONE = os.environ.get("CONTACT_PHONE", "01566 779 333")

# ---------------------------------------------------------------------------
# Search engine
# ---------------------------------------------------------------------------

STOP_WORDS = set(
    "a an the and or but in on at to for of with by from as is it are was were "
    "be been has have had do does did will would could should may might must "
    "shall can need dare ought used this that these those i you he she we they "
    "me him her us them my your his her its our their mine yours his hers its "
    "ours theirs myself yourself himself herself itself ourselves yourselves "
    "themselves what which who whom whose when where why how all each every "
    "both few more most other some such no nor not only own same so than too "
    "very just about above across after against along among around before "
    "behind below beneath beside between beyond down during inside into "
    "outside over through throughout under underneath until up upon within "
    "without here there"
    .split()
)


def tokenize(text: str) -> list[str]:
    """Tokenize and clean text into lowercase words."""
    text = text.lower()
    tokens = re.findall(r"[a-z0-9']+(?:[a-z0-9-]+)*", text)
    return [t for t in tokens if len(t) > 1 and t not in STOP_WORDS]


# Query expansion map — domain-specific synonyms to improve BM25 relevance
QUERY_EXPANSIONS = {
    "address": ["contact", "visit", "office", "location", "find", "where"],
    "apply": ["application", "applicant", "process", "guidance", "submit"],
    "eligibility": ["eligible", "criteria", "qualify", "requirements"],
    "phone": ["telephone", "call", "contact", "number", "reach"],
    "email": ["contact", "mail", "reach"],
    "funding": ["grant", "money", "support", "fund", "award"],
    "grant": ["funding", "fund", "award", "money", "support"],
    "documents": ["paperwork", "forms", "application", "supporting", "upload"],
    "deadline": ["closing date", "when", "due", "cutoff", "timeframe"],
    "who": ["eligible", "can", "organisation", "charity", "group"],
    "help": ["support", "assistance", "guidance", "advice", "contact"],
}

# ---------------------------------------------------------------------------
# Load index
# ---------------------------------------------------------------------------

_index_data = None  # {index: dict, chunks: list[dict]}
_chunks = []


def load_index() -> bool:
    """Load the BM25 index and chunk metadata from disk."""
    global _index_data, _chunks

    index_path = DATA_DIR / "index.pkl"

    if not index_path.exists():
        print("No index found. Run crawl.py + index.py first.", file=sys.stderr)
        return False

    print(f"Loading index from {index_path}...", file=sys.stderr)
    with open(index_path, "rb") as f:
        _index_data = pickle.load(f)

    _chunks = _index_data["chunks"]
    print(f"Index loaded: {len(_chunks)} chunks, {len(_index_data['index']['index'])} words", file=sys.stderr)
    return True


def search(query: str, top_k: int = 5) -> list[dict]:
    """BM25 search with query expansion. Returns top_k chunks sorted by relevance."""
    if _index_data is None:
        return []

    query_tokens = tokenize(query)
    if not query_tokens:
        return []

    # Expand query with domain synonyms
    expanded_tokens = set(query_tokens)
    for qt in query_tokens:
        for base_word, expansions in QUERY_EXPANSIONS.items():
            if base_word in qt or qt in base_word:
                for exp in expansions:
                    expanded_tokens.update(tokenize(exp))

    index = _index_data["index"]["index"]
    doc_freq = _index_data["index"]["doc_freq"]
    num_chunks = _index_data["index"]["num_chunks"]
    avg_chunk_len = _index_data["index"]["avg_chunk_len"]

    k1 = 1.5
    b = 0.75

    scores = {}
    for word in expanded_tokens:
        if word not in index:
            continue
        idf = math.log((num_chunks - doc_freq[word] + 0.5) / (doc_freq[word] + 0.5) + 1.0)
        for chunk_idx, tf in index[word].items():
            chunk_len = len(tokenize(_chunks[chunk_idx]["text"]))
            score = idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * chunk_len / avg_chunk_len))
            # Boost exact query token matches
            if word in query_tokens:
                score *= 1.3
            # Penalise PDF chunks — they tend to be noisy
            url = _chunks[chunk_idx].get("url", "")
            if url.lower().endswith(".pdf"):
                score *= 0.5
            scores[chunk_idx] = scores.get(chunk_idx, 0.0) + score

    if not scores:
        return []

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    results = []
    for chunk_idx, score in ranked[:top_k]:
        chunk = _chunks[chunk_idx]
        results.append({
            "url": chunk["url"],
            "title": chunk["title"],
            "text": chunk["text"],
            "score": round(score, 3),
        })

    return results


# ---------------------------------------------------------------------------
# Answer generation
# ---------------------------------------------------------------------------

def _extract_relevant_sentences(chunk_text: str, max_sentences: int = 1) -> str:
    """
    Extract a short, factual sentence from a chunk.
    Prefers the shortest non-boilerplate sentence that is informative.
    """
    text = re.sub(r"\s+", " ", chunk_text).strip()
    if not text:
        return ""

    # Split into sentences
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z\"'(])", text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 15]

    if not sentences:
        return text[:150] + ("..." if len(text) > 150 else "")

    # Key fact markers — sentences containing these are preferred
    key_markers = {
        "address", "phone", "email", "office", "charity number",
        "charitable", "grant", "funding", "eligible", "apply",
        "application", "criteria", "registered", "support",
        "community foundation", "contact", "visit", "find us",
    }

    boilerplate = {
        "cookie", "accept", "all rights reserved", "copyright", "subscribe",
        "newsletter", "sign up", "quick links", "share this", "follow us",
        "skip to content", "menu", "search", "footer", "sidebar",
    }

    scored = []
    for s in sentences:
        low = s.lower()
        bp_score = sum(3 for b in boilerplate if b in low)
        key_score = sum(2 for k in key_markers if k in low)
        # Strongly prefer concise sentences (30-120 chars)
        length = len(s)
        if 30 <= length <= 120:
            length_score = 0
        elif length > 200:
            length_score = -3
        else:
            length_score = -1
        score = key_score - bp_score + length_score
        scored.append((score, s))

    # Pick best sentence
    scored.sort(key=lambda x: (-x[0], x[1]))
    best = scored[0][1]

    # Trim to one sentence max
    if len(best) > 200:
        best = best[:197].rsplit(".", 1)[0] + "."

    return best


# Common factual answers — used before BM25 fallback for precision
COMMON_ANSWERS = {
    # Multi-word keys checked first in _check_common_answer
    "address": "CCF's office address is: 1st Floor Aspect House, 17 Callywith Gate, Bodmin, Cornwall PL31 2RQ",
    "phone": "CCF's phone number is: 01566 779 333",
    "email": "CCF's email is: office@cornwallfoundation.com",
    "amy fairman": "Press & PR contact: amy.fairman@cornwallfoundation.com",
    "charity number": "CCF's charity number is 1099977 and company number is 04816191",
    "grants": "CCF offers grants through various funds. Check the available grants page for current opportunities: https://cornwallcommunityfoundation.com/cornwall-charity-grants/grants/",
    "application": "To apply for a grant, visit the Application Process & Guidance page: https://cornwallcommunityfoundation.com/cornwall-charity-grants/application-process-guidance/",
}


def _check_common_answer(query: str) -> Optional[str]:
    """Return a direct factual answer for common queries, or None."""
    q = query.lower()
    # Check multi-word keys first (more specific — higher priority)
    for key in sorted(COMMON_ANSWERS, key=len, reverse=True):
        if key in q:
            return COMMON_ANSWERS[key]
    if "find" in q and ("office" in q or "ccf" in q or "you" in q or "us" in q):
        return COMMON_ANSWERS["address"]
    if "where" in q and ("located" in q or "are" in q or "office" in q):
        return COMMON_ANSWERS["address"]
    if "how to contact" in q or "contact number" in q or ("call" in q and "ccf" in q.lower()):
        return COMMON_ANSWERS["phone"]
    return None


def build_answer(retrieved: list[dict], query: str) -> str:
    """
    Generate a concise grounded answer from retrieved chunks.

    Returns a short summary with source citations. Set USE_LLM=true
    environment variable to enable LLM-powered natural answers instead.
    """
    if not retrieved:
        return (
            "I couldn't find an answer to that in the CCF website content. "
            f"Please contact the CCF team directly: email {CONTACT_EMAIL} or call {CONTACT_PHONE}."
        )

    # Check for common factual queries first
    common = _check_common_answer(query)
    if common:
        return f"• {common}"

    # Check if LLM-powered generation is enabled
    if os.environ.get("USE_LLM", "").lower() in ("true", "1", "yes"):
        return _build_answer_llm(retrieved, query)

    # Deduplicate sources by URL
    seen_urls = set()
    unique_chunks = []
    for r in retrieved:
        if r["url"] not in seen_urls:
            seen_urls.add(r["url"])
            unique_chunks.append(r)

    # Build short bullet-point answer from BM25 results
    seen_titles = set()
    bullet_items = []
    for r in retrieved:
        if r["url"] not in seen_urls:
            snippet = _extract_relevant_sentences(r["text"])
            if snippet and r["title"] not in seen_titles:
                seen_titles.add(r["title"])
                bullet_items.append(snippet)

    if not bullet_items:
        bullet_items = [_extract_relevant_sentences(retrieved[0]["text"])]

    answer_parts = []
    for item in bullet_items[:3]:
        answer_parts.append(f"• {item}")

    # Source list — just URLs
    for i, r in enumerate(unique_chunks[:5], 1):
        answer_parts.append(r['url'])

    return "\n".join(answer_parts)


def _build_answer_llm(retrieved: list[dict], query: str) -> str:
    """
    Generate a concise natural-language answer using OpenRouter API.
    Enabled by setting USE_LLM=true in the environment.
    """
    seen_urls = set()
    unique_chunks = []
    for r in retrieved:
        if r["url"] not in seen_urls:
            seen_urls.add(r["url"])
            unique_chunks.append(r)

    context = "\n\n".join(
        f"[{c['title']}]({c['url']}):\n{c['text'][:500]}"
        for c in unique_chunks[:3]
    )

    system_prompt = (
        "You are a helpful chatbot for Cornwall Community Foundation. "
        "Answer using ONLY the website content below. "
        "Answer concisely — 2-3 sentences max. No fluff, no greetings, no disclaimers. "
        "If the content doesn't answer the question accurately, direct them to contact CCF.\n\n"
        "### Key facts (always accurate):\n"
        "- Phone: 01566 779333\n"
        "- Email: office@cornwallfoundation.com\n"
        "- Grants enquiries: grants@cornwallfoundation.com\n"
        "- Address: 1st Floor Aspect House, 17 Callywith Gate, Bodmin, Cornwall PL31 2RQ\n"
        "- Charity number: 1099977\n"
        "- Company number: 04816191\n\n"
        f"### Website content retrieved for this question:\n{context}"
    )

    try:
        import requests as req
        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        if not api_key:
            # Fallback: use embedded key
            api_key = "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"
        resp = req.post(
            "https://openrouter.ai/api/v1/chat/completions",
            json={
                "model": "deepseek/deepseek-v4-flash",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": query}
                ]
            },
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=15,
        )
        answer = resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        answer = f"Could not generate LLM answer ({e}). Using template fallback."

    # Append sources (top 2 only, just URLs)
    parts = [answer]
    seen = set()
    count = 0
    for r in retrieved:
        url = r["url"]
        if url not in seen and count < 2:
            seen.add(url)
            parts.append(url)
            count += 1
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="CCF Chatbot API",
    description="Retrieval-augmented chatbot for Cornwall Community Foundation",
    version="1.2.0",
)

# CORS — allow embedding from any origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# Serve static widget files
widget_dir = HERE / "widget"
if widget_dir.exists():
    app.mount("/widget", StaticFiles(directory=str(widget_dir)), name="widget")


# ---------------------------------------------------------------------------
# Request/response models
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str
    top_k: int = 5


class ChatResponse(BaseModel):
    answer: str
    sources: list[dict]
    disclaimer: str
    contact_email: str
    contact_phone: str


class ReindexResponse(BaseModel):
    status: str
    message: str
    pages_crawled: Optional[int] = None
    chunks_created: Optional[int] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "num_chunks": len(_chunks) if _chunks else 0,
        "vocabulary_size": len(_index_data["index"]["index"]) if _index_data else 0,
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    if not req.message.strip():
        raise HTTPException(400, "Message cannot be empty")

    if _index_data is None:
        loaded = load_index()
        if not loaded:
            return ChatResponse(
                answer=(
                    "The chatbot knowledge base is not yet built. "
                    f"Please contact the CCF team at {CONTACT_EMAIL} "
                    f"or call {CONTACT_PHONE} for assistance."
                ),
                sources=[],
                disclaimer=DISCLAIMER,
                contact_email=CONTACT_EMAIL,
                contact_phone=CONTACT_PHONE,
            )

    # Retrieve relevant chunks
    retrieved = search(req.message, req.top_k)

    if not retrieved:
        return ChatResponse(
            answer=(
                "I couldn't find an answer to that in the CCF website content. "
                f"Please contact the CCF team directly: email {CONTACT_EMAIL} or call {CONTACT_PHONE}."
            ),
            sources=[],
            disclaimer=DISCLAIMER,
            contact_email=CONTACT_EMAIL,
            contact_phone=CONTACT_PHONE,
        )

    # Build answer
    answer = build_answer(retrieved, req.message)

    # Prepare source list
    seen = set()
    sources = []
    for r in retrieved:
        if r["url"] not in seen:
            seen.add(r["url"])
            sources.append({
                "url": r["url"],
                "title": r["title"],
            })

    return ChatResponse(
        answer=answer,
        sources=sources,
        disclaimer=DISCLAIMER,
        contact_email=CONTACT_EMAIL,
        contact_phone=CONTACT_PHONE,
    )


@app.post("/reindex", response_model=ReindexResponse)
async def reindex():
    """Re-crawl the site and rebuild the index."""
    try:
        print("Starting reindex...", file=sys.stderr)

        # Step 1: Crawl
        result = subprocess.run(
            [sys.executable, str(CRAWL_SCRIPT)],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Crawl failed: {result.stderr}")

        pages_crawled = None
        for line in result.stdout.splitlines():
            if "Saved" in line:
                for part in line.split():
                    if part.isdigit():
                        pages_crawled = int(part)
                        break

        # Step 2: Index
        result = subprocess.run(
            [sys.executable, str(INDEX_SCRIPT)],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Index failed: {result.stderr}")

        chunks_created = None
        for line in result.stdout.splitlines():
            if "Created" in line and "chunks" in line:
                for part in line.split():
                    if part.isdigit():
                        chunks_created = int(part)
                        break

        # Reload
        load_index()

        return ReindexResponse(
            status="ok",
            message="Index rebuilt successfully",
            pages_crawled=pages_crawled,
            chunks_created=chunks_created,
        )

    except Exception as e:
        return ReindexResponse(
            status="error",
            message=str(e),
        )


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def startup():
    load_index()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)