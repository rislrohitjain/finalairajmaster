import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.join(current_dir, "backend")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import socket
import uvicorn

def is_port_free(port):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("0.0.0.0", port))
            return True
    except Exception:
        return False

def main():
    # Detect Hugging Face Spaces or explicit PORT env
    is_hf = bool(os.getenv("SPACE_ID")) or os.getenv("ENV_MODE") == "huggingface"
    env_port = os.getenv("PORT")
    if env_port:
        selected_port = int(env_port)
    elif is_hf:
        selected_port = 7860
    else:
        # Prioritize 3006 (user's preferred port), followed by 8000, 3007
        target_ports = [3006, 8000, 3007, 8080]
        selected_port = 3006
        for p in target_ports:
            if is_port_free(p):
                selected_port = p
                break

    print("=" * 80)
    print("RAJASTHAN ADMINISTRATIVE & GEOGRAPHIC MASTER (finalairajmaster)")
    print(f"Server starting on:     http://localhost:{selected_port}/")
    print(f"Jain Live Voice Mode:   http://localhost:{selected_port}/voice")
    print(f"Admin Dashboard:        http://localhost:{selected_port}/admin/dashboard")
    print(f"API Documentation:      http://localhost:{selected_port}/docs")
    print("=" * 80, flush=True)

    uvicorn.run("app.main:app", host="0.0.0.0", port=selected_port, log_level="info")

if __name__ == "__main__":
    main()
