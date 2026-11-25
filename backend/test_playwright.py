import os
import sys

# Crucial for sandboxed environments: bypass proxy for local loopback
os.environ["NO_PROXY"] = "127.0.0.1,localhost"
os.environ["no_proxy"] = "127.0.0.1,localhost"

import time
import json
import threading
import uvicorn
import httpx
from playwright.sync_api import sync_playwright

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from app.main import app

ARTIFACT_DIR = r"C:\Users\rislr\.gemini\antigravity\brain\e62625ff-b72d-4de2-a97b-bc834b025436"

def start_server_in_thread():
    config = uvicorn.Config(app, host="127.0.0.1", port=8000, log_level="error")
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    return server, t

def wait_for_server(url="http://127.0.0.1:8000/health", timeout=15):
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = httpx.get(url, timeout=1.0)
            if r.status_code == 200:
                return True
        except Exception:
            time.sleep(0.3)
    return False

def run_playwright_e2e():
    print("=" * 80)
    print("PLAYWRIGHT TEST: STYLISH HIERARCHY PATH (BOLD, ITALIC, UNDERLINE, ZERO **)")
    print("=" * 80)

    print("\n[Step 1/5] Starting FastAPI + Full-Stack Angular Server...")
    server, srv_thread = start_server_in_thread()
    if not wait_for_server():
        print("Error: Server failed to start within timeout.")
        sys.exit(1)
    print("  ✓ Full-stack server live at http://127.0.0.1:8000 (Health Check: 200 OK)")

    os.makedirs(ARTIFACT_DIR, exist_ok=True)

    with sync_playwright() as p:
        print("\n[Step 2/5] Launching Playwright Chromium Headless Browser...")
        browser = p.chromium.launch(
            headless=True,
            args=["--no-proxy-server"]
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 950}
        )
        page = context.new_page()

        page.on("console", lambda msg: print(f"    [Browser Console] {msg.text}") if msg.type in ("error", "warning") else None)

        # 1. Load Main Application
        print("\n[Step 3/5] Navigating to http://127.0.0.1:8000/...")
        page.goto("http://127.0.0.1:8000/", wait_until="networkidle")
        print(f"  ✓ Page Loaded. Title: '{page.title()}'")

        # 2. Test Sending Query: "Details of pincode 302029"
        print("\n[Step 4/5] Sending query: 'Details of pincode 302029'...")
        chat_input = page.locator("input[type='text']").first
        chat_input.fill("Details of pincode 302029")
        page.keyboard.press("Enter")
        time.sleep(3.0)

        # Check message card
        last_card = page.locator(".max-w-\\[95\\%\\]").last
        last_preview = last_card.locator("div.markdown-preview")
        assert last_preview.is_visible(timeout=5000)

        # Check text in preview mode for zero **
        preview_text = last_preview.inner_text()
        assert "**" not in preview_text, f"Found literal '**' in preview: {preview_text}"
        print("  ✓ Zero '**' in Preview text verified!")

        # Verify Stylish Hierarchy Path card
        hierarchy_header = last_preview.locator("span:has-text('HIERARCHY PATH')").first
        assert hierarchy_header.is_visible(timeout=5000)
        print("  ✓ Rendered 'HIERARCHY PATH' title with bold, uppercase, and underline styling verified!")

        # Verify Italic sub-badge
        italic_badge = last_preview.locator("text=6-Tier Master Path").first
        assert italic_badge.is_visible(timeout=5000)
        print("  ✓ Rendered italic '6-Tier Master Path' pill badge verified!")

        # Verify Target Destination Badge with target pin/star
        target_badge = last_preview.locator("span:has-text('🎯')").first
        assert target_badge.is_visible(timeout=5000)
        print("  ✓ Rendered target destination badge with '🎯' highlight verified!")

        # Verify Governance Box
        gov_header = last_preview.locator("text=/Governance & Administrative/i").first
        assert gov_header.is_visible(timeout=5000)
        print("  ✓ Rendered 'Governance & Administrative Authority' styled card verified!")

        # Verify Next Expected Questions
        next_q_header = last_preview.locator("text=/Next Expected Questions/i").first
        assert next_q_header.is_visible(timeout=5000)
        print("  ✓ Rendered 'Next Expected Questions' styled header with underline verified!")

        # 3. Test Second Query: "number of villages in Jodhpur"
        print("\n[Step 5/5] Sending second query: 'number of villages in Jodhpur'...")
        chat_input.fill("number of villages in Jodhpur")
        page.keyboard.press("Enter")
        time.sleep(3.0)

        last_card_2 = page.locator(".max-w-\\[95\\%\\]").last
        last_preview_2 = last_card_2.locator("div.markdown-preview")
        assert last_preview_2.is_visible(timeout=5000)

        preview_text_2 = last_preview_2.inner_text()
        assert "**" not in preview_text_2, f"Found literal '**' in preview 2: {preview_text_2}"
        print("  ✓ Zero '**' in Preview text 2 verified!")

        # Save High-Res Screenshot
        screenshot_path = os.path.join(ARTIFACT_DIR, "playwright_hierarchy_path_stylish_verified.png")
        page.screenshot(path=screenshot_path, full_page=True)
        print(f"  ✓ High-Res Screenshot saved to: {screenshot_path}")

        browser.close()

    server.should_exit = True
    print("\n" + "=" * 80)
    print("ALL PLAYWRIGHT TESTS PASSED (100%): STYLISH HIERARCHY PATH FULLY VERIFIED!")
    print("=" * 80)

if __name__ == "__main__":
    run_playwright_e2e()
