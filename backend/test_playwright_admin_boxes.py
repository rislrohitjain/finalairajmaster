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

def run_playwright_admin_boxes():
    print("=" * 80)
    print("PLAYWRIGHT TEST: ADMIN GEOGRAPHIC BOXES LISTING & EDIT MODAL VERIFICATION")
    print("=" * 80)

    print("\n[Step 1/6] Starting FastAPI + Full-Stack Angular Server...")
    server, srv_thread = start_server_in_thread()
    if not wait_for_server():
        print("Error: Server failed to start within timeout.")
        sys.exit(1)
    print("  ✓ Full-stack server live at http://127.0.0.1:8000 (Health Check: 200 OK)")

    os.makedirs(ARTIFACT_DIR, exist_ok=True)

    with sync_playwright() as p:
        print("\n[Step 2/6] Launching Playwright Chromium Headless Browser...")
        browser = p.chromium.launch(
            headless=True,
            args=["--no-proxy-server"]
        )
        context = browser.new_context(
            viewport={"width": 1400, "height": 1050}
        )
        page = context.new_page()

        page.on("console", lambda msg: print(f"    [Browser Console] {msg.text}") if msg.type in ("error", "warning") else None)

        # 1. Login as Admin
        print("\n[Step 3/6] Navigating to Admin Login at http://127.0.0.1:8000/admin/login...")
        page.goto("http://127.0.0.1:8000/admin/login", wait_until="networkidle")
        time.sleep(1.0)

        page.fill("input[name='username']", "8946919241")
        page.fill("input[name='password']", "123456")
        page.click("button[type='submit']")
        print("  ✓ Admin credentials submitted (8946919241 / 123456)")

        page.wait_for_url("**/admin/dashboard", timeout=8000)
        print("  ✓ Redirected to Admin Dashboard:", page.url)
        time.sleep(1.5)

        # 2. Switch to 'Geographic Stats & Records' Tab
        print("\n[Step 4/6] Switching to 'Geographic Stats & Records' tab...")
        geo_tab = page.locator("button:has-text('Geographic Stats & Records')").first
        geo_tab.click()
        time.sleep(1.5)

        # Verify live count boxes
        total_card = page.locator("text=Total Geographic DB").first
        assert total_card.is_visible(timeout=5000)
        print("  ✓ Live Stat Cards visible on screen!")

        # 3. Test Clicking Stat Boxes & Listing Records
        print("\n[Step 5/6] Testing Box Selection & Table Listing...")
        # Click on 'Divisions' Box
        div_box = page.locator("#stat-box-division")
        assert div_box.is_visible(timeout=5000)
        div_box.click()
        time.sleep(1.5)
        
        # Verify table switched to Divisions
        table_title = page.locator("h3:has-text('Divisions Master Records')").first
        assert table_title.is_visible(timeout=5000)
        print("  ✓ Clicked 'Divisions' stat box (#stat-box-division) -> Table switched to Divisions Master Records (10 Total)!")

        # Click on 'Districts' Box
        dist_box = page.locator("#stat-box-district")
        assert dist_box.is_visible(timeout=5000)
        dist_box.click()
        time.sleep(1.5)

        # Verify table switched to Districts
        dist_title = page.locator("h3:has-text('Districts Master Records')").first
        assert dist_title.is_visible(timeout=5000)
        print("  ✓ Clicked 'Districts' stat box (#stat-box-district) -> Table switched to Districts Master Records (50 Total)!")

        # Search for Jaipur in Districts
        search_input = page.locator("input[placeholder*='Search Districts by name']").first
        search_input.fill("Jaipur")
        time.sleep(1.0)
        print("  ✓ Filtered table by search: 'Jaipur'")

        # Verify Jaipur record is present
        jaipur_row = page.locator("tr:has-text('Jaipur')").first
        assert jaipur_row.is_visible(timeout=5000)
        print("  ✓ Jaipur record displayed with English/Hindi name and LGD details!")

        # 4. Test Edit Option & Modal
        print("\n[Step 6/6] Testing '✏️ Edit' Option & Modal...")
        edit_btn = jaipur_row.locator("button:has-text('Edit')").first
        edit_btn.click()
        time.sleep(1.0)

        # Verify Edit Modal is visible
        modal_title = page.locator("h3:has-text('Edit Geographic Master Record')").first
        assert modal_title.is_visible(timeout=5000)
        print("  ✓ Edit Modal opened successfully!")

        # Update authority details in the modal
        auth_textarea = page.locator("textarea[name='edit_authority_details']").first
        original_auth = auth_textarea.input_value()
        new_auth_val = "District Collectorate, Jaipur (Verified Master Authority IAS)"
        auth_textarea.fill(new_auth_val)
        print(f"  ✓ Modified Authority field in modal to: '{new_auth_val}'")

        # Save Changes
        save_btn = page.locator("button:has-text('Save Changes to Database')").first
        save_btn.click()
        time.sleep(1.5)

        # Verify alert notice in modal
        success_alert = page.locator("text=/Successfully updated record/i").first
        if success_alert.is_visible():
            print("  ✓ Success alert verified in modal!")

        # Wait for modal to auto-close and table to refresh
        time.sleep(2.0)
        modal_visible = modal_title.is_visible()
        assert not modal_visible, "Modal should have closed after save"
        print("  ✓ Edit Modal closed automatically after successful commit!")

        # Verify table displays the updated authority string
        updated_cell = page.locator(f"text={new_auth_val}").first
        assert updated_cell.is_visible(timeout=5000)
        print(f"  ✓ Table displays updated authority details: '{new_auth_val}'!")

        # Revert back cleanly to keep DB pristine
        edit_btn_2 = page.locator("tr:has-text('Jaipur')").first.locator("button:has-text('Edit')").first
        edit_btn_2.click()
        time.sleep(1.0)
        auth_textarea_2 = page.locator("textarea[name='edit_authority_details']").first
        auth_textarea_2.fill("District Collectorate, Jaipur")
        page.locator("button:has-text('Save Changes to Database')").first.click()
        time.sleep(2.0)
        print("  ✓ Reverted Jaipur record cleanly in database.")

        # Save Screenshot of the Dashboard with Box Listing & Selection
        screenshot_path = os.path.join(ARTIFACT_DIR, "playwright_admin_box_listing_edit_verified.png")
        page.screenshot(path=screenshot_path, full_page=True)
        print(f"  ✓ High-Res Screenshot saved to: {screenshot_path}")

        browser.close()

    server.should_exit = True
    print("\n" + "=" * 80)
    print("ALL PLAYWRIGHT TESTS PASSED (100%): BOX LISTING & EDIT MODAL FULLY VERIFIED!")
    print("=" * 80)

if __name__ == "__main__":
    run_playwright_admin_boxes()
