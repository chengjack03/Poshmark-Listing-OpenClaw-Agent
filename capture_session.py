"""
Poshmark Session Capture
Opens https://poshmark.com/login in a headed Chromium browser.
Log in manually, then press Enter in this terminal to save cookies to session.json.
"""

import asyncio
import json
from playwright.async_api import async_playwright

SESSION_FILE = "/home/cymolt/poshmark_listings/session.json"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        print("Opening Poshmark login page...")
        await page.goto("https://poshmark.com/login")
        trigger = "/home/cymolt/poshmark_listings/.save_session"
        print(f"Browser open. Log in manually in the VNC window.")
        print(f"When done, create this file to save the session:")
        print(f"  touch {trigger}")

        import os, time
        while not os.path.exists(trigger):
            time.sleep(2)
        os.remove(trigger)

        cookies = await context.cookies()
        with open(SESSION_FILE, "w") as f:
            json.dump(cookies, f, indent=2)

        print(f"Session saved to {SESSION_FILE}")
        await browser.close()

asyncio.run(main())
