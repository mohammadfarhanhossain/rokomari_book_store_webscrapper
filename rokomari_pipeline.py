import argparse
import json
import os
import random
import re
import shutil
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from bs4 import BeautifulSoup
from requests.exceptions import RequestException
from sqlalchemy import create_engine, text

stdout_reconfigure = getattr(sys.stdout, "reconfigure", None)
if callable(stdout_reconfigure):
    stdout_reconfigure(encoding="utf-8")

PROJECT_DIR = Path(__file__).resolve().parent
RAW_DIR = PROJECT_DIR / "data" / "raw"
PROCESSED_DIR = PROJECT_DIR / "data" / "processed"
STATE_DIR = PROJECT_DIR / "data" / "state"
LOG_DIR = PROJECT_DIR / "data" / "logs"
ARCHIVE_DIR = PROJECT_DIR / "data" / "archive"

for directory in [RAW_DIR, PROCESSED_DIR, STATE_DIR, LOG_DIR, ARCHIVE_DIR]:
    directory.mkdir(parents=True, exist_ok=True)

DB_USER = os.getenv("ROKOMARI_DB_USER", "root")
DB_PASS = os.getenv("ROKOMARI_DB_PASS", "farhan")
DB_HOST = os.getenv("ROKOMARI_DB_HOST", "localhost")
DB_PORT = os.getenv("ROKOMARI_DB_PORT", "3306")
DB_NAME = os.getenv("ROKOMARI_DB_NAME", "rokomari_db")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "bn-BD,bn;q=0.9,en-US;q=0.8,en;q=0.7",
}
DOMAIN = "https://www.rokomari.com"
BN_DIGITS = {chr(0x09E6 + i): str(i) for i in range(10)}
INVALID_TEXTS = {"", "nan", "none", "not listed", "not listed on grid"}
BLOCK_INDICATORS = [
    "captcha",
    "are you human",
    "access denied",
    "too many requests",
    "please enable javascript",
    "unusual traffic",
    "verify you are human",
    "challenge-running",
    "cf-browser-verification",
]

ENTITY_CONFIGS = {
    "author": {
        "raw_file": RAW_DIR / "Rokomari_All_Authors.csv",
        "raw_name_col": "Author_Name",
        "clean_file": PROCESSED_DIR / "clean_authors.csv",
        "id_col": "author_id",
        "name_col": "author_name",
        "default_name": "Unknown Author",
        "list_url": "https://www.rokomari.com/book/authors",
        "href_part": "/book/author/",
        "max_pages": 400,
        "processed_file": PROCESSED_DIR / "Rokomari_Authors_Data.csv",
        "progress_file": STATE_DIR / "scraping_progress_authors.txt",
    },
    "publisher": {
        "raw_file": RAW_DIR / "Rokomari_All_Publishers.csv",
        "raw_name_col": "Publisher_Name",
        "clean_file": PROCESSED_DIR / "clean_publishers.csv",
        "id_col": "publisher_id",
        "name_col": "publisher_name",
        "default_name": "Unknown Publisher",
        "list_url": "https://www.rokomari.com/book/publishers",
        "href_part": "/book/publisher/",
        "max_pages": 200,
        "processed_file": PROCESSED_DIR / "Rokomari_Publishers_Data.csv",
        "progress_file": STATE_DIR / "scraping_progress_publishers.txt",
    },
}

ENTITY_TYPES = ["author", "publisher"]
TEXT_COLUMNS = ["book_name", "author_name", "publisher_name"]
BOOK_COLUMNS = TEXT_COLUMNS + ["main_price", "rokomari_price", "book_url", "book_numeric_id"]
BOOK_URL_PATTERN = re.compile(r"^https?://(?:www\.)?rokomari\.com/book/(\d+)(?:/([^/?#]+))?")


def is_blocked_page(text: str) -> bool:
    if not text:
        return False
    lower = text.lower()
    for phrase in BLOCK_INDICATORS:
        if phrase in lower:
            return True
    return False


