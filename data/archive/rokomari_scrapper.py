import csv
import os
import time
import random
from playwright.sync_api import sync_playwright
from playwright_stealth.stealth import Stealth

AUTHORS_CSV = "rokomari_authors_playwright.csv"

def scrape_authors_with_playwright(max_pages=400):
    print(f"[PLAYWRIGHT START] স্টিলথ মোডে স্ক্র্যাপিং শুরু হচ্ছে (সর্বোচ্চ {max_pages} পেজ)...")
    authors_list = []
    seen_links = set()
    chrome_executable = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    
    with sync_playwright() as p:
        # ১. আসল ব্রাউজার সিমুলেট করার জন্য ক্রোমিয়াম লঞ্চ করা
        # headless=False রাখছি যাতে তুমি লাইভ দেখতে পারো ক্লাউডফ্লেয়ার পার হচ্ছে কিনা।
        launch_kwargs = {"headless": False}
        if os.path.exists(chrome_executable):
            launch_kwargs["executable_path"] = chrome_executable
        browser = p.chromium.launch(**launch_kwargs)
        
        # ২. একটি ব্রাউজার কন্টেক্সট এবং পেজ তৈরি করা (মানুষের মতো স্ক্রিন সাইজ সেট করা)
        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        
        # ৩. দ্য ম্যাজিক লাইন: পেজের ওপর স্টিলথ প্লাগইন অ্যাক্টিভেট করা
        # এটি navigator.webdriver এবং অন্যান্য রোবট সিগনেচার মুছে দেয়
        Stealth().apply_stealth_sync(page)
        
        base_url = "https://www.rokomari.com/book/authors"
        
        for p_num in range(1, max_pages + 1):
            url = f"{base_url}?ref=sm&page={p_num}"
            print(f" -> ব্রাউজার ভিজিট করছে পেজ {p_num}: {url}")
            
            try:
                # পেজ লোড হওয়া এবং নেটওয়ার্ক কানেকশন শান্ত হওয়া পর্যন্ত ওয়েট করা
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                
                # ক্লাউডফ্লেয়ার যদি কোনো র্যান্ডম চ্যালেঞ্জ দেয়, তার জন্য ৪-৬ সেকেন্ড সেফটি ডিলে
                time.sleep(random.uniform(4.0, 6.0))
                
                print(f"    পেজের বর্তমান টাইটেল: {page.title()}")
                
                # ৪. পেজের সমস্ত 'a' (অ্যাঙ্কর) ট্যাগ খুঁজে বের করা
                a_tags = page.query_selector_all("a")
                found_in_page = 0
                
                for a in a_tags:
                    href = a.get_attribute("href")
                    if href and "/book/author/" in href:
                        # ট্র্যাকিং প্যারামিটার ফিল্টার করা
                        clean_href = href.split('?')[0] if '?' in href else href
                        name = a.inner_text().strip()
                        
                        if name and name not in ["Next", "Previous", "Next ", " Previous", "আরও দেখুন"]:
                            full_link = clean_href if clean_href.startswith("http") else f"https://www.rokomari.com{clean_href}"
                            author_id = str(len(authors_list) + 1)
                            
                            author_node = {"id": author_id, "name": name, "link": full_link}
                            if full_link not in seen_links:
                                authors_list.append(author_node)
                                seen_links.add(full_link)
                                found_in_page += 1
                                
                print(f"    সফলতা: পেজ {p_num} থেকে {found_in_page} জন লেখক পাওয়া গেছে।")
                
            except Exception as page_err:
                print(f"    [ERROR] পেজ {p_num} লোড করতে সমস্যা হয়েছে: {page_err}")
                break
                
        # ব্রাউজার সেশন ক্লোজ করা
        browser.close()

    # ডাটা CSV ফাইলে রাইট করা
    if authors_list:
        with open(AUTHORS_CSV, mode="w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["id", "name", "link"])
            writer.writeheader()
            writer.writerows(authors_list)
        print(f"\n[SUCCESS] মোট {len(authors_list)} জন লেখকের তালিকা '{AUTHORS_CSV}' ফাইলে সুরক্ষিত আছে।")
    else:
        print("\n[FAILED] কোনো ডেটা স্ক্র্যাপ করা যায়নি।")

if __name__ == "__main__":
    scrape_authors_with_playwright(max_pages=400)