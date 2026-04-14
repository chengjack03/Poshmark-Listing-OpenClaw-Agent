"""
Inspect the Poshmark create-listing page to find current field selectors.
"""
import asyncio, json

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
        context = await browser.new_context(user_agent="Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
        await context.add_cookies(cookies)
        page = await context.new_page()

        await page.goto("https://poshmark.com/create-listing", wait_until="networkidle", timeout=60000)
        await page.wait_for_timeout(3000)

        print("URL:", page.url)
        print("Title:", await page.title())

        # Dump all inputs and textareas
        inputs = await page.eval_on_selector_all(
            "input, textarea, [contenteditable], [role='textbox']",
            "els => els.map(e => ({tag:e.tagName, name:e.name||'', id:e.id||'', placeholder:e.placeholder||'', type:e.type||'', 'aria-label':e.getAttribute('aria-label')||'', class:e.className.substring(0,80)}))"
        )
        print(f"\n=== Found {len(inputs)} input/textarea/editable elements ===")
        for i, el in enumerate(inputs):
            print(f"[{i}] {el}")

        # Dump buttons
        buttons = await page.eval_on_selector_all(
            "button",
            "els => els.map(e => ({text:e.textContent.trim().substring(0,60), class:e.className.substring(0,60), 'aria-label':e.getAttribute('aria-label')||''}))"
        )
        print(f"\n=== Found {len(buttons)} buttons ===")
        for i, b in enumerate(buttons):
            print(f"[{i}] {b}")

        await page.screenshot(path="/home/cymolt/poshmark_listings/inspect_listing.png")
        print("\nScreenshot saved.")
        await browser.close()

asyncio.run(main())
