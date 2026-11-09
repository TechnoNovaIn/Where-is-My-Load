"""Prepare .env before start: generate SESSION_SECRET if missing, check upstream credentials.
Stdlib only, so it runs before or after dependencies are installed."""
import re
import secrets
import sys
from pathlib import Path

env = Path(__file__).resolve().parent.parent / ".env"
text = env.read_text(encoding="utf-8")


def get(key: str) -> str:
    m = re.search(rf"^{key}=(.*)$", text, flags=re.M)
    return m.group(1).strip() if m else ""


def put(key: str, value: str) -> None:
    global text
    if re.search(rf"^{key}=", text, flags=re.M):
        text = re.sub(rf"^{key}=.*$", f"{key}={value}", text, flags=re.M)
    else:
        text = text.rstrip("\n") + f"\n{key}={value}\n"


changed = False
if len(get("SESSION_SECRET")) < 32:
    put("SESSION_SECRET", secrets.token_urlsafe(48))
    changed = True
    print("Generated SESSION_SECRET in .env")
if changed:
    env.write_text(text, encoding="utf-8")

missing = [k for k in ("UPSTREAM_USERNAME", "UPSTREAM_PASSWORD") if not get(k)]
if missing:
    print(f"Fill {', '.join(missing)} in {env} and run again.")
    sys.exit(1)
if not get("OLA_MAPS_API_KEY"):
    print("Note: OLA_MAPS_API_KEY is empty; the map will show as unavailable until you add it.")
if get("COOKIE_SECURE").lower() != "false":
    print("Note: COOKIE_SECURE is not false. Sign-in only works over HTTPS; set COOKIE_SECURE=false for http://localhost testing.")
