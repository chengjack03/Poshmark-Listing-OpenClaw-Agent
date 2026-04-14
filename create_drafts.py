"""
Create 3 Zara kids Poshmark draft listings.
v6: Uploads cover shot photo per listing before saving draft.
"""
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

LISTINGS = [
    {
        "title": "Zara Girls Ribbed Floral Tank Top Size 6 Yellow Black Print",
        "description": (
            "Adorable Zara ribbed cotton tank in a yellow & black floral print on cream base. "
            "Gently worn — clean, no stains or damage. Made in Bangladesh.\n\n"
            "#ZaraKids #EuropeanKidsFashion #FloralPrint #GirlsTop #ZaraGirls"
        ),
        "brand": "Zara",
        "list_price": "14",
        "dept": "Kids",
        "category": "Shirts & Tops",
        "subcategory": None,
        "photo": "/home/cymolt/poshmark_listings/.openclaw_state/media/inbound/0e2f4c3f-ec1d-4ff6-9b50-bca5a179f1aa.jpg",
    },
    {
        "title": "Zara Girls Ribbed Cherry Print Tank Top Size 3-4Y",
        "description": (
            "Sweet Zara ribbed tank with red cherry print on white. "
            "Gently worn — clean, no damage. Made in Morocco. "
            "Pairs with matching cherry pants (sold separately)!\n\n"
            "#ZaraKids #CherryPrint #BabyCore #GirlsTop #ZaraGirls"
        ),
        "brand": "Zara",
        "list_price": "11",
        "dept": "Kids",
        "category": "Shirts & Tops",
        "subcategory": None,
        "photo": "/home/cymolt/poshmark_listings/.openclaw_state/media/inbound/2a392a71-2545-4158-ba79-791ea9ce6085.jpg",
    },
    {
        "title": "Zara Girls Ribbed Cherry Print Pants Size 3-4Y",
        "description": (
            "Cute Zara ribbed pants with elastic waist and red cherry print on white. "
            "Gently worn — clean, no damage. Made in Morocco. "
            "Pairs with matching cherry tank (sold separately)!\n\n"
            "#ZaraKids #CherryPrint #MatchingSet #GirlsPants #ZaraGirls"
        ),
        "brand": "Zara",
        "list_price": "12",
        "dept": "Kids",
        "category": "Bottoms",
        "subcategory": None,
        "photo": "/home/cymolt/poshmark_listings/.openclaw_state/media/inbound/8a2782d0-b6ff-4e3b-937c-0d6edb345e42.jpg",
    },
]


async def dismiss_cookie_banner(page, label=""):
    """Aggressively dismiss cookie banner via click and JS fallback."""
    tag = f" [{label}]" if label else ""
    try:
        ok_btn = page.locator('button.btn--primary:has-text("Ok"), button.btn--primary:has-text("OK"), button:has-text("Accept")')
        count = await ok_btn.count()
        for i in range(count):
            btn = ok_btn.nth(i)
            if await btn.is_visible():
                await btn.click(force=True)
                await page.wait_for_timeout(400)
                print(f"  🍪 Cookie banner dismissed (click){tag}")
                return
    except Exception:
        pass

    try:
        dismissed = await page.evaluate("""
            (function() {
                // Only act if a recognizable cookie banner container is present
                var banner = document.querySelector('.cookie-banner, [class*="cookie-consent"], [class*="gdpr"]');
                if (!banner) return false;
                // Click Ok/Accept button inside the banner
                var btns = banner.querySelectorAll('button');
                for (var b of btns) {
                    if (b.textContent.trim().match(/^(Ok|OK|Accept)$/)) {
                        b.click();
                        return true;
                    }
                }
                // No button found — remove the banner element itself
                banner.remove();
                return true;
            })()
        """)
        if dismissed:
            await page.wait_for_timeout(400)
            print(f"  🍪 Cookie banner dismissed (JS){tag}")
    except Exception:
        pass