def normalize_text(value):
    if pd.isna(value):
        return np.nan

    text_value = str(value)
    text_value = text_value.replace('"', "").replace("'", "")
    text_value = text_value.replace("“", "").replace("”", "")
    text_value = re.sub(r"\s+", " ", text_value).strip()

    if text_value.lower() in INVALID_TEXTS:
        return np.nan
    return text_value


def clean_price(value):
    if pd.isna(value):
        return 0

    digits_only = "".join(re.findall(r"[\u09E6-\u09EF0-9]", str(value)))
    if not digits_only:
        return 0

    english_digits = "".join(BN_DIGITS.get(char, char) for char in digits_only)
    try:
        return int(english_digits)
    except ValueError:
        return 0


def atomic_replace(src_path, dest_path, retries=3, delay=0.2):
    src = Path(str(src_path))
    dest = Path(str(dest_path))
    last_exc = None
    for _ in range(retries):
        try:
            os.replace(str(src), str(dest))
            return
        except PermissionError as exc:
            last_exc = exc
            try:
                if dest.exists():
                    os.remove(str(dest))
            except Exception:
                time.sleep(delay)
                continue
            try:
                os.replace(str(src), str(dest))
                return
            except Exception as exc2:
                last_exc = exc2
                time.sleep(delay)
                continue
        except Exception as exc:
            last_exc = exc
            time.sleep(delay)
            continue
    if last_exc:
        raise last_exc


def read_progress(path):
    if not path.exists():
        return None
    try:
        text_content = path.read_text(encoding="utf-8").strip()
        if not text_content:
            return None
        return json.loads(text_content)
    except Exception:
        text_content = path.read_text(encoding="utf-8").strip()
        if not text_content:
            return None
        return {"entity": text_content, "next_page": None}


def write_progress(path, value):
    tmp = path.with_suffix(path.suffix + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(value, fh, ensure_ascii=False)
    atomic_replace(tmp, path)


def load_existing_processed(path):
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False)


def fetch_page(session, url, max_retries=3, timeout=15):
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            response = session.get(url, headers=HEADERS, timeout=timeout)
            if response.status_code == 200:
                return response
            last_error = f"status {response.status_code}"
        except RequestException as exc:
            last_error = str(exc)

        print(f"Request failed for {url} ({attempt}/{max_retries}): {last_error}")
        if attempt < max_retries:
            time.sleep(random.uniform(1.0, 2.5))

    print(f"Skipping {url} after retries: {last_error}")
    return None


def extract_entity_name(a_tag):
    for selector in ["h3", "h2", "span", "p"]:
        tag = a_tag.find(selector)
        if tag and tag.get_text(strip=True):
            return tag.get_text(strip=True)
    return a_tag.get_text(strip=True)


def normalize_entity_list(entity_type, df, persist=False):
    config = ENTITY_CONFIGS[entity_type]
    id_col = config["id_col"]
    name_col = config["raw_name_col"]
    output_file = config["raw_file"]

    for col in [name_col, "Profile_Link"]:
        if col not in df.columns:
            df[col] = np.nan
        df[col] = df[col].map(normalize_text)

    df.dropna(subset=[name_col], inplace=True)
    dedupe_cols = ["Profile_Link"] if df["Profile_Link"].notna().any() else [name_col]
    df.drop_duplicates(subset=dedupe_cols, keep="first", inplace=True)
    df.reset_index(drop=True, inplace=True)

    if id_col in df.columns:
        df.drop(columns=[id_col], inplace=True)
    df.insert(0, id_col, df.index + 2)
    df = df[[id_col, name_col, "Profile_Link"]]

    if persist:
        tmp_out = output_file.with_suffix(output_file.suffix + ".tmp")
        df.to_csv(tmp_out, index=False, encoding="utf-8-sig")
        atomic_replace(tmp_out, output_file)
    return df


