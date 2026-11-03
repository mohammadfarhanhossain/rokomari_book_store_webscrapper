#!/usr/bin/env python3
"""
Rokomari (rokomari) — Production Scraper, Relational Database & Integrity Pipeline.
Structured identically to Wafilife and Rokomari pipelines.
"""

import argparse
import os
import sys
import re
import json
import sqlite3
from pathlib import Path
from difflib import SequenceMatcher
from urllib.parse import quote, urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup

stdout_reconfigure = getattr(sys.stdout, "reconfigure", None)
if callable(stdout_reconfigure):
    stdout_reconfigure(encoding="utf-8")

PROJECT_DIR = Path(__file__).resolve().parent
RAW_DIR = PROJECT_DIR / "data" / "raw"
PROCESSED_DIR = PROJECT_DIR / "data" / "processed"
STATE_DIR = PROJECT_DIR / "data" / "state"
LOG_DIR = PROJECT_DIR / "data" / "logs"
DB_PATH = PROJECT_DIR / "database" / "rokomari_catalog.sqlite3"

for directory in [RAW_DIR, PROCESSED_DIR, STATE_DIR, LOG_DIR, DB_PATH.parent]:
    directory.mkdir(parents=True, exist_ok=True)

STORE_NAME = "Rokomari"
DOMAIN = "https://www.rokomari.com"
TIMEOUT = 9

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,bn;q=0.8",
}

BN_DIGITS = {chr(0x09E6 + i): str(i) for i in range(10)}

def to_en_digits(s):
    if not s:
        return ""
    return "".join(BN_DIGITS.get(c, c) for c in str(s))

def extract_prices(val):
    if not val:
        return []
    s = to_en_digits(val)
    s = re.sub(r'(?i)\b(tk|bdt)\.', ' ', s)
    s = re.sub(r'(?i)\b(tk|bdt)\b', ' ', s)
    s = s.replace('৳', ' ').replace('/-', ' ')
    matches = re.findall(r'(\d[\d,]*)(?:\.\d+)?', s)
    prices = []
    for m in matches:
        clean_num = m.replace(',', '')
        if clean_num:
            try:
                p = int(clean_num)
                if p > 0:
                    prices.append(p)
            except ValueError:
                pass
    return prices

def to_int_price(val):
    prices = extract_prices(val)
    return prices[-1] if prices else None

def normalize_bangla(val):
    if not val:
        return ""
    val = str(val).lower().strip()
    val = val.replace("ী", "ি").replace("ূ", "ু").replace("ণ", "ন").replace("শ", "স").replace("ষ", "স")
    val = re.sub(r"[^\w\s\u0980-\u09FF]", " ", val)
    return " ".join(val.split())

def title_similarity(query, title):
    nq = normalize_bangla(query)
    nt = normalize_bangla(title)
    if not nq or not nt:
        return 0.0
    if nq == nt:
        return 1.0
    q_words = set(nq.split())
    t_words = set(nt.split())
    if not q_words or not t_words:
        return 0.0
    overlap = len(q_words & t_words) / len(q_words)
    if len(q_words) >= 2 and overlap < 0.50:
        return 0.0
    if nq in nt:
        contain_ratio = len(nq) / len(nt)
        return max(0.88, contain_ratio)
    seq_ratio = SequenceMatcher(None, nq, nt).ratio()
    return (0.60 * overlap) + (0.40 * seq_ratio)

# --- SCRAPER IMPLEMENTATION ---
def search_rokomari(query):
    results = []
    try:
        url = f"https://www.rokomari.com/search?term={quote(query)}&search_type=ALL"
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, 'html.parser')
            cards = soup.find_all(lambda tag: tag.name == 'div' and any('productGridItem' in c for c in tag.get('class', [])))
            for card in cards:
                t_el = card.find('p', class_=lambda c: c and 'productTitle' in c)
                a_el = card.find('p', class_=lambda c: c and 'productAuthor' in c)
                p_el = card.find('p', class_=lambda c: c and 'productPrice' in c)
                l_el = card.find('a', href=lambda h: h and '/book/' in h)
                i_el = card.find('img')

                title = t_el.text.strip() if t_el else ""
                if not title or not l_el:
                    continue

                link = urljoin("https://www.rokomari.com", l_el['href'])
                price = to_int_price(p_el.text) if p_el else None
                author = a_el.text.strip() if a_el else ""
                img = i_el.get('data-src') or i_el.get('src') or "" if i_el else ""

                card_text = card.get_text()
                in_stock = 'Product in stock' in card_text or 'In stock' in card_text or 'স্টকে আছে' in card_text

                results.append({
                    'store': 'Rokomari',
                    'store_type': 'General',
                    'title': title,
                    'author': author,
                    'price': price,
                    'regular_price': price,
                    'in_stock': in_stock,
                    'stock_text': 'স্টকে আছে' if in_stock else 'স্টক নেই',
                    'url': link,
                    'image': img,
                })
    except Exception as exc:
        print(f"[Scraper] Rokomari error: {exc}")
    return results


