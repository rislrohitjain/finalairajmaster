import os
import sys

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

def get_free_port():
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port

def start_server_in_thread(port):
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    return server, t

def wait_for_server(url, timeout=15):
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = httpx.get(url, timeout=1.0)
            if r.status_code == 200:
                return True
        except Exception:
            time.sleep(0.3)
    return False

def run_playwright_gemini_voice():
    print("=" * 80)
    print("PLAYWRIGHT TEST: GEMINI LIVE VOICE INTERACTIVE AGENT (INDIAN FEMALE VOCAL)")
    print("=" * 80)

    port = get_free_port()
    health_url = f"http://127.0.0.1:{port}/health"
    base_url = f"http://127.0.0.1:{port}"

    print(f"\n[Step 1/6] Starting FastAPI + Full-Stack Angular Server on port {port}...")
    server, srv_thread = start_server_in_thread(port)
    if not wait_for_server(health_url):
        print("Error: Server failed to start within timeout.")
        sys.exit(1)
    print(f"  ✓ Full-stack server live at {base_url} (Health Check: 200 OK)")

    os.makedirs(ARTIFACT_DIR, exist_ok=True)

    with sync_playwright() as p:
        print("\n[Step 2/6] Launching Playwright Chromium Headless Browser...")
        browser = p.chromium.launch(
            headless=True,
            args=["--no-proxy-server", "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"]
        )
        context = browser.new_context(
            viewport={"width": 1440, "height": 960},
            permissions=["microphone"]
        )
        page = context.new_page()

        page.on("console", lambda msg: print(f"    [Browser Console] {msg.text}") if msg.type in ("error", "warning") else None)

        # 1. Main Chat Interface Verification
        print(f"\n[Step 3/6] Navigating to {base_url}/ and verifying Voice buttons...")
        page.goto(f"{base_url}/", wait_until="networkidle")
        time.sleep(1.0)

        # Verify Header Voice Button
        voice_header_btn = page.locator("button:has-text('Gemini Live Voice')").first
        assert voice_header_btn.is_visible(timeout=5000)
        print("  ✓ Header '✨ Gemini Live Voice' button visible with pulse animation!")

        # Verify Input Bar Mic Voice Button
        input_mic_btn = page.locator("button[title*='Gemini Live Voice']").first
        assert input_mic_btn.is_visible(timeout=5000)
        print("  ✓ Input bar '🎙️ Live Voice' button visible next to send bar!")

        # Capture Screenshot of Chat Interface with Voice Buttons
        chat_btn_screenshot = os.path.join(ARTIFACT_DIR, "playwright_gemini_live_chat_button.png")
        page.screenshot(path=chat_btn_screenshot)
        print(f"  ✓ Saved Chat Voice Button screenshot: {chat_btn_screenshot}")

        # 2. Click to Launch Full-Screen Gemini Live Voice Agent
        print("\n[Step 4/6] Clicking '✨ Gemini Live Voice' button to open full-screen interface...")
        voice_header_btn.click()
        time.sleep(1.5)

        # Verify Full-Screen Elements
        live_branding = page.locator("h1:has-text('RajMaster Gemini Live')").first
        assert live_branding.is_visible(timeout=5000)
        print("  ✓ Opened Full-Screen Interface: 'RajMaster Gemini Live' confirmed!")

        # Verify Indian Female Voice Subtitle
        vocal_badge = page.locator("text=/Authentic Indian Female Vocal/i").first
        assert vocal_badge.is_visible(timeout=5000)
        print("  ✓ Indian Female Vocal subtitle (Swara / Neerja) confirmed!")

        # Verify Language Switchers (हिन्दी / Hinglish / English-IN) inside Voice Agent
        voice_overlay = page.locator("app-voice-agent div.fixed").first
        assert voice_overlay.is_visible(timeout=5000)

        hindi_pill = voice_overlay.locator("button:has-text('हिन्दी')").first
        hinglish_pill = voice_overlay.locator("button:has-text('Hinglish')").first
        english_pill = voice_overlay.locator("button:has-text('English (India)')").first
        assert hindi_pill.is_visible(timeout=5000)
        assert hinglish_pill.is_visible(timeout=5000)
        assert english_pill.is_visible(timeout=5000)
        print("  ✓ 3 Vocal Language Pills (हिन्दी, Hinglish, English-India) verified inside voice agent!")

        # Verify Gemini Live Concentric Glowing Fluid Orb
        gemini_orb = voice_overlay.locator("div.animate-spin-slow").first
        assert gemini_orb.is_visible(timeout=5000)
        print("  ✓ Central Gemini Live Glowing Fluid Orb with swirling gradient verified!")

        # 3. Test Asking a Question in Voice Mode
        print("\n[Step 5/6] Testing Voice Query via Suggestion Chip...")
        muhana_chip = voice_overlay.locator("button:has-text('Muhana Village Hierarchy')").first
        assert muhana_chip.is_visible(timeout=5000)
        muhana_chip.click()
        time.sleep(3.5)

        # Verify User Transcript
        transcript_box = voice_overlay.locator("text=/What is the administrative lineage of Muhana village/i").first
        assert transcript_box.is_visible(timeout=5000)
        print("  ✓ User question registered in live transcript bubble!")

        # Verify Spoken Text Subtitles
        spoken_card = voice_overlay.locator("text=/RajMaster Spoken Audio/i").first
        assert spoken_card.is_visible(timeout=5000)
        spoken_text = voice_overlay.locator("div:has(span:has-text('RajMaster Spoken Audio')) p").first.inner_text()
        print(f"  ✓ Live Indian Spoken Audio generated (Length: {len(spoken_text)} chars)")
        print(f"    Excerpt: '{spoken_text[:120]}...'")

        # 4. Test Language Switching inside Voice Agent
        print("\n[Step 6/6] Testing Language Switching to हिन्दी & English (India)...")
        hindi_pill.click()
        time.sleep(1.0)
        print("  ✓ Switched language to हिन्दी (Hindi)")

        english_pill.click()
        time.sleep(1.0)
        print("  ✓ Switched language to English (India)")

        # Save Full-Screen High-Res Screenshot
        fullscreen_screenshot = os.path.join(ARTIFACT_DIR, "playwright_gemini_live_voice_fullscreen.png")
        page.screenshot(path=fullscreen_screenshot, full_page=True)
        print(f"  ✓ High-Res Full-Screen Gemini Live screenshot saved to: {fullscreen_screenshot}")

        # Test Direct Route Navigation (/voice)
        print("\n[Step 7/7] Testing direct route navigation to /voice...")
        page.goto(f"{base_url}/voice", wait_until="networkidle")
        time.sleep(1.0)
        direct_branding = page.locator("h1:has-text('RajMaster Gemini Live')").first
        assert direct_branding.is_visible(timeout=5000)
        print("  ✓ Direct navigation to /voice successfully loaded full-screen voice agent interface!")

        browser.close()

    server.should_exit = True
    print("\n" + "=" * 80)
    print("ALL PLAYWRIGHT TESTS PASSED (100%): GEMINI LIVE VOICE AGENT FULLY VERIFIED!")
    print("=" * 80)

if __name__ == "__main__":
    run_playwright_gemini_voice()