async def js_fill(page, selector, value, label):
    """Fill a field via JS, retrying up to 10s if element not yet in DOM.

    For placeholder-based selectors (input[placeholder="..."] / textarea[placeholder="..."]),
    uses find(e => e.placeholder.includes(...)) to avoid querySelector serialization issues.
    For class/attribute selectors without placeholders, falls back to querySelector.
    """
    # Extract placeholder keyword if selector targets a placeholder attribute
    import re as _re
    ph_match = _re.search(r'placeholder=["\']([^"\']+)["\']', selector)
    placeholder_keyword = ph_match.group(1)[:12] if ph_match else None

    for attempt in range(20):
        try:
            if placeholder_keyword:
                result = await page.evaluate("""
                    ([keyword, val]) => {
                        var el = [...document.querySelectorAll('input,textarea')]
                            .find(e => e.placeholder.includes(keyword));
                        if (!el) return 'not_found';
                        el.scrollIntoView({block:'center'});
                        el.focus();
                        var proto = el.tagName === 'TEXTAREA'
                            ? window.HTMLTextAreaElement.prototype
                            : window.HTMLInputElement.prototype;
                        var nativeSetter = Object.getOwnPropertyDescriptor(proto, 'value');
                        if (nativeSetter) nativeSetter.set.call(el, val);
                        el.dispatchEvent(new Event('input', {bubbles:true}));
                        el.dispatchEvent(new Event('change', {bubbles:true}));
                        return 'ok';
                    }
                """, [placeholder_keyword, value])
            else:
                result = await page.evaluate("""
                    ([sel, val]) => {
                        var el = document.querySelector(sel);
                        if (!el) return 'not_found';
                        el.scrollIntoView({block:'center'});
                        el.focus();
                        var nativeSetter = Object.getOwnPropertyDescriptor(
                            window.HTMLInputElement.prototype, 'value') ||
                            Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value');
                        if (nativeSetter) nativeSetter.set.call(el, val);
                        el.dispatchEvent(new Event('input', {bubbles:true}));
                        el.dispatchEvent(new Event('change', {bubbles:true}));
                        return 'ok';
                    }
                """, [selector, value])

            if result == 'ok':
                print(f"  ✅ {label} (JS fill, attempt {attempt+1})")
                return True
            await page.wait_for_timeout(500)
        except Exception as e:
            print(f"  ❌ {label} JS fill error: {e}")
            return False
    print(f"  ❌ {label}: element not found after 10s of retries")
    return False


async def dismiss_image_modal(page):
    """Click Apply in the photo crop modal to accept the photo and close it."""
    # Primary: Apply button (data-et-name="apply") — accepts crop as-is
    for selector in [
        'button[data-et-name="apply"]',
        'button.btn--primary:has-text("Apply")',
    ]:
        try:
            btn = page.locator(selector).first
            if await btn.count() > 0 and await btn.is_visible():
                await btn.click()
                await page.wait_for_timeout(1000)
                print(f"  📷 Image modal dismissed (Apply)")
                return
        except Exception:
            pass
    # Fallback: force-click Apply by data-et-name even if not visible
    try:
        await page.evaluate("() => { var b = document.querySelector('button[data-et-name=\"apply\"]'); if(b) b.click(); }")
        await page.wait_for_timeout(1000)
        print(f"  📷 Image modal dismissed (Apply JS)")
    except Exception:
        pass


async def upload_covershot(page, photo_path):
    """Upload a photo via the hidden file input and dismiss the resulting image modal."""
    try:
        file_input = page.locator('input[name="img-file-input"]').first
        await file_input.set_input_files(photo_path)
        # Wait for the image modal to appear then dismiss it
        modal = page.locator('[data-test="modal-body"].listing-editor__image-modal').first
        try:
            await modal.wait_for(state="visible", timeout=10000)
            print(f"  📷 Image modal appeared — dismissing")
            await dismiss_image_modal(page)
            # Wait for modal to fully close
            await modal.wait_for(state="hidden", timeout=8000)
        except Exception:
            await page.wait_for_timeout(3000)
        print(f"  ✅ Cover photo uploaded: {photo_path.split('/')[-1][:36]}")
        return True
    except Exception as e:
        print(f"  ❌ Photo upload failed: {e}")
        return False


async def select_category_v2(page, dept, category, subcategory):
    """Open category dropdown, select dept then category using native Playwright clicks."""
    try:
        await dismiss_cookie_banner(page, "before category")
        cat_container = page.locator('.listing-editor__category-container').first
        await cat_container.click()
        await page.wait_for_timeout(1200)

        # Select department (e.g. "Kids") — appears as a.dropdown__link
        dept_loc = page.locator(f'a.dropdown__link:has-text("{dept}")').first
        await dept_loc.wait_for(state="visible", timeout=8000)
        await dept_loc.click()
        await page.wait_for_timeout(1200)
        print(f"  ✅ Department: {dept}")

        # Select category — appears as li after dept is chosen
        # Scroll the dropdown to make sure the item is reachable, then click
        cat_loc = page.locator(f'li:has-text("{category}"), a.dropdown__link:has-text("{category}")').first
        await cat_loc.wait_for(state="visible", timeout=8000)
        await cat_loc.scroll_into_view_if_needed()
        await cat_loc.click()
        await page.wait_for_timeout(1000)
        print(f"  ✅ Category: {category}")

        # Select subcategory if provided
        if subcategory:
            await dismiss_cookie_banner(page, "before subcategory")
            sub_container = page.locator('.listing-editor__subcategory-container').first
            if await sub_container.count() > 0:
                await sub_container.click()
                await page.wait_for_timeout(1000)
            sub_loc = page.locator(f'li:has-text("{subcategory}"), a.dropdown__link:has-text("{subcategory}")').first
            try:
                await sub_loc.wait_for(state="visible", timeout=5000)
                await sub_loc.scroll_into_view_if_needed()
                await sub_loc.click()
                await page.wait_for_timeout(800)
                print(f"  ✅ Subcategory: {subcategory}")
            except Exception:
                print(f"  ⚠️  Subcategory not found: {subcategory} (continuing)")

        return True
    except Exception as e:
        print(f"  ❌ Category selection failed: {e}")
        return False


