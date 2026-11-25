import asyncio
from playwright.async_api import async_playwright

async def verify_admin_ui():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1440, "height": 1000})
        page = await context.new_page()

        print("Navigating to http://localhost:3006/admin/login...")
        await page.goto("http://localhost:3006/admin/login", wait_until="networkidle")
        await page.screenshot(path="backend/playwright_screenshots/admin_login_page.png")

        # Fill in credentials
        await page.fill('input[type="text"], input[name="username"]', "8946919241")
        await page.fill('input[type="password"]', "123456")
        await page.click('button[type="submit"]')

        print("Waiting for dashboard navigation...")
        await page.wait_for_url("**/admin/dashboard", timeout=10000)
        await page.wait_for_timeout(2000)

        # Take full screenshot of LLM & AI Control tab
        await page.screenshot(path="backend/playwright_screenshots/admin_dashboard_rag.png", full_page=True)
        print("Captured backend/playwright_screenshots/admin_dashboard_rag.png")

        # Check if RAG elements exist
        rag_heading = await page.query_selector('text=RAG Knowledge Retrieval & Live Web Search Fallback')
        print("RAG Section present:", rag_heading is not None)

        # Also navigate to public chat and test a live web fallback query
        print("Navigating to public chat...")
        await page.goto("http://localhost:3006/", wait_until="networkidle")
        await page.wait_for_timeout(1000)

        # Check welcome greeting
        body_text = await page.inner_text("body")
        print("Contains 'Welcome here chat with Jain's only':", "Welcome here chat with Jain's only" in body_text)

        # Send query
        chat_input = await page.query_selector('input[placeholder*="Ask any question"]')
        if chat_input:
            await chat_input.fill("Who is the current Chief Minister of Rajasthan?")
            send_btn = await page.query_selector('button:has-text("Send"), button[type="submit"]')
            if send_btn:
                await send_btn.click()
            else:
                await chat_input.press("Enter")

            print("Waiting for chat response...")
            await page.wait_for_timeout(5000)
            await page.screenshot(path="backend/playwright_screenshots/chat_web_search_response.png")
            print("Captured backend/playwright_screenshots/chat_web_search_response.png")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(verify_admin_ui())