def scrape_entity_list(entity_type, force=False):
    config = ENTITY_CONFIGS[entity_type]
    output_file = config["raw_file"]

    if output_file.exists() and not force:
        print(f"[SKIP] {output_file.name} already exists. Use --force-list to refresh.")
        return normalize_entity_list(entity_type, pd.read_csv(output_file, low_memory=False), persist=True)

    session = requests.Session()
    rows = []
    domain = DOMAIN

    for page in range(1, config["max_pages"] + 1):
        current_url = f"{config['list_url']}?page={page}"
        print(f"[LIST] {entity_type} page {page}: {current_url}")
        response = fetch_page(session, current_url)
        if response is None:
            break

        soup = BeautifulSoup(response.text, "html.parser")
        found = 0
        for a_tag in soup.find_all("a", href=True):
            href = str(a_tag["href"])
            if config["href_part"] not in href or "?page=" in href:
                continue
            if href.rstrip("/") == config["list_url"].rstrip("/"):
                continue

            profile_link = f"{domain}{href}" if not href.startswith("http") else href
            name = extract_entity_name(a_tag)
            if name and not any(k in name.lower() for k in ["see all", "view all", "category"]):
                rows.append({config["raw_name_col"]: name, "Profile_Link": profile_link})
                found += 1

        print(f" -> found {found}")
        if found == 0:
            break
        time.sleep(random.uniform(0.5, 1.5))

    df = normalize_entity_list(entity_type, pd.DataFrame(rows))
    tmp_out = output_file.with_suffix(output_file.suffix + ".tmp")
    df.to_csv(tmp_out, index=False, encoding="utf-8-sig")
    atomic_replace(tmp_out, output_file)
    print(f"[OK] Saved {len(df)} {entity_type} rows to {output_file}")
    return df


def book_page_url(entity_type, base_url, page):
    clean_base = base_url.split("?")[0].rstrip("/")
    if page == 1:
        return clean_base
    return f"{clean_base}?page={page}"


def extract_book_card(article, domain=DOMAIN):
    # Find canonical book link
    book_link_tag = article.find("a", href=lambda h: h and "/book/" in h and "/author/" not in h and "/publisher/" not in h)
    if not book_link_tag:
        return None

    raw_href = book_link_tag["href"].split("?")[0].rstrip("/")
    book_url = f"{domain}{raw_href}" if not raw_href.startswith("http") else raw_href

    match = BOOK_URL_PATTERN.match(book_url)
    if not match:
        return None
    book_numeric_id = match.group(1)

    # Extract Title cleanly
    title = None
    title_el = article.find(class_=lambda c: c and "productTitle" in c)
    if title_el:
        title = title_el.get_text(strip=True)
    if not title:
        for selector in ["h4", "h3", "h2", "p"]:
            heading = article.find(selector)
            if heading and heading.get_text(strip=True):
                title = heading.get_text(strip=True)
                break
    if not title:
        title = (book_link_tag.get("title") or "").strip()
    if not title:
        # Fallback to text parsing
        lines = [line.strip() for line in book_link_tag.get_text().split("\n") if line.strip()]
        if lines:
            title = lines[1] if re.match(r"^\d{1,3}%?$", lines[0]) and len(lines) > 1 else lines[0]

    # Extract Author cleanly
    card_author = None
    author_el = article.find(class_=lambda c: c and "productAuthor" in c)
    if author_el:
        card_author = author_el.get_text(strip=True)

    # Extract Prices cleanly
    main_price = 0
    rokomari_price = 0

    del_tag = article.find("del")
    price_p = article.find(class_=lambda c: c and "productPrice" in c)

    if del_tag:
        main_price = clean_price(del_tag.get_text(strip=True))
    if price_p:
        rokomari_price = clean_price(price_p.get_text(strip=True))

    if rokomari_price == 0 and main_price > 0:
        rokomari_price = main_price
    elif main_price == 0 and rokomari_price > 0:
        main_price = rokomari_price

    if rokomari_price > main_price and main_price > 0:
        main_price, rokomari_price = rokomari_price, main_price

    return {
        "Title": title,
        "Author": card_author or "Not Listed",
        "Main_Price": main_price,
        "Rokomari_Price": rokomari_price,
        "book_url": book_url,
        "book_numeric_id": book_numeric_id,
    }


