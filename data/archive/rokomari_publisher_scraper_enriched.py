import csv
import os
import sys
import time
import random
import re
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright
from playwright_stealth.stealth import Stealth

# ইনপুট এবং আউটপুট ফাইল পাথ পরিবর্তন
INPUT_PUBLISHERS_CSV = "rokomari_publishers_playwright.csv"
OUTPUT_CSV = "rokomari_publisher_books_verified.csv"
QUALITY_REPORT = "rokomari_publisher_books_verified_quality.txt"


def load_publishers(limit=None):
    publishers = []
    seen_publisher_keys = set()
    if not os.path.exists(INPUT_PUBLISHERS_CSV):
        raise FileNotFoundError(f"{INPUT_PUBLISHERS_CSV} not found")

    with open(INPUT_PUBLISHERS_CSV, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            if limit and i >= limit:
                break
            
            link = row.get("link") or row.get("url")
            name = row.get("name") or row.get("publisher") or ""
            if not link:
                continue

            # রকমারির প্রকাশনী ইউআরএল প্যাটার্ন এক্সট্রাক্ট করা (যেমন: /publisher/5/anannya)
            match = re.search(r"/publisher/(\d+)", link)
            if match:
                publisher_key = match.group(1)
                canonical_link = f"https://www.rokomari.com/book/publisher/{publisher_key}"
            else:
                canonical_link = link.split("?")[0].rstrip("/")
                publisher_key = canonical_link

            if publisher_key in seen_publisher_keys:
                continue

            seen_publisher_keys.add(publisher_key)
            publishers.append({"id": str(len(publishers) + 1), "name": name, "link": canonical_link})
    return publishers


def parse_book_link(link):
    match = re.search(r"/book/(\d+)(?:/([^/?#]+))?", link)
    if match:
        return match.group(1), match.group(2) or ""
    return "", ""


def read_existing_progress():
    """আগের কাজের প্রগ্রেস ট্র্যাক রিড করা (Resume Functionality)"""
    processed = set()
    max_id = 0
    if not os.path.exists(OUTPUT_CSV):
        return processed, max_id

    try:
        with open(OUTPUT_CSV, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                pid = row.get("publisher_id")
                if pid:
                    processed.add(str(pid))
                rid = row.get("id")
                if rid:
                    try:
                        max_id = max(max_id, int(rid))
                    except Exception:
                        pass
    except Exception:
        return set(), 0

    return processed, max_id


def ensure_output_header():
    with open(OUTPUT_CSV, mode="w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "id",
                "publisher_id",
                "publisher_name",
                "publisher_link",
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
                "publisher_id",
                "publisher_name",
                "publisher_link",
                "book_numeric_id",
                "book_slug",
                "book_title",
                "book_link",
            ],
        )
        for r in rows:
            writer.writerow(r)


def write_quality_report(publishers, output_path=OUTPUT_CSV):
    with open(output_path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    owner_ids = {row["publisher_id"] for row in rows if row.get("publisher_id")}
    links = [row.get("book_link", "") for row in rows]
    pair_keys = [(row.get("publisher_id", ""), row.get("book_link", "")) for row in rows]
    missing_ids = [publisher["id"] for publisher in publishers if publisher["id"] not in owner_ids]
    invalid_ids = sum(not row.get("book_numeric_id") for row in rows)
    duplicate_links = len(links) - len(set(links))
    duplicate_owner_links = len(pair_keys) - len(set(pair_keys))
    with open(QUALITY_REPORT, "w", encoding="utf-8") as report:
        report.write("ROKOMARI PUBLISHER SCRAPE QUALITY REPORT\n")
        report.write("=======================================\n\n")
        report.write(f"Input publishers: {len(publishers)}\n")
        report.write(f"Valid book rows: {len(rows)}\n")
        report.write(f"Publishers with at least one book: {len(owner_ids)}\n")
        report.write(f"Publishers with no book row: {len(missing_ids)}\n")
        report.write(f"Rows with invalid book ID: {invalid_ids}\n")
        report.write(f"Repeated book links across different publishers: {duplicate_links}\n")
        report.write(f"Repeated book links for the same publisher: {duplicate_owner_links}\n\n")
        report.write("INTERPRETATION\n")
        report.write("- Invalid book ID should be 0; otherwise the extraction rule needs review.\n")
        report.write("- Repeated links across publishers are usually valid because a book may have multiple publishers.\n")
        report.write("- Publishers with no book row may have no books, a blocked page, or a page-structure change.\n")
        if missing_ids:
            report.write("\nPublisher IDs with no saved books: " + ", ".join(missing_ids) + "\n")


def scrape_books_for_publisher(page, publisher):
    url = publisher["link"]
    last_error = None
    for attempt in range(1, 4):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            time.sleep(random.uniform(0.05, 0.2))
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
            
            # বইয়ের লিংক ফিল্টারিং লজিক (পাবলিশার বা অথর পেজ বাদ দিয়ে শুধু পিউর বুক লিংক নেওয়া)
            if "/book/" in href and "/publisher/" not in href and "/author/" not in href:
                clean = href.split("?")[0]
                link = clean if clean.startswith("http") else urljoin("https://www.rokomari.com", clean)
                if link in seen:
                    continue
                title = a.inner_text().strip()
                if not title:
                    title = (a.get_attribute("title") or "").strip()
                if not title:
                    continue
                
                book_numeric_id, book_slug = parse_book_link(link)
                if not book_numeric_id:
                    continue
                books.append({
                    "publisher_id": publisher["id"],
                    "publisher_name": publisher.get("name", ""),
                    "publisher_link": publisher.get("link", ""),
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
    publishers = load_publishers(limit)
    if not publishers:
        print("No publishers to process")
        return

    if not os.path.exists(OUTPUT_CSV) or os.path.getsize(OUTPUT_CSV) == 0:
        ensure_output_header()

    processed_publisher_ids, max_assigned_id = read_existing_progress()
    if processed_publisher_ids:
        print(f"Resuming: found {len(processed_publisher_ids)} processed publishers; next book id will start at {max_assigned_id + 1}", flush=True)
        next_book_id = max_assigned_id + 1
    else:
        next_book_id = 1

    id_to_pos = {p["id"]: i + 1 for i, p in enumerate(publishers)}
    publishers_to_process = [p for p in publishers if p["id"] not in processed_publisher_ids]
    if not publishers_to_process:
        print("All publishers already processed — nothing to do.", flush=True)
        return

    chrome_executable = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    with sync_playwright() as p:
        launch_kwargs = {"headless": True}  # তুমি চাইলে এটি False করে লাইভ ব্রাউজার দেখতে পারো
        if os.path.exists(chrome_executable):
            launch_kwargs["executable_path"] = chrome_executable
        browser = p.chromium.launch(**launch_kwargs)
        context = browser.new_context(viewport={"width": 1280, "height": 720})
        page = context.new_page()
        Stealth().apply_stealth_sync(page)

        for publisher in publishers_to_process:
            pos = id_to_pos.get(publisher["id"], "?")
            print(f"[{pos}/{len(publishers)}] Scraping books for publisher: {publisher.get('name')} -> {publisher.get('link')}", flush=True)
            books = scrape_books_for_publisher(page, publisher)
            if books:
                for book in books:
                    book["id"] = str(next_book_id)
                    next_book_id += 1
                append_books(books)
                print(f"    saved {len(books)} books", flush=True)
            else:
                print("    no books found or error", flush=True)
            
            # ক্লাউডফ্লেয়ার ব্লকিং এড়ানোর জন্য পলাইট ডিলে
            time.sleep(random.uniform(0.2, 0.6))

        browser.close()
    write_quality_report(publishers)
    print(f"Quality report written to {QUALITY_REPORT}", flush=True)


if __name__ == "__main__":
    arg_limit = None
    if len(sys.argv) > 1:
        try:
            arg_limit = int(sys.argv[1])
        except Exception:
            pass
    main(limit=arg_limit)