# ==============================================================================


def search_local_db(query, limit=10):
    if not DB_PATH.exists():
        return []
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    norm_q = "%" + query.strip() + "%"
    try:
        cur.execute("""
            SELECT book_id, book_name, author_name, publisher_name, subject_name, main_price, store_price, book_url, image_url, in_stock
            FROM master
            WHERE book_name LIKE ? OR author_name LIKE ?
            LIMIT ?
        """, (norm_q, norm_q, limit))
        rows = cur.fetchall()
        results = []
        for r in rows:
            results.append({
                "book_id": r[0],
                "book_name": r[1],
                "author_name": r[2],
                "publisher_name": r[3],
                "subject_name": r[4],
                "main_price": r[5],
                "price": r[6],
                "url": r[7],
                "image": r[8],
                "in_stock": bool(r[9])
            })
        conn.close()
        return results
    except Exception as e:
        conn.close()
        return []

def verify_data():
    print("=" * 60)
    print("ROKOMARI DATA INTEGRITY REPORT")
    print("=" * 60)
    
    files = ["clean_authors.csv", "clean_publishers.csv", "clean_subjects.csv", "clean_books.csv", "master.csv"]
    for f in files:
        p = PROJECT_DIR / f
        if p.exists():
            df = pd.read_csv(p)
            print(f"[{f:20}] Rows: {len(df):,}")
        else:
            print(f"[{f:20}] MISSING")

    if DB_PATH.exists():
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        print("\n--- SQLite Database Metrics ---")
        for tbl in ["authors", "publishers", "subjects", "books", "master", "books_fts"]:
            try:
                cur.execute(f"SELECT COUNT(*) FROM {tbl}")
                cnt = cur.fetchone()[0]
                print(f"Table [{tbl:12}]: {cnt:,} records")
            except Exception as e:
                print(f"Table [{tbl:12}]: Error ({e})")
        
        # Foreign key checks
        try:
            cur.execute("SELECT COUNT(*) FROM books b LEFT JOIN authors a ON b.author_id=a.author_id WHERE a.author_id IS NULL AND b.author_id IS NOT NULL")
            orphan_auth = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM books b LEFT JOIN publishers p ON b.publisher_id=p.publisher_id WHERE p.publisher_id IS NULL AND b.publisher_id IS NOT NULL")
            orphan_pub = cur.fetchone()[0]
            print(f"Orphan Author FKs   : {orphan_auth}")
            print(f"Orphan Publisher FKs: {orphan_pub}")
        except Exception:
            pass
        conn.close()
    else:
        print(f"\nSQLite database not found at {DB_PATH}")
    print("=" * 60)

def main():
    parser = argparse.ArgumentParser(description="Rokomari Scraper and Database Pipeline")
    parser.add_argument("--search", type=str, help="Search book online and in local database")
    parser.add_argument("--verify", action="store_true", help="Verify data integrity across CSVs and SQLite")
    parser.add_argument("--db", action="store_true", help="Rebuild SQLite database from clean CSVs")
    args = parser.parse_args()

    if args.verify:
        verify_data()
        return

    if args.search:
        q = args.search.strip()
        print(f"Searching for '{q}' on Rokomari live website...")
        live_res = search_rokomari(q)
        print(f"Live website returned {len(live_res)} results:")
        for it in live_res[:5]:
            print(f"  - {it.get('title')} | ৳{it.get('price')} | {it.get('url')}")

        print(f"\nSearching for '{q}' in local SQLite database...")
        db_res = search_local_db(q)
        print(f"Local database returned {len(db_res)} results:")
        for it in db_res[:5]:
            print(f"  - {it.get('book_name')} | ৳{it.get('price')} | {it.get('url')}")
        return

    verify_data()

if __name__ == "__main__":
    main()
