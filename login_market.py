"""
login_market.py — One-time interactive login for the "market research" LinkedIn account.

Uses patchright (stealth Playwright fork) + real Google Chrome to bypass
Google's "browser not secure" block during OAuth.

Opens a visible browser with a persistent profile at linkedin_session_market/.
Sign in manually via Google OAuth, then press Enter in the terminal to save.
"""
import asyncio
import os
import sys

# patchright — stealth fork of playwright, avoids Google bot-detection
from patchright.async_api import async_playwright

from config import CHROME_PATH, LINKEDIN_ACCOUNT_EMAIL, SESSION_DIR


async def main():
    os.makedirs(SESSION_DIR, exist_ok=True)
    print(f"Session dir: {SESSION_DIR}")
    print()
    print("1. Browser will open at LinkedIn login page.")
    hint = LINKEDIN_ACCOUNT_EMAIL or "your market-research Google account"
    print(f'2. Click "Sign in with Google" → choose {hint}.')
    print("3. Complete Google OAuth flow.")
    print("4. Once you see your LinkedIn feed — scroll around for 1-2 min")
    print("   (opens a few posts / jobs to warm up the account).")
    print("5. Come back here and press Enter to save the session.\n")

    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(
            user_data_dir=SESSION_DIR,
            headless=False,
            executable_path=CHROME_PATH,
            viewport={"width": 1280, "height": 900},
            args=[
                "--disable-blink-features=AutomationControlled",
            ],
            ignore_default_args=["--enable-automation"],
        )

        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        try:
            await page.goto(
                "https://www.linkedin.com/login", wait_until="domcontentloaded"
            )
        except Exception as exc:
            print(f"⚠️  Could not open LinkedIn login: {exc}")
            print("The browser is still open — navigate to linkedin.com/login manually.")

        # ── Wait for user ────────────────────────────────────────────
        await asyncio.get_event_loop().run_in_executor(
            None,
            input,
            ">>> Press Enter after you reach the LinkedIn feed... ",
        )

        # ── Check result ────────────────────────────────────────────
        # After user presses Enter the page may have navigated anywhere.
        # We just read whatever the active page shows.
        try:
            # Grab URL from whichever page is still alive
            live_pages = ctx.pages
            url = live_pages[0].url if live_pages else "unknown"
        except Exception:
            url = "unknown (browser may have been closed)"

        print(f"\nFinal URL: {url}")

        if "/feed" in url or "/in/" in url:
            print("✅ Logged in! Persistent session saved.")
        elif url == "unknown" or "closed" in url:
            print("⚠️  Browser was closed before saving — cookies may still be OK.")
            print("   Re-run this script; if LinkedIn opens already logged in, you're set.")
        else:
            print("⚠️  URL doesn't look like the feed — login may have failed.")
            print(f"   Got: {url}")

        # ── Close context to flush cookies to disk ──────────────────
        try:
            await ctx.close()
        except Exception:
            pass  # already closed by user

    print(f"\n📁 Profile saved to: {SESSION_DIR}")
    print("   Use this path in your scraper's user_data_dir to reuse the session.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(0)
