import csv
import os
import time
import random
from playwright.sync_api import sync_playwright
from playwright_stealth.stealth import Stealth

PUBLISHERS_CSV = "rokomari_publishers_playwright.csv"

def scrape_publishers_with_playwright(max_pages=100):
    print(f"[PLAYWRIGHT START] স্টিলথ মোডে প্রকাশনী স্ক্র্যাপিং শুরু হচ্ছে (সর্বোচ্চ {max_pages} পেজ)...")
    publishers_list = []
    seen_links = set()
    chrome_executable = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    
    with sync_playwright() as p:
        # ১. লোকাল ক্রোম বাইনারি ব্যবহার করে ব্রাউজার লঞ্চ করা
        launch_kwargs = {"headless": False}
        if os.path.exists(chrome_executable):
            launch_kwargs["executable_path"] = chrome_executable
        browser = p.chromium.launch(**launch_kwargs)
        
        # ২. মানুষের মতো ব্রাউজার কন্টেক্সট তৈরি
        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        
        # ৩. ক্লাউডফ্লেয়ার বাইপাসের জন্য স্টিলথ প্লাগইন অ্যাপ্লাই
        Stealth().apply_stealth_sync(page)
        
        # মেইন ইউআরএল পাথ (পাবলিশার্স)
        base_url = "https://www.rokomari.com/book/publishers"
        
        for p_num in range(1, max_pages + 1):
            url = f"{base_url}?ref=sm&page={p_num}"
            print(f" -> ব্রাউজার ভিজিট করছে প্রকাশনী পেজ {p_num}: {url}")
            
            try:
                # পেজ লোড হওয়া পর্যন্ত ওয়েট করা
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                
                # অ্যান্টি-বট ট্রিগার এড়াতে র্যান্ডম ডিলে
                time.sleep(random.uniform(4.0, 6.0))
                
                print(f"    পেজের বর্তমান টাইটেল: {page.title()}")
                
                # ৪. সমস্ত 'a' ট্যাগ এক্সট্রাক্ট করা
                a_tags = page.query_selector_all("a")
                found_in_page = 0
                
                for a in a_tags:
                    href = a.get_attribute("href")
                    # রকমারির প্রকাশনী ফিল্টার (যেমন: /book/publisher/123/anannya)
                    if href and "/book/publisher/" in href:
                        # ট্র্যাকিং কুয়েরি বাদ দেওয়া
                        clean_href = href.split('?')[0] if '?' in href else href
                        name = a.inner_text().strip()
                        
                        # অপ্রয়োজনীয় বাটন ফিল্টার আউট করা
                        if name and name not in ["Next", "Previous", "Next ", " Previous", "আরও দেখুন"]:
                            full_link = clean_href if clean_href.startswith("http") else f"https://www.rokomari.com{clean_href}"
                            
                            # ইনক্রিমেন্টাল আইডি জেনারেশন
                            publisher_id = str(len(publishers_list) + 1)
                            publisher_node = {"id": publisher_id, "name": name, "link": full_link}
                            
                            if full_link not in seen_links:
                                publishers_list.append(publisher_node)
                                seen_links.add(full_link)
                                found_in_page += 1
                                
                print(f"    সফলতা: পেজ {p_num} থেকে {found_in_page} টি প্রকাশনী পাওয়া গেছে।")
                
                # এজ কেস: কোনো পেজে যদি কোনো পাবলিশার না পাওয়া যায়, তবে লুপ শেষ করা
                if found_in_page == 0:
                    print(" -> এই পেজে কোনো প্রকাশনী নেই। স্ক্র্যাপিং সমাপ্ত করা হচ্ছে।")
                    break
                
            except Exception as page_err:
                print(f"    [ERROR] পেজ {p_num} লোড করতে সমস্যা হয়েছে: {page_err}")
                break
                
        # সেশন ক্লোজ
        browser.close()

    # CSV ফাইলে ডেটা রাইট করা
    if publishers_list:
        with open(PUBLISHERS_CSV, mode="w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["id", "name", "link"])
            writer.writeheader()
            writer.writerows(publishers_list)
        print(f"\n[SUCCESS] মোট {len(publishers_list)} টি প্রকাশনীর তালিকা '{PUBLISHERS_CSV}' ফাইলে সুরক্ষিত আছে।")
    else:
        print("\n[FAILED] কোনো প্রকাশনীর ডেটা স্ক্র্যাপ করা যায়নি।")

if __name__ == "__main__":
    # রকমারিতে মোট প্রকাশনী পেজ সংখ্যা লেখকদের চেয়ে কম (সাধারণত ১০০ পেজের কম)
    scrape_publishers_with_playwright(max_pages=100)