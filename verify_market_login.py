import asyncio
import os
from patchright.async_api import async_playwright

from config import CHROME_PATH, SESSION_DIR

async def main():
    print(f"Verifying session in: {SESSION_DIR}")
    async with async_playwright() as pw:
        # Launch using the persistent context we just created
        ctx = await pw.chromium.launch_persistent_context(
            user_data_dir=SESSION_DIR,
            headless=True, # Verify in headless mode now
            executable_path=CHROME_PATH,
        )
        page = await ctx.new_page()
        
        try:
            print("Navigating to LinkedIn feed...")
            await page.goto("https://www.linkedin.com/feed/", wait_until="networkidle", timeout=20000)
            url = page.url
            print(f"Final URL: {url}")
            
            if "feed" in url or "/in/" in url:
                print("✅ VERIFICATION SUCCESS: Session is valid and persists.")
            else:
                print("❌ VERIFICATION FAILED: Did not reach feed. Might need to re-login.")
                # Maybe take a screenshot to see what's wrong (e.g. login page)
                await page.screenshot(path="verification_failure.png")
        except Exception as e:
            print(f"❌ Error during verification: {e}")
        finally:
            await ctx.close()

if __name__ == "__main__":
    asyncio.run(main())