def scrape_entity_books(entity_type):
    config = ENTITY_CONFIGS[entity_type]
    raw_file = config["raw_file"]
    if not raw_file.exists():
        raise FileNotFoundError(f"Missing {raw_file}; run list scraping first.")

    entity_df = normalize_entity_list(entity_type, pd.read_csv(raw_file, low_memory=False), persist=True)
    existing_df = load_existing_processed(config["processed_file"])
    all_rows = existing_df.to_dict("records") if not existing_df.empty else []
    progress = read_progress(config["progress_file"])

    resume_index = None
    resume_page = None
    if progress:
        if isinstance(progress, dict):
            prog_entity = progress.get("entity")
            prog_next = progress.get("next_page")
        else:
            prog_entity = progress
            prog_next = None

        if prog_entity:
            matches = entity_df.index[entity_df[config["raw_name_col"]] == prog_entity].tolist()
            if matches:
                idx = matches[0]
                if prog_next:
                    resume_index = idx
                    resume_page = int(prog_next)
                else:
                    resume_index = idx + 1

    session = requests.Session()
    domain = DOMAIN

    for position, row in entity_df.iterrows():
        if resume_index is not None and position < resume_index:
            continue
        entity_name = row[config["raw_name_col"]]
        base_url = str(row["Profile_Link"]).rstrip("/")
        total_for_entity = 0

        if resume_index is not None and position == resume_index and resume_page:
            page = resume_page
            resume_page = None
        else:
            page = 1

        print(f"[BOOKS] {entity_type}: {entity_name} ({int(position) + 1}/{len(entity_df)})")
        while True:
            url = book_page_url(entity_type, base_url, page)
            response = fetch_page(session, url)
            if response is None:
                write_progress(config["progress_file"], {"entity": entity_name, "next_page": page})
                print(f"[BOOKS] fetch failed, saved progress for {entity_name} page {page}")
                return

            if is_blocked_page(response.text):
                write_progress(config["progress_file"], {"entity": entity_name, "next_page": page})
                print(f"[BOOKS] Block detected for {entity_name} at page {page}; stopping to preserve progress")
                return

            soup = BeautifulSoup(response.text, "html.parser")
            # Find product cards specifically scoped to grid items to prevent navbar/bestseller leakage
            items = soup.find_all(lambda tag: tag.name in ["div", "article"] and tag.get("class") and any("productgriditem" in c.lower() or "book-list-wrapper" in c.lower() for c in tag.get("class")))
            if not items:
                # Fallback to book containers
                items = soup.find_all("div", class_=lambda c: c and "productDetailsBody" in c)

            if not items:
                break

            found = 0
            for item in items:
                book_data = extract_book_card(item, domain=domain)
                if not book_data or not book_data["Title"]:
                    continue

                if entity_type == "author":
                    book_data["Author"] = entity_name
                    book_data["Publisher"] = "Not Listed"
                elif entity_type == "publisher":
                    book_data["Publisher"] = entity_name

                all_rows.append(book_data)
                found += 1
                total_for_entity += 1

            if found == 0:
                break

            write_progress(config["progress_file"], {"entity": entity_name, "next_page": page + 1})
            page += 1
            time.sleep(random.uniform(0.2, 0.6))

        processed_path = config["processed_file"]
        tmp_processed = processed_path.with_suffix(processed_path.suffix + ".tmp")
        pd.DataFrame(all_rows).to_csv(tmp_processed, index=False, encoding="utf-8-sig")
        atomic_replace(tmp_processed, processed_path)
        write_progress(config["progress_file"], {"entity": entity_name, "next_page": None})
        print(f" -> scraped {total_for_entity}; saved total {len(all_rows)}")


def first_valid(values, fallback):
    valid = values.dropna()
    return valid.iloc[0] if valid.size else fallback


