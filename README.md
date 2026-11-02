# Rokomari Scraper — Unified Pipeline & Automation

A unified, fault-tolerant scraping, cleaning, normalization, and relational catalog pipeline for Rokomari, structured identically to `wafilife scrapper`.

---

## Daily Scraping & Automation

- Use the project's virtual environment and run the pipeline with `--scrape`.
- Example (PowerShell):

```powershell
& ".\.venv\Scripts\python.exe" "rokomari_pipeline.py" --scrape
```

- Or execute the scheduled daily wrapper script:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_rokomari_daily.ps1
```

---

## Features & Reliability Design

### 1. Atomic File Updates
- All intermediate outputs and final CSVs are written to `.tmp` files first and replaced using atomic filesystem operations (`atomic_replace`).
- This guarantees that partial, interrupted, or crashed runs never corrupt previously valid data.

### 2. State & Resume Behavior
- Crawl progress is stored in `data/state/scraping_progress_authors.txt` and `data/state/scraping_progress_publishers.txt`.
- If a connection fails or is stopped, the pipeline automatically resumes exactly from the last saved page and entity.

### 3. Block & Anti-Bot Detection
- The scraper monitors for interstitial security pages (Cloudflare, captcha, access denied) via `is_blocked_page`.
- When triggered, it cleanly saves current state and stops without data loss.

### 4. Scoped DOM Selectors
- Unlike previous un-scoped `page.query_selector_all("a")` runs, `rokomari_pipeline.py` scopes item extraction strictly to `.productGridItem` cards.
- This completely prevents header/dropdown menu items (`/book/ebook`, `/book/categories`) and unrelated carousel bestsellers from polluting author book lists.

---

## How to Run

### 1. Build & Clean CSVs (No fresh web scrape, build from processed data)
```powershell
& ".\.venv\Scripts\python.exe" "rokomari_pipeline.py" --build-only
```

### 2. Verify Data Integrity Only
```powershell
& ".\.venv\Scripts\python.exe" "rokomari_pipeline.py" --verify-only
```

### 3. Resume Scrape
```powershell
& ".\.venv\Scripts\python.exe" "rokomari_pipeline.py" --scrape
```

### 4. Fresh Scrape (Force rebuild author/publisher lists)
```powershell
& ".\.venv\Scripts\python.exe" "rokomari_pipeline.py" --scrape --force-list
```

---

## Directory & File Layout

```
rokomar_scrapper/
├── data/
│   ├── archive/                     # Archived legacy dumps & previous unorganized CSVs
│   ├── logs/                        # Daily run logs (stdout & stderr)
│   ├── processed/                   # Cleaned entity scrapes and processed CSVs
│   │   ├── all_scraped_book_rows.csv
│   │   ├── clean_authors.csv
│   │   ├── clean_books.csv
│   │   ├── clean_publishers.csv
│   │   ├── master.csv
│   │   ├── Rokomari_Authors_Data.csv
│   │   └── Rokomari_Publishers_Data.csv
│   ├── raw/                         # Raw entity lists
│   │   ├── Rokomari_All_Authors.csv
│   │   └── Rokomari_All_Publishers.csv
│   └── state/                       # Resume markers for authors and publishers
├── database/
│   └── migrations/
│       ├── 001_catalog_schema.sql
│       └── 002_seed_sources.sql
├── all_scraped_book_rows.csv        # Top-level merged book rows (297,970 rows)
├── clean_authors.csv                # Relational authors table (30,136 authors)
├── clean_books.csv                  # Relational books table (91,497 canonical books)
├── clean_publishers.csv             # Relational publishers table (5,016 publishers)
├── master.csv                       # Master denormalized catalog (91,497 books)
├── docker-compose.yml               # Local MySQL & Chroma DB containers
├── requirements.txt                 # Python dependencies
├── README.md                        # Documentation
├── run_rokomari_daily.ps1           # Scheduled task runner
└── rokomari_pipeline.py             # Core unified pipeline
```

---

## Catalog Verification Summary

### Wafilife Scraped Data Verification:
- **Clean Books**: 59,886
- **Clean Authors**: 18,075
- **Clean Publishers**: 1,639
- **Clean Subjects**: 49
- **Master Rows**: 59,886
- **Orphan Foreign Keys**: 0 (all foreign keys valid)
- **Null Fields**: 0 across all columns
- **Price Check**: Main price and Wafilife price fully populated (3,229 books had higher Wafilife price due to independent `max()` aggregation during merging).

### Rokomari Scraped Data Verification:
- **Total Canonical Books**: 91,497
- **Total Authors**: 30,136
- **Total Publishers**: 5,016
- **Total Merged Scraped Rows**: 297,970
- **Orphan Foreign Keys**: 0
- **Master Null Counts**: 0
- **Price Anomalies (`rokomari_price > main_price`)**: 0
- **Quality Fixes Applied**:
  1. Filtered out 230,436 navigation links (`/book/ebook`, `/book/categories`, etc.) that were accidentally captured in previous crawls.
  2. Parsed and cleaned 94,000+ book cards where multiline card text had leaked into the `book_title` field.
  3. Extracted accurate discount pricing, author names, and canonical numeric book identifiers.
