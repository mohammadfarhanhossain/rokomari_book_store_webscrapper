import csv
import os
import sys
import time
import random
import re
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright
from playwright_stealth.stealth import Stealth

INPUT_AUTHORS_CSV = "rokomari_authors_playwright.csv"
OUTPUT_CSV = "rokomari_author_books_verified.csv"
QUALITY_REPORT = "rokomari_author_books_verified_quality.txt"


def load_authors(limit=None):
    authors = []
    seen_author_keys = set()
    if not os.path.exists(INPUT_AUTHORS_CSV):
        raise FileNotFoundError(f"{INPUT_AUTHORS_CSV} not found")

    with open(INPUT_AUTHORS_CSV, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            if limit and i >= limit:
                break
            # support files with or without an `id` column
            link = row.get("link") or row.get("url")
            name = row.get("name") or row.get("author") or ""
            if not link:
                continue

            match = re.search(r"/author/(\d+)", link)
            if match:
                author_key = match.group(1)
                canonical_link = f"https://www.rokomari.com/book/author/{author_key}"
            else:
                canonical_link = link.split("?")[0].rstrip("/")
                author_key = canonical_link

            if author_key in seen_author_keys:
                continue

            seen_author_keys.add(author_key)
            authors.append({"id": str(len(authors) + 1), "name": name, "link": canonical_link})
    return authors


def parse_book_link(link):
    match = re.search(r"/book/(\d+)(?:/([^/?#]+))?", link)
    if match:
        return match.group(1), match.group(2) or ""
    return "", ""


def read_existing_progress():
    """Return (processed_author_ids_set, max_assigned_id).

    - processed_author_ids_set: set of author_id strings already present in OUTPUT_CSV
    - max_assigned_id: maximum integer value of our assigned sequential `id` column
    """
    processed = set()
    max_id = 0
    if not os.path.exists(OUTPUT_CSV):
        return processed, max_id

    try:
        with open(OUTPUT_CSV, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                aid = row.get("author_id")
                if aid:
                    processed.add(str(aid))
                rid = row.get("id")
                if rid:
                    try:
                        max_id = max(max_id, int(rid))
                    except Exception:
                        pass
    except Exception:
        # If file is malformed or unreadable, treat as no progress
        return set(), 0

    return processed, max_id


def ensure_output_header():
    with open(OUTPUT_CSV, mode="w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "id",
                "author_id",
                "author_name",
                "author_link",
                "book_numeric_id",
                "book_slug",
                "book_title",
                "book_link",
            ],
        )
        writer.writeheader()


def append_books(rows):
    with open(OUTPUT_CSV, mode="a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "id",
                "author_id",
                "author_name",
                "author_link",
                "book_numeric_id",
                "book_slug",
                "book_title",
                "book_link",
            ],
        )
        for r in rows:
            writer.writerow(r)


