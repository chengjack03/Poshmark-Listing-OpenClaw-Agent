"""Deep inspect of the create-listing page to find category selector and all hidden elements."""
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
        ctx = await browser.new_context(
            viewport={"width":1280,"height":900},
            user_agent="Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        await ctx.add_cookies(cookies)
        page = await ctx.new_page()
        await page.goto("https://poshmark.com/create-listing", wait_until="networkidle", timeout=60000)
        await page.wait_for_timeout(3000)

        # Dismiss cookie banner
        ok_btn = page.locator('button.btn--primary', has_text="Ok")
        if await ok_btn.count() > 0 and await ok_btn.first.is_visible():
            await ok_btn.first.click()
            await page.wait_for_timeout(500)
            print("Cookie banner dismissed")

        # Full page screenshot
        await page.screenshot(path="/home/cymolt/poshmark_listings/full_page.png", full_page=True)
        print("Full page screenshot saved")

        # Dump ALL elements with 'categor' in class/id/data attributes
        cat_els = await page.eval_on_selector_all(
            "*",
            """els => els
                .filter(e => {
                    const s = (e.className||'') + (e.id||'') + (e.getAttribute('data-et-name')||'') + (e.getAttribute('data-vv-name')||'');
                    return s.toLowerCase().includes('categor');
                })
                .map(e => ({
                    tag: e.tagName,
                    class: e.className.substring(0,100),
                    id: e.id,
                    text: e.textContent.trim().substring(0,80),
                    visible: e.offsetParent !== null,
                    dataEt: e.getAttribute('data-et-name'),
                    dataVv: e.getAttribute('data-vv-name'),
                    role: e.getAttribute('role'),
                }))
                .slice(0, 30)
            """
        )
        print(f"\n=== Category-related elements ({len(cat_els)}) ===")
        for e in cat_els:
            print(e)

        # Dump all clickable elements that might be category
        print("\n=== All buttons/links with 'Kids'/'Category'/'Select' text ===")
        sel_els = await page.eval_on_selector_all(
            "button, a, [role='button'], li, .dropdown__menu-item",
            """els => els
                .filter(e => /kids|categor|select a|department/i.test(e.textContent))
                .map(e => ({
                    tag: e.tagName,
                    class: e.className.substring(0,80),
                    text: e.textContent.trim().substring(0,80),
                    visible: e.offsetParent !== null,
                }))
                .slice(0, 20)
            """
        )
        for e in sel_els:
            print(e)

        # Also dump structure of listing-editor sections
        print("\n=== Listing editor section headers ===")
        headers = await page.eval_on_selector_all(
            ".listing-editor__label, .form__label, [class*='listing-editor__section']",
            "els => els.map(e => ({class: e.className.substring(0,80), text: e.textContent.trim().substring(0,60), visible: e.offsetParent !== null}))"
        )
        for h in headers:
            print(h)

        await browser.close()

asyncio.run(main())
