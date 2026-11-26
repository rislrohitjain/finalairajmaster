import os
import sys

# Ensure backend directory is in python path
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.join(current_dir, "backend")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

# If this file was imported as 'app' by Vercel or Python's module loader,
# remove 'app' from sys.modules temporarily so Python resolves the 'app' package
# inside the 'backend' directory instead of shadowing it with this file (app.py).
_this_module = sys.modules.get("app")
if _this_module is not None and not hasattr(_this_module, "__path__"):
    del sys.modules["app"]

try:
    import app.main
    fastapi_app = app.main.app
    # Export as 'app' for ASGI/WSGI servers (like Vercel and Uvicorn)
    app = fastapi_app
finally:
    if _this_module is not None and not hasattr(_this_module, "__path__"):
        _this_module.app = app
        sys.modules["app"] = _this_module

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 7860))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, log_level="info")
