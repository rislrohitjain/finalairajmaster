import os
import sys
os.environ["NO_PROXY"] = "127.0.0.1,localhost"
os.environ["no_proxy"] = "127.0.0.1,localhost"
import time
import threading
import uvicorn
from playwright.sync_api import sync_playwright

from app.main import app
ARTIFACT_DIR = r"C:\Users\rislr\.gemini\antigravity\brain\e62625ff-b72d-4de2-a97b-bc834b025436"

config = uvicorn.Config(app, host="127.0.0.1", port=8001, log_level="error")
server = uvicorn.Server(config)
t = threading.Thread(target=server.run, daemon=True)
t.start()
time.sleep(2.0)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-proxy-server"])
    page = browser.new_page(viewport={"width": 1400, "height": 1050})

    page.goto("http://127.0.0.1:8001/admin/login", wait_until="networkidle")
    page.fill("input[name='username']", "8946919241")
    page.fill("input[name='password']", "123456")
    page.click("button[type='submit']")
    page.wait_for_url("**/admin/dashboard", timeout=8000)
    time.sleep(1.0)

    # Click Geographic Stats & Records
    page.locator("button:has-text('Geographic Stats & Records')").first.click()
    time.sleep(1.0)

    # Search Jaipur
    page.locator("input[placeholder*='Search Districts by name']").first.fill("Jaipur")
    time.sleep(1.0)

    # Click Edit on Jaipur row
    page.locator("tr:has-text('Jaipur')").first.locator("button:has-text('Edit')").first.click()
    time.sleep(1.0)

    # Save Screenshot with modal open
    modal_path = os.path.join(ARTIFACT_DIR, "playwright_admin_edit_modal_verified.png")
    page.screenshot(path=modal_path, full_page=True)
    print("Modal Screenshot saved:", modal_path)
    browser.close()

server.should_exit = True
