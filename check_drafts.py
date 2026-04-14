"""Check drafts count and list on Poshmark."""
import asyncio, json

COOKIES_FILE = "/home/cymolt/poshmark_listings/auth.json"
SAMESITE_MAP = {"no_restriction":"None","unspecified":"None","lax":"Lax","strict":"Strict","none":"None"}

def nc(c):
    r = {"name":c["name"],"value":c["value"],"domain":c["domain"],"path":c.get("path","/"),
         "httpOnly":c.get("httpOnly",False),"secure":c.get("secure",False),
         "sameSite":SAMESITE_MAP.get(c.get("sameSite","None").lower(),"None")}
    if "expirationDate" in c: r["expires"] = c["expirationDate"]
    return r

async def main():
    from playwright.async_api import async_playwright
    with open(COOKIES_FILE) as f:
        cookies = [nc(c) for c in json.load(f) if "poshmark" in c.get("domain","")]

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width":1280,"height":900},
            user_agent="Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
        await ctx.add_cookies(cookies)
        page = await ctx.new_page()

        # Check drafts via the drafts page
        await page.goto("https://poshmark.com/closet/POSHMARK_USER_REDACTED?availability=draft", wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)

        title = await page.title()
        url = page.url
        print(f"URL: {url}")
        print(f"Title: {title}")

        # Try to find listing cards
        listings = await page.eval_on_selector_all(
            ".tile__title, .listing-title, [data-et-name='listing_title'], .card__title",
            "els => els.map(e => e.textContent.trim().substring(0,80))"
        )
        print(f"\nDraft listings found ({len(listings)}):")
        for l in listings:
            print(f"  - {l}")

        # Also check for draft count indicator
        draft_count = await page.eval_on_selector_all(
            "*",
            """els => els.filter(e => /draft/i.test(e.textContent) && e.textContent.length < 40)
               .map(e => e.textContent.trim()).slice(0,5)"""
        )
        print(f"\nDraft-related text on page: {draft_count}")

        await page.screenshot(path="/home/cymolt/poshmark_listings/drafts_check.png")
        print("\nScreenshot saved: drafts_check.png")
        await browser.close()

asyncio.run(main())