async def click_cancel_and_save_draft(page):
    """Click Cancel button, then Save Draft in the popup."""
    try:
        await dismiss_cookie_banner(page, "before cancel")
        cancel_btn = page.locator('button:has-text("Cancel"), a:has-text("Cancel")').first
        if await cancel_btn.count() == 0:
            cancel_btn = page.locator('text="Cancel"').first
        await cancel_btn.wait_for(state="visible", timeout=10000)
        await cancel_btn.click()
        await page.wait_for_timeout(1500)
        print("  ✅ Cancel clicked")

        await dismiss_cookie_banner(page, "before save draft")
        save_btn = page.locator('button[data-et-name="save_draft"]').first
        if await save_btn.count() == 0:
            save_btn = page.locator('button:has-text("Save Draft")').first
        try:
            await save_btn.wait_for(state="visible", timeout=8000)
        except Exception:
            pass  # try force-clicking even if not visible
        await save_btn.click(force=True)
        await page.wait_for_timeout(2000)
        print("  ✅ Save Draft clicked!")

        url = page.url
        print(f"  URL after save: {url}")
        return True
    except Exception as e:
        print(f"  ❌ Cancel→Save Draft failed: {e}")
        return False


async def fill_listing(page, listing, idx):
    print(f"\n{'='*60}")
    print(f"Listing {idx+1}: {listing['title'][:55]}")
    print(f"{'='*60}")

    await page.goto("https://poshmark.com/create-listing", wait_until="networkidle", timeout=60000)
    await page.wait_for_timeout(2500)

    if "login" in page.url.lower():
        print("  ERROR: Not logged in!")
        return False

    await dismiss_cookie_banner(page, "page load")
    await page.wait_for_timeout(1500)  # let page stabilize after banner dismiss

    # Cover photo — upload before filling any fields
    if listing.get("photo"):
        await upload_covershot(page, listing["photo"])
        await page.wait_for_timeout(500)

    # Title — use JS fill to bypass actionability checks from banner overlay
    await dismiss_cookie_banner(page, "before title")
    title_ok = await js_fill(
        page,
        'input[placeholder="What are you selling? (required)"]',
        listing["title"],
        "Title"
    )
    if not title_ok:
        print(f"  ❌ Title failed — aborting listing")
        return False

    await page.wait_for_timeout(400)

    # Description — JS fill for same reason
    await dismiss_cookie_banner(page, "before description")
    desc_escaped = listing["description"].replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    await js_fill(page, 'textarea[placeholder="Describe it! (required)"]', desc_escaped, "Description")

    await page.wait_for_timeout(400)

    # Category (banner dismissed internally at each step)
    await select_category_v2(page, listing["dept"], listing["category"], listing.get("subcategory"))
    await page.wait_for_timeout(500)

    # Brand — JS fill then escape autocomplete
    await dismiss_cookie_banner(page, "before brand")
    brand_ok = await js_fill(page, 'input[placeholder="Enter the Brand/Designer"]', listing["brand"], "Brand")
    if brand_ok:
        await page.wait_for_timeout(1000)
        await dismiss_cookie_banner(page, "after brand autocomplete")
        try:
            await page.locator('input[placeholder="Enter the Brand/Designer"]').first.press("Escape")
        except Exception:
            pass

    await page.wait_for_timeout(400)

    # List price
    await dismiss_cookie_banner(page, "before price")
    price_ok = await js_fill(page, "input.listing-price-input", listing["list_price"], "List price")
    if not price_ok:
        await js_fill(page, 'input[data-vv-name="listingPrice"]', listing["list_price"], "List price (alt)")

    await page.wait_for_timeout(300)

    # Screenshot before save
    await dismiss_cookie_banner(page, "before screenshot")
    await page.screenshot(path=f"/home/cymolt/poshmark_listings/before_draft_{idx+1}.png")
    print(f"  📸 Screenshot: before_draft_{idx+1}.png")

    # Save Draft via Cancel popup
    success = await click_cancel_and_save_draft(page)

    await page.wait_for_timeout(1000)
    await page.screenshot(path=f"/home/cymolt/poshmark_listings/after_draft_{idx+1}.png")
    print(f"  📸 Screenshot: after_draft_{idx+1}.png")

    return success


async def main():
    from playwright.async_api import async_playwright

    with open(COOKIES_FILE) as f:
        cookies = [normalize_cookie(c) for c in json.load(f) if "poshmark" in c.get("domain","")]
    print(f"Loaded {len(cookies)} Poshmark cookies\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        await context.add_cookies(cookies)
        page = await context.new_page()

        results = []
        for i, listing in enumerate(LISTINGS):
            success = await fill_listing(page, listing, i)
            results.append({"title": listing["title"], "price": listing["list_price"], "success": success})
            await page.wait_for_timeout(2000)

        await browser.close()

    print("\n" + "="*60)
    print("FINAL RESULTS")
    print("="*60)
    for r in results:
        status = "✅ Draft saved" if r["success"] else "❌ Failed"
        print(f"  {status} — ${r['price']} — {r['title'][:55]}")

    return results

asyncio.run(main())
