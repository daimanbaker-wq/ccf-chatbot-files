#!/usr/bin/env python3
"""
crawl.py — Crawl CCF website pages and extract clean text content.

Usage:
    python crawl.py [--pages data/pages.txt] [--output data/pages_content.json]

Output: JSON file with one entry per page: {url, title, text, fetched_at}
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup
import fitz  # PyMuPDF for PDF text extraction

USER_AGENT = (
    "Mozilla/5.0 (compatible; CCF-Chatbot-Crawler/1.0; "
    "+https://cornwallcommunityfoundation.com)"
)
REQUEST_TIMEOUT = 30  # seconds
DELAY_BETWEEN_REQUESTS = 1.0  # polite crawl


def load_pages(path: str) -> list[str]:
    """Load page URLs from a file (one per line, # comments ignored)."""
    pages = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                pages.append(line)
    return pages


def extract_text(html: str, url: str) -> str:
    """Extract clean text from HTML, removing nav, footer, scripts, etc."""
    soup = BeautifulSoup(html, "lxml")

    # Remove non-content elements
    for tag in soup.select(
        "script, style, nav, footer, header, iframe, noscript, "
        ".site-header, .site-footer, .nav-menu, .menu, "
        "[role=navigation], [role=search], .search-form, "
        ".social-links, .share-buttons, .newsletter-form, "
        "aside, .sidebar, .widget-area"
    ):
        tag.decompose()

    # Remove images and their links
    for img in soup.find_all("img"):
        img.decompose()

    # Remove links that are just icons or have no text
    for a in soup.find_all("a"):
        if not a.get_text(strip=True):
            a.decompose()

    # Get main content
    main = (
        soup.find("main")
        or soup.find("article")
        or soup.find('[role="main"]')
        or soup.find("body")
        or soup
    )

    text = main.get_text(separator="\n", strip=True)

    # Clean up whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = text.strip()

    return text


def extract_pdf(content: bytes, url: str) -> Optional[dict]:
    """Extract text from a PDF using PyMuPDF."""
    try:
        doc = fitz.open(stream=content, filetype="pdf")
        pages_text = []
        for page in doc:
            text = page.get_text().strip()
            if text:
                pages_text.append(text)
        doc.close()

        full_text = "\n\n".join(pages_text).strip()
        title = doc.metadata.get("title", url.split("/")[-1])

        if not full_text:
            print(f"  ⚠  No text extracted from PDF: {url}", file=sys.stderr)
            full_text = "[PDF document — no extractable text content]"

        print(f"  ✓  PDF: {len(pages_text)} pages, {len(full_text)} chars", file=sys.stderr)
        return {
            "url": url,
            "title": title,
            "text": full_text,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        print(f"  ✗  PDF extraction failed: {url} — {e}", file=sys.stderr)
        return None


def fetch_page(url: str, session: requests.Session) -> Optional[dict]:
    """Fetch a single page and return extracted text, or None on failure."""
    print(f"  Fetching: {url}", file=sys.stderr)
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()

        # Detect PDF by URL extension or Content-Type header
        is_pdf = (
            url.lower().endswith(".pdf")
            or "application/pdf" in resp.headers.get("Content-Type", "")
        )

        if is_pdf:
            return extract_pdf(resp.content, url)

        # HTML page — detect encoding and extract text
        resp.encoding = resp.apparent_encoding or "utf-8"

        # Try to extract title
        soup = BeautifulSoup(resp.text, "lxml")
        title_tag = soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else url

        text = extract_text(resp.text, url)

        if len(text) < 50:
            print(f"  ⚠  Too little text ({len(text)} chars) from {url}", file=sys.stderr)

        return {
            "url": url,
            "title": title,
            "text": text,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
    except requests.exceptions.RequestException as e:
        print(f"  ✗  Failed: {url} — {e}", file=sys.stderr)
        return None


def main():
    parser = argparse.ArgumentParser(description="Crawl CCF website pages")
    parser.add_argument(
        "--pages",
        default=Path(__file__).parent / "data" / "pages.txt",
        help="Path to pages list file",
    )
    parser.add_argument(
        "--output",
        default=Path(__file__).parent / "data" / "pages_content.json",
        help="Output JSON file path",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max pages to crawl (0 = all)",
    )
    args = parser.parse_args()

    pages = load_pages(str(args.pages))
    if args.limit > 0:
        pages = pages[: args.limit]

    print(f"Crawling {len(pages)} pages...", file=sys.stderr)

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    results = []
    for i, url in enumerate(pages, 1):
        print(f"[{i}/{len(pages)}] ", end="", file=sys.stderr)
        result = fetch_page(url, session)
        if result:
            results.append(result)
        if i < len(pages):
            time.sleep(DELAY_BETWEEN_REQUESTS)

    # Save output
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(
            {
                "crawled_at": datetime.now(timezone.utc).isoformat(),
                "total_pages": len(results),
                "pages": results,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )

    print(f"\nDone. Saved {len(results)} pages to {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()