import csv
import re


BOOK_URL = re.compile(r"^https://www\.rokomari\.com/book/(\d+)(?:/([^/?#]+))?$")


def compact_ranges(values):
    numbers = sorted(int(value) for value in values if value.isdigit())
    if not numbers:
        return "none"
    ranges = []
    start = previous = numbers[0]
    for number in numbers[1:]:
        if number == previous + 1:
            previous = number
            continue
        ranges.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = number
    ranges.append(str(start) if start == previous else f"{start}-{previous}")
    return ", ".join(ranges)


def clean_file(source_path, output_path, report_path, owner_key, owner_label, input_path):
    with open(source_path, encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    clean_rows = []
    seen_owner_links = set()
    rejected = 0
    duplicate_owner_links = 0
    for row in rows:
        match = BOOK_URL.match((row.get("book_link") or "").strip())
        if not match:
            rejected += 1
            continue
        row["book_numeric_id"] = match.group(1)
        row["book_slug"] = match.group(2) or ""
        owner_link = (row.get(owner_key, ""), row.get("book_link", ""))
        if owner_link in seen_owner_links:
            duplicate_owner_links += 1
            continue
        seen_owner_links.add(owner_link)
        clean_rows.append(row)

    with open(output_path, "w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(clean_rows)

    with open(input_path, encoding="utf-8-sig", newline="") as source:
        input_ids = {row.get("id", "") for row in csv.DictReader(source) if row.get("id")}
    output_ids = {row.get(owner_key, "") for row in clean_rows}
    missing_ids = sorted(input_ids - output_ids, key=lambda value: int(value) if value.isdigit() else value)
    links = [row.get("book_link", "") for row in clean_rows]
    with open(report_path, "w", encoding="utf-8") as report:
        report.write(f"ROKOMARI {owner_label.upper()} VERIFIED DATA REPORT\n")
        report.write("=" * (25 + len(owner_label)) + "\n\n")
        report.write("Source: existing enriched CSV cleaned locally; not a fresh website scrape.\n")
        report.write(f"Input rows: {len(rows)}\n")
        report.write(f"Verified rows saved: {len(clean_rows)}\n")
        report.write(f"Rejected non-book/navigation rows: {rejected}\n")
        report.write(f"Removed duplicate rows for the same {owner_label}: {duplicate_owner_links}\n")
        report.write(f"{owner_label.title()}s with at least one book: {len(output_ids)}\n")
        report.write(f"{owner_label.title()}s with no saved book: {len(missing_ids)}\n")
        report.write(f"Repeated links across different {owner_label}s: {len(links) - len(set(links))}\n\n")
        report.write("HOW TO READ THIS\n")
        report.write("- Every saved book_link matches /book/<numeric-id>; navigation links were removed.\n")
        report.write("- Repeated links across different owners can be valid because a book may have multiple owners.\n")
        report.write("- A missing owner means no valid book row was present in the source snapshot.\n")
        if missing_ids:
            report.write("\nMissing owner ID ranges: " + compact_ranges(missing_ids) + "\n")


if __name__ == "__main__":
    clean_file(
        "rokomari_author_books_enriched.csv",
        "rokomari_author_books_verified.csv",
        "rokomari_author_books_verified_quality.txt",
        "author_id",
        "author",
        "rokomari_authors_playwright.csv",
    )
    clean_file(
        "rokomari_publisher_books_enriched.csv",
        "rokomari_publisher_books_verified.csv",
        "rokomari_publisher_books_verified_quality.txt",
        "publisher_id",
        "publisher",
        "rokomari_publishers_playwright.csv",
    )
    print("Verified CSVs and quality reports generated.")