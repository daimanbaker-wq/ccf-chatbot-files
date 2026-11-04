#!/usr/bin/env python3
"""
index.py — Build a keyword search index from crawled page content.

Uses a simple term-frequency scoring approach (BM25-like) that works
instantly on any machine — no heavy ML dependencies.

Usage:
    python index.py [--input data/pages_content.json] [--output data/]
"""

import argparse
import json
import math
import os
import re
import sys
import pickle
from collections import Counter
from pathlib import Path

# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

CHUNK_SIZE = 500
CHUNK_OVERLAP = 80


def chunk_text(text: str, url: str, title: str) -> list[dict]:
    """Split text into overlapping chunks at sentence boundaries.

    Each chunk starts at the beginning of a sentence (not mid-sentence).
    Chunks are approximately CHUNK_SIZE characters, with CHUNK_OVERLAP
    overlap, but always break at sentence boundaries when possible.
    """
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    if not text:
        return []

    # Split into sentences (handles . ! ? and common abbreviations)
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z\"'(])", text)
    sentences = [s.strip() for s in sentences if s.strip()]

    if not sentences:
        return []

    chunks = []
    chunk_idx = 0
    start = 0

    while start < len(sentences):
        # Accumulate sentences until we hit CHUNK_SIZE
        chunk_sentences = []
        char_count = 0
        end = start

        while end < len(sentences):
            s_len = len(sentences[end]) + 1  # +1 for space
            if char_count + s_len > CHUNK_SIZE and char_count > 30:
                break
            chunk_sentences.append(sentences[end])
            char_count += s_len
            end += 1

        if not chunk_sentences:
            # Single sentence longer than CHUNK_SIZE — force-split it
            chunk_sentences = [sentences[start]]
            end = start + 1

        chunk_text = " ".join(chunk_sentences)
        if chunk_text and len(chunk_text) > 30:
            chunks.append({
                "chunk_id": f"{url}#chunk-{chunk_idx}",
                "url": url,
                "title": title,
                "text": chunk_text,
                "chunk_index": chunk_idx,
            })
            chunk_idx += 1

        # Advance by CHUNK_SIZE - CHUNK_OVERLAP sentences
        advance = max(1, end - start - max(1, CHUNK_OVERLAP // 50))
        start = end - (CHUNK_OVERLAP // 50) if end - (CHUNK_OVERLAP // 50) > start else end
        if start >= end:
            start = end

    return chunks


# ---------------------------------------------------------------------------
# Simple keyword-based search index
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


def build_chunk_index(chunks: list[dict]) -> dict:
    """
    Build an inverted index: word -> {chunk_idx: term_frequency}.
    Also compute document frequencies for BM25.
    """
    word_to_chunks = {}  # word -> {chunk_idx: tf}
    doc_freq = {}        # word -> number of chunks containing it

    for idx, chunk in enumerate(chunks):
        tokens = tokenize(chunk["text"])
        counter = Counter(tokens)
        for word, count in counter.items():
            if word not in word_to_chunks:
                word_to_chunks[word] = {}
            word_to_chunks[word][idx] = count
            doc_freq[word] = doc_freq.get(word, 0) + 1

    return {
        "index": word_to_chunks,
        "doc_freq": doc_freq,
        "num_chunks": len(chunks),
        "avg_chunk_len": sum(len(tokenize(c["text"])) for c in chunks) / max(len(chunks), 1),
    }


def search_index(query: str, index_data: dict, chunks: list[dict], top_k: int = 5) -> list[dict]:
    """
    BM25-style search.
    Returns top_k chunks sorted by relevance score.
    """
    query_tokens = tokenize(query)
    if not query_tokens:
        return []

    word_to_chunks = index_data["index"]
    doc_freq = index_data["doc_freq"]
    num_chunks = index_data["num_chunks"]
    avg_chunk_len = index_data["avg_chunk_len"]

    # BM25 parameters
    k1 = 1.5
    b = 0.75

    # Score each chunk
    scores = {}

    for word in query_tokens:
        if word not in word_to_chunks:
            continue

        idf = math.log((num_chunks - doc_freq[word] + 0.5) / (doc_freq[word] + 0.5) + 1.0)

        for chunk_idx, tf in word_to_chunks[word].items():
            chunk_len = len(tokenize(chunks[chunk_idx]["text"]))
            # BM25 score
            score = idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * chunk_len / avg_chunk_len))
            scores[chunk_idx] = scores.get(chunk_idx, 0.0) + score

    if not scores:
        return []

    # Sort by score descending
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    # Return top_k
    results = []
    for chunk_idx, score in ranked[:top_k]:
        chunk = chunks[chunk_idx]
        results.append({
            "url": chunk["url"],
            "title": chunk["title"],
            "text": chunk["text"],
            "score": round(score, 3),
        })

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Build keyword index from crawled pages")
    parser.add_argument(
        "--input",
        default=Path(__file__).parent / "data" / "pages_content.json",
        help="Crawled content JSON from crawl.py",
    )
    parser.add_argument(
        "--output",
        default=Path(__file__).parent / "data",
        help="Output directory for index files",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load crawled content
    print(f"Loading crawled content from {input_path}...", file=sys.stderr)
    with open(input_path) as f:
        data = json.load(f)

    print(f"Loaded {len(data['pages'])} pages", file=sys.stderr)

    # Chunk
    all_chunks = []
    for page in data["pages"]:
        chunks = chunk_text(page["text"], page["url"], page["title"])
        all_chunks.extend(chunks)

    print(f"Created {len(all_chunks)} chunks", file=sys.stderr)

    if not all_chunks:
        print("No chunks created — nothing to index!", file=sys.stderr)
        sys.exit(1)

    # Build index
    print("Building keyword search index (BM25)...", file=sys.stderr)
    index_data = build_chunk_index(all_chunks)
    print(f"  Vocabulary size: {len(index_data['index'])} words", file=sys.stderr)

    # Save
    index_path = output_dir / "index.pkl"
    with open(index_path, "wb") as f:
        pickle.dump({
            "index": index_data,
            "chunks": all_chunks,
        }, f)
    print(f"Saved index: {index_path} ({os.path.getsize(index_path)} bytes)", file=sys.stderr)

    meta = {
        "num_chunks": len(all_chunks),
        "num_pages": len(data["pages"]),
        "method": "bm25_keyword",
        "vocabulary_size": len(index_data["index"]),
        "chunk_size": CHUNK_SIZE,
        "chunk_overlap": CHUNK_OVERLAP,
        "crawled_at": data.get("crawled_at", "unknown"),
        "indexed_at": __import__("datetime").datetime.now().isoformat(),
    }
    meta_path = output_dir / "index_meta.json"
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"Saved metadata: {meta_path}", file=sys.stderr)

    # Quick test
    print("\n--- Quick test ---", file=sys.stderr)
    test_queries = [
        "How do I apply for a grant?",
        "What documents do I need?",
        "Eligibility for charities",
    ]
    for q in test_queries:
        results = search_index(q, index_data, all_chunks, top_k=2)
        print(f"  Query: {q}", file=sys.stderr)
        for r in results:
            print(f"    [{r['score']}] {r['title']} — {r['url']}", file=sys.stderr)

    print("\nDone! Index ready.", file=sys.stderr)


if __name__ == "__main__":
    main()