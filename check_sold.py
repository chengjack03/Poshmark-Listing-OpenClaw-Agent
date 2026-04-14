"""
Check Poshmark for sold listings and match against processed/ folder.
Outputs a list of listing IDs that have sold, for the agent to act on.

The agent should:
1. Run this script
2. For each sold listing found, message Master Jack:
   "🎉 [Title] sold for $[price]! OK to delete the photos? Reply YES to delete or NO to keep."
3. On YES: delete processed/{listing_id}/
4. On NO or no reply: leave photos in place
"""
import asyncio, json, os, sys

COOKIES_FILE   = "/home/cymolt/poshmark_listings/auth.json"
PROCESSED_DIR  = "/home/cymolt/poshmark_listings/processed"
POSHMARK_USER  = "POSHMARK_USER_REDACTED"
SAMESITE_MAP   = {"no_restriction":"None","unspecified":"None","lax":"Lax","strict":"Strict","none":"None"}


def normalize_cookie(c):
    nc = {"name":c["name"],"value":c["value"],"domain":c["domain"],"path":c.get("path","/"),
          "httpOnly":c.get("httpOnly",False),"secure":c.get("secure",False),
          "sameSite":SAMESITE_MAP.get(c.get("sameSite","None").lower(),"None")}
    if "expirationDate" in c:
        nc["expires"] = c["expirationDate"]
    return nc


def load_processed_listings():
    """Return dict of listing_id → listing.json metadata for all processed listings."""
    result = {}
    if not os.path.exists(PROCESSED_DIR):
        return result
    for listing_id in os.listdir(PROCESSED_DIR):
        meta_path = os.path.join(PROCESSED_DIR, listing_id, "listing.json")
        if os.path.exists(meta_path):
            with open(meta_path) as f:
                result[listing_id] = json.load(f)
    return result


async def get_sold_listing_ids(cookies):
    """Scrape poshmark sold listings page and return list of listing IDs."""
    from playwright.async_api import async_playwright

    sold_ids = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            viewport={"width":1280,"height":900},
            user_agent="Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36"
        )
        await ctx.add_cookies(cookies)
        page = await ctx.new_page()

        await page.goto(
            f"https://poshmark.com/closet/{POSHMARK_USER}?availability=sold_out",
            wait_until="networkidle", timeout=30000
        )
        await page.wait_for_timeout(2000)

        # Extract listing IDs from href links on the sold page
        hrefs = await page.evaluate("""() => {
            var links = [...document.querySelectorAll('a[href*="/listing/"]')];
            return links.map(a => a.href).filter(h => h.includes('/listing/'));
        }""")

        import re
        for href in hrefs:
            m = re.search(r'/listing/([a-f0-9]+)', href)
            if m:
                lid = m.group(1)
                if lid not in sold_ids:
                    sold_ids.append(lid)

        await browser.close()

    return sold_ids


def delete_listing_photos(listing_id):
    """Permanently delete photos and metadata for a listing."""
    import shutil
    dest_dir = os.path.join(PROCESSED_DIR, listing_id)
    if os.path.exists(dest_dir):
        shutil.rmtree(dest_dir)
        print(f"Deleted processed/{listing_id}/")
        return True
    return False


async def main():
    with open(COOKIES_FILE) as f:
        cookies = [normalize_cookie(c) for c in json.load(f) if "poshmark" in c.get("domain","")]

    # If called with --delete {listing_id}, delete that listing's photos
    if len(sys.argv) == 3 and sys.argv[1] == "--delete":
        listing_id = sys.argv[2]
        if delete_listing_photos(listing_id):
            print(f"OK photos deleted for {listing_id}")
        else:
            print(f"NOT_FOUND {listing_id}")
        return

    processed = load_processed_listings()
    if not processed:
        print("NO_PROCESSED no listings in processed/ folder")
        return

    print(f"Checking {len(processed)} processed listing(s) against Poshmark sold...")
    sold_ids = await get_sold_listing_ids(cookies)
    print(f"Found {len(sold_ids)} sold listing ID(s) on Poshmark")

    matches = []
    for listing_id, meta in processed.items():
        if listing_id in sold_ids:
            matches.append({
                "listing_id": listing_id,
                "title": meta.get("title"),
                "list_price": meta.get("list_price"),
                "poshmark_url": meta.get("poshmark_url"),
            })
            print(f"SOLD {listing_id} — {meta.get('title')} (${meta.get('list_price')})")

    if not matches:
        print("NO_SOLD none of the processed listings have sold yet")
    else:
        # Output JSON for the agent to parse
        print("SOLD_JSON " + json.dumps(matches))


asyncio.run(main())
