"""Delete all draft listings from Poshmark."""
import asyncio
import json

COOKIES_FILE = "/home/cymolt/poshmark_listings/auth.json"
SAMESITE_MAP = {"no_restriction":"None","unspecified":"None","lax":"Lax","strict":"Strict","none":"None"}

def normalize_cookie(c):
    nc = {"name":c["name"],"value":c["value"],"domain":c["domain"],"path":c.get("path","/"),
          "httpOnly":c.get("httpOnly",False),"secure":c.get("secure",False),
          "sameSite":SAMESITE_MAP.get(c.get("sameSite","None").lower(),"None")}
    if "expirationDate" in c:
        nc["expires"] = c["expirationDate"]
    return nc

async def main():
    from playwright.async_api import async_playwright
    with open(COOKIES_FILE) as f:
        cookies = [normalize_cookie(c) for c in json.load(f) if "poshmark" in c.get("domain","")]

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            viewport={"width":1280,"height":900},
            user_agent="Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        await ctx.add_cookies(cookies)
        page = await ctx.new_page()

        deleted = 0
        while True:
            await page.goto("https://poshmark.com/create-listing", wait_until="networkidle", timeout=60000)
            await page.wait_for_timeout(2000)

            # Dismiss cookie banner if present
            try:
                btn = page.locator('button.btn--primary:has-text("Ok")')
                if await btn.count() > 0 and await btn.first.is_visible():
                    await btn.first.click(force=True)
                    await page.wait_for_timeout(400)
            except Exception:
                pass

            # Find draft tiles — they live in the Drafts section above the create form
            draft_tiles = page.locator('[class*="draft"] [class*="tile"], [class*="draft"] [class*="card"], [class*="drafts-list"] li, .listing-card--draft')
            count = await draft_tiles.count()

            # Fallback: look for any clickable element in the Drafts section header area
            if count == 0:
                draft_tiles = page.locator('section:has-text("Drafts") a, [data-test*="draft"] a')
                count = await draft_tiles.count()

            # Second fallback: find by the thumbnail imgs inside the Drafts collapsible
            if count == 0:
                # The draft section is the first section above .listing-editor
                draft_tiles = page.locator('.drafts__list-container .tile, .draft-listing, [class*="draft"] img').first
                count = 1 if await draft_tiles.count() > 0 else 0

            if count == 0:
                print(f"No more drafts found. Total deleted: {deleted}")
                break

            print(f"Found draft tiles, clicking first one...")
            # Click the first draft tile to open it for editing
            tile = page.locator('[class*="draft"] img, [class*="draft"] [class*="tile"]').first
            if await tile.count() == 0:
                print("Could not locate draft tile element. Stopping.")
                break

            await tile.click()
            await page.wait_for_timeout(2500)
            await page.screenshot(path=f"/home/cymolt/poshmark_listings/delete_debug_{deleted}.png")

            # Scroll to the bottom to find Delete Listing button
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(800)

            delete_btn = page.locator('button:has-text("Delete Listing")').first
            try:
                await delete_btn.wait_for(state="visible", timeout=8000)
                await delete_btn.click()
                await page.wait_for_timeout(1500)
                print(f"  Clicked Delete Listing")

                # Confirm deletion popup
                confirm_btn = page.locator('button:has-text("Yes"), button:has-text("Delete"), button:has-text("Confirm")').first
                await confirm_btn.wait_for(state="visible", timeout=5000)
                await confirm_btn.click()
                await page.wait_for_timeout(2000)
                deleted += 1
                print(f"  ✅ Draft {deleted} deleted")
            except Exception as e:
                print(f"  ❌ Could not delete: {e}")
                await page.screenshot(path=f"/home/cymolt/poshmark_listings/delete_fail_{deleted}.png")
                break

        await browser.close()
        print(f"\nDone. Deleted {deleted} drafts.")

asyncio.run(main())