def make_entity_table(entity_type, final_df):
    config = ENTITY_CONFIGS[entity_type]
    raw_df = normalize_entity_list(entity_type, pd.read_csv(config["raw_file"], low_memory=False), persist=True)
    seed_df = pd.DataFrame({
        config["name_col"]: raw_df[config["raw_name_col"]].map(normalize_text),
        "profile_link": raw_df["Profile_Link"].map(normalize_text),
    })
    seed_df.dropna(subset=[config["name_col"]], inplace=True)

    scraped_df = pd.DataFrame({
        config["name_col"]: final_df[config["name_col"]],
        "profile_link": np.nan,
    })

    entity_df = pd.concat([seed_df, scraped_df], ignore_index=True)
    entity_df.dropna(subset=[config["name_col"]], inplace=True)
    entity_df = entity_df[entity_df[config["name_col"]] != config["default_name"]]
    entity_df.drop_duplicates(subset=[config["name_col"]], keep="first", inplace=True)
    entity_df.reset_index(drop=True, inplace=True)
    entity_df.insert(0, config["id_col"], entity_df.index + 2)

    default_row = pd.DataFrame({
        config["id_col"]: [1],
        config["name_col"]: [config["default_name"]],
        "profile_link": [np.nan],
    })
    return pd.concat([default_row, entity_df], ignore_index=True)


def load_source_books():
    source_specs = [
        (ENTITY_CONFIGS["author"]["processed_file"], {
            "Author": "author_name",
            "Publisher": "publisher_name",
            "Title": "book_name",
            "Main_Price": "main_price",
            "Rokomari_Price": "rokomari_price",
            "book_url": "book_url",
            "book_numeric_id": "book_numeric_id",
        }),
        (ENTITY_CONFIGS["publisher"]["processed_file"], {
            "Author": "author_name",
            "Publisher": "publisher_name",
            "Title": "book_name",
            "Main_Price": "main_price",
            "Rokomari_Price": "rokomari_price",
            "book_url": "book_url",
            "book_numeric_id": "book_numeric_id",
        }),
    ]
    frames = []

    for path, rename_map in source_specs:
        if not path.exists():
            raise FileNotFoundError(f"Missing processed book file: {path}")
        df = pd.read_csv(path, low_memory=False)
        df.rename(columns=rename_map, inplace=True)
        for col in BOOK_COLUMNS:
            if col not in df.columns:
                df[col] = np.nan
        frames.append(df[BOOK_COLUMNS])

    combined_df = pd.concat(frames, ignore_index=True)
    for col in TEXT_COLUMNS:
        combined_df[col] = combined_df[col].map(normalize_text)

    combined_df.dropna(subset=["book_name"], inplace=True)
    combined_df["main_price"] = combined_df["main_price"].apply(clean_price)
    combined_df["rokomari_price"] = combined_df["rokomari_price"].apply(clean_price)
    combined_df["main_price"] = np.where(combined_df["main_price"] == 0, combined_df["rokomari_price"], combined_df["main_price"])
    return combined_df