def write_quality_report(authors, output_path=OUTPUT_CSV):
    with open(output_path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    owner_ids = {row["author_id"] for row in rows if row.get("author_id")}
    links = [row.get("book_link", "") for row in rows]
    pair_keys = [(row.get("author_id", ""), row.get("book_link", "")) for row in rows]
    missing_ids = [author["id"] for author in authors if author["id"] not in owner_ids]
    invalid_ids = sum(not row.get("book_numeric_id") for row in rows)
    duplicate_links = len(links) - len(set(links))
    duplicate_owner_links = len(pair_keys) - len(set(pair_keys))
    with open(QUALITY_REPORT, "w", encoding="utf-8") as report:
        report.write("ROKOMARI AUTHOR SCRAPE QUALITY REPORT\n")
        report.write("===================================\n\n")
        report.write(f"Input authors: {len(authors)}\n")
        report.write(f"Valid book rows: {len(rows)}\n")
        report.write(f"Authors with at least one book: {len(owner_ids)}\n")
        report.write(f"Authors with no book row: {len(missing_ids)}\n")
        report.write(f"Rows with invalid book ID: {invalid_ids}\n")
        report.write(f"Repeated book links across different authors: {duplicate_links}\n")
        report.write(f"Repeated book links for the same author: {duplicate_owner_links}\n\n")
        report.write("INTERPRETATION\n")
        report.write("- Invalid book ID should be 0; otherwise the extraction rule needs review.\n")
        report.write("- Repeated links across authors are usually valid because one book can have multiple authors.\n")
        report.write("- Authors with no book row may have no books, a blocked page, or a page-structure change.\n")
        if missing_ids:
            report.write("\nAuthor IDs with no saved books: " + ", ".join(missing_ids) + "\n")


def scrape_books_for_author(page, author):
    url = author["link"]
    last_error = None
    for attempt in range(1, 4):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            time.sleep(random.uniform(0.1, 0.3))
            break
        except Exception as e:
            last_error = e
            print(f"    [WARN] visit attempt {attempt}/3 failed: {e}", flush=True)
            time.sleep(2 * attempt)
    else:
        print(f"    [ERROR] visiting {url}: {last_error}", flush=True)
        return []

    anchors = page.query_selector_all("a")
    books = []
    seen = set()
    for a in anchors:
        try:
            href = a.get_attribute("href")
            if not href:
                continue
            # book links contain '/book/' but exclude author links
            if "/book/" in href and "/author/" not in href:
                clean = href.split("?")[0]
                link = clean if clean.startswith("http") else urljoin("https://www.rokomari.com", clean)
                if link in seen:
                    continue
                title = a.inner_text().strip()
                if not title:
                    # try title attribute
                    title = (a.get_attribute("title") or "").strip()
                if not title:
                    continue
                book_numeric_id, book_slug = parse_book_link(link)
                if not book_numeric_id:
                    continue
                books.append({
                    "author_id": author["id"],
                    "author_name": author.get("name", ""),
                    "author_link": author.get("link", ""),
                    "book_numeric_id": book_numeric_id,
                    "book_slug": book_slug,
                    "book_title": title,
                    "book_link": link,
                })
                seen.add(link)
        except Exception:
            continue
    return books


def main(limit=None):
    authors = load_authors(limit)
    if not authors:
        print("No authors to process")
        return

    if not os.path.exists(OUTPUT_CSV) or os.path.getsize(OUTPUT_CSV) == 0:
        ensure_output_header()

    # Detect existing progress and decide whether to resume or create a fresh output
    processed_author_ids, max_assigned_id = read_existing_progress()
    if processed_author_ids:
        print(f"Resuming: found {len(processed_author_ids)} processed authors; next book id will start at {max_assigned_id + 1}", flush=True)
        next_book_id = max_assigned_id + 1
    else:
        # create output file with header if it doesn't exist
        next_book_id = 1

    # build a quick map of author id -> original position so progress printing remains meaningful
    id_to_pos = {a["id"]: i + 1 for i, a in enumerate(authors)}

    # filter authors to only those not yet processed
    authors_to_process = [a for a in authors if a["id"] not in processed_author_ids]
    if not authors_to_process:
        print("All authors already processed — nothing to do.", flush=True)
        return

    chrome_executable = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    with sync_playwright() as p:
        launch_kwargs = {"headless": True}
        if os.path.exists(chrome_executable):
            launch_kwargs["executable_path"] = chrome_executable
        browser = p.chromium.launch(**launch_kwargs)
        context = browser.new_context(viewport={"width": 1280, "height": 720})
        page = context.new_page()
        Stealth().apply_stealth_sync(page)

        for author in authors_to_process:
            pos = id_to_pos.get(author["id"], "?")
            print(f"[{pos}/{len(authors)}] Scraping books for: {author.get('name')} -> {author.get('link')}", flush=True)
            books = scrape_books_for_author(page, author)
            if books:
                for book in books:
                    book["id"] = str(next_book_id)
                    next_book_id += 1
                append_books(books)
                print(f"    saved {len(books)} books", flush=True)
            else:
                print("    no books found or error", flush=True)
            # polite delay between authors
            time.sleep(random.uniform(0.2, 0.6))

        browser.close()
    write_quality_report(authors)
    print(f"Quality report written to {QUALITY_REPORT}", flush=True)


if __name__ == "__main__":
    arg_limit = None
    if len(sys.argv) > 1:
        try:
            arg_limit = int(sys.argv[1])
        except Exception:
            pass
    main(limit=arg_limit)