def build_clean_csvs():
    print("[BUILD] Loading and merging processed Rokomari book rows...")
    combined_df = load_source_books()
    combined_df.to_csv(PROCESSED_DIR / "all_scraped_book_rows.csv", index=False, encoding="utf-8-sig")
    combined_df.to_csv(PROJECT_DIR / "all_scraped_book_rows.csv", index=False, encoding="utf-8-sig")

    # Group by canonical book numeric ID or book URL
    group_col = "book_numeric_id" if combined_df["book_numeric_id"].notna().sum() > 0.8 * len(combined_df) else "book_name"
    print(f"[BUILD] Grouping books by canonical identifier '{group_col}'...")

    final_df = combined_df.groupby(group_col, sort=False).agg({
        "book_name": lambda x: first_valid(x, "Unknown Book"),
        "author_name": lambda x: first_valid(x, "Unknown Author"),
        "publisher_name": lambda x: first_valid(x, "Unknown Publisher"),
        "main_price": "max",
        "rokomari_price": "max",
        "book_url": lambda x: first_valid(x, np.nan),
    }).reset_index()

    authors = make_entity_table("author", final_df)
    publishers = make_entity_table("publisher", final_df)

    books = final_df.merge(authors, on="author_name", how="left") \
                    .merge(publishers, on="publisher_name", how="left")

    for id_col in ["author_id", "publisher_id"]:
        books[id_col] = books[id_col].fillna(1).astype(int)

    books = books[["book_name", "author_id", "publisher_id", "main_price", "rokomari_price", "book_url"]].reset_index(drop=True)
    books.insert(0, "book_id", books.index + 1)

    outputs = {
        "clean_authors.csv": authors,
        "clean_publishers.csv": publishers,
        "clean_books.csv": books,
    }
    for filename, df in outputs.items():
        root_path = PROJECT_DIR / filename
        processed_path = PROCESSED_DIR / filename
        df.to_csv(root_path, index=False, encoding="utf-8-sig")
        shutil.copyfile(root_path, processed_path)
        print(f"[OK] {filename}: {len(df)} rows")

    # Build master
    master = books.merge(authors[["author_id", "author_name"]], on="author_id", how="left") \
                  .merge(publishers[["publisher_id", "publisher_name"]], on="publisher_id", how="left")
    master = master[["book_id", "book_name", "author_id", "author_name", "publisher_id", "publisher_name", "main_price", "rokomari_price", "book_url"]]

    for path in [PROJECT_DIR / "master.csv", PROCESSED_DIR / "master.csv"]:
        master.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"[OK] master.csv: {len(master)} rows")

    return authors, publishers, books, master


def upload_sql(authors, publishers, books):
    print("[SQL] Connecting and rebuilding Rokomari database tables...")
    server_uri = f"mysql+mysqlconnector://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}"
    base_engine = create_engine(server_uri)
    with base_engine.begin() as conn:
        conn.execute(text(f"CREATE DATABASE IF NOT EXISTS {DB_NAME}"))

    database_uri = f"mysql+mysqlconnector://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    engine = create_engine(database_uri)

    with engine.begin() as conn:
        existing_objects = conn.execute(text("SHOW FULL TABLES")).fetchall()
        for row in existing_objects:
            object_name = row[0]
            object_type = str(row[1]).upper()
            escaped_name = str(object_name).replace("`", "``")
            if object_type == "VIEW":
                conn.execute(text(f"DROP VIEW IF EXISTS `{escaped_name}`"))
            else:
                conn.execute(text(f"DROP TABLE IF EXISTS `{escaped_name}`"))

    authors.to_sql("authors", con=engine, if_exists="replace", index=False)
    publishers.to_sql("publishers", con=engine, if_exists="replace", index=False)
    books.to_sql("books", con=engine, if_exists="replace", index=False)

    master_query = """
        CREATE TABLE master AS
        SELECT
            b.book_id,
            b.book_name,
            b.author_id,
            a.author_name,
            b.publisher_id,
            p.publisher_name,
            b.main_price,
            b.rokomari_price,
            b.book_url
        FROM books b
        LEFT JOIN authors a ON b.author_id = a.author_id
        LEFT JOIN publishers p ON b.publisher_id = p.publisher_id
    """
    with engine.begin() as conn:
        conn.execute(text(master_query))

    master_df = pd.read_sql(text("SELECT * FROM master ORDER BY book_id"), con=engine)
    for path in [PROJECT_DIR / "master.csv", PROCESSED_DIR / "master.csv"]:
        master_df.to_csv(path, index=False, encoding="utf-8-sig")

    print("[SQL] Created tables: authors, publishers, books, master")
    print(f"[SQL] Master rows: {len(master_df)}")


def verify_sql():
    database_uri = f"mysql+mysqlconnector://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    try:
        engine = create_engine(database_uri)
        with engine.connect() as conn:
            for table in ["authors", "publishers", "books", "master"]:
                count = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
                print(f"[VERIFY SQL] {table}: {count}")

            checks = {
                "orphan_author_fk": "SELECT COUNT(*) FROM books b LEFT JOIN authors a ON b.author_id=a.author_id WHERE a.author_id IS NULL",
                "orphan_publisher_fk": "SELECT COUNT(*) FROM books b LEFT JOIN publishers p ON b.publisher_id=p.publisher_id WHERE p.publisher_id IS NULL",
            }
            for label, query in checks.items():
                count = conn.execute(text(query)).scalar()
                print(f"[VERIFY SQL] {label}: {count}")
    except Exception as exc:
        print(f"[VERIFY SQL] MySQL check skipped or unavailable: {exc}")


def verify_local_csvs():
    print("==================================================")
    print("ROKOMARI DATA INTEGRITY VERIFICATION REPORT")
    print("==================================================")
    for name in ["clean_authors.csv", "clean_publishers.csv", "clean_books.csv", "master.csv"]:
        p = PROJECT_DIR / name
        if not p.exists():
            print(f"[FAIL] Missing {name}")
            return False

    authors = pd.read_csv(PROJECT_DIR / "clean_authors.csv")
    publishers = pd.read_csv(PROJECT_DIR / "clean_publishers.csv")
    books = pd.read_csv(PROJECT_DIR / "clean_books.csv")
    master = pd.read_csv(PROJECT_DIR / "master.csv")

    print(f"Authors: {len(authors):,}")
    print(f"Publishers: {len(publishers):,}")
    print(f"Books: {len(books):,}")
    print(f"Master: {len(master):,}")

    orphan_authors = (~books["author_id"].isin(authors["author_id"])).sum()
    orphan_publishers = (~books["publisher_id"].isin(publishers["publisher_id"])).sum()

    print(f"Orphan author FKs: {orphan_authors}")
    print(f"Orphan publisher FKs: {orphan_publishers}")

    null_summary = master.isnull().sum()
    print("Master Null Summary:")
    print(null_summary.to_dict())

    zero_main = (master["main_price"] == 0).sum()
    zero_rokomari = (master["rokomari_price"] == 0).sum()
    anomaly_price = (master["rokomari_price"] > master["main_price"]).sum()
    print(f"Zero main_price: {zero_main:,}")
    print(f"Zero rokomari_price: {zero_rokomari:,}")
    print(f"Rokomari price > Main price anomalies: {anomaly_price:,}")
    print(f"Max main_price: ৳{master['main_price'].max():,}, Min: ৳{master['main_price'].min():,}")
    print("==================================================")
    return orphan_authors == 0 and orphan_publishers == 0


def run_scrape(force_list=False):
    print("[SCRAPE] Building raw author and publisher lists...")
    for entity_type in ENTITY_TYPES:
        scrape_entity_list(entity_type, force=force_list)

    print("[SCRAPE] Scraping books under each entity...")
    for entity_type in ENTITY_TYPES:
        scrape_entity_books(entity_type)


def main():
    parser = argparse.ArgumentParser(description="Single-file Rokomari scrape, clean, and SQL pipeline.")
    parser.add_argument("--scrape", action="store_true", help="Scrape raw entity lists and books before building.")
    parser.add_argument("--force-list", action="store_true", help="Refresh raw author/publisher lists even if CSVs exist.")
    parser.add_argument("--build-only", action="store_true", help="Build clean CSVs only; do not upload SQL.")
    parser.add_argument("--verify-only", action="store_true", help="Run local CSV data integrity verification only.")
    args = parser.parse_args()

    if args.verify_only:
        verify_local_csvs()
        return

    if args.scrape:
        run_scrape(force_list=args.force_list)

    authors, publishers, books, master = build_clean_csvs()
    verify_local_csvs()

    if not args.build_only:
        try:
            upload_sql(authors, publishers, books)
            verify_sql()
        except Exception as e:
            print(f"[SQL WARNING] SQL upload skipped or failed: {e}")

    print("[DONE] Rokomari pipeline execution completed.")


if __name__ == "__main__":
    main()
