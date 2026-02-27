"""
LinkedIn OAuth 2.0 Authorization Code Flow.

Gets a member access token for posting on LinkedIn via the REST API.
Saves LINKEDIN_ACCESS_TOKEN and LINKEDIN_PERSON_URN to .env.

Usage:
    .venv/Scripts/python.exe src/linkedin_oauth.py
"""
import http.server
import os
import threading
import urllib.parse
import webbrowser
from pathlib import Path

import httpx

_ROOT = Path(__file__).parent.parent
_ENV_FILE = _ROOT / ".env"

REDIRECT_URI = "http://localhost:8080/callback"
SCOPES = "w_member_social"
AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
ME_URL = "https://api.linkedin.com/v2/me"
USERINFO_URL = "https://api.linkedin.com/v2/userinfo"

# ── Shared callback state ────────────────────────────────────────────────────

_callback_code: str | None = None
_callback_error: str | None = None
_callback_event = threading.Event()


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        global _callback_code, _callback_error
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)

        if "code" in params:
            _callback_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<html><body style='font-family:sans-serif;text-align:center;padding:60px'>"
                b"<h2>Authorization successful!</h2>"
                b"<p>You can close this tab and return to the terminal.</p>"
                b"</body></html>"
            )
        else:
            _callback_error = params.get("error_description", params.get("error", ["unknown"]))[0]
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Authorization failed.")

        _callback_event.set()

    def log_message(self, *args):
        pass  # suppress noisy request logs


# ── .env helpers ─────────────────────────────────────────────────────────────

def _load_env() -> dict:
    result = {}
    if _ENV_FILE.exists():
        for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                result[k.strip()] = v.strip()
    return result


def _update_env(updates: dict):
    """Write key=value pairs into .env, replacing existing keys or appending."""
    text = _ENV_FILE.read_text(encoding="utf-8") if _ENV_FILE.exists() else ""
    lines = text.splitlines()
    replaced = set()

    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                new_lines.append(f"{key}={updates[key]}")
                replaced.add(key)
                continue
        new_lines.append(line)

    for key, value in updates.items():
        if key not in replaced:
            new_lines.append(f"{key}={value}")

    _ENV_FILE.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


# ── Main OAuth flow ───────────────────────────────────────────────────────────

def main():
    env = _load_env()
    client_id = env.get("LINKEDIN_CLIENT_ID", "")
    client_secret = env.get("LINKEDIN_CLIENT_SECRET", "")

    if not client_id or not client_secret:
        print("ERROR: Set LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET in .env first.")
        return

    # Build auth URL
    auth_url = AUTH_URL + "?" + urllib.parse.urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": "ai_employee_oauth",
    })

    # Start local callback server — serve_forever so we don't miss the request
    server = http.server.HTTPServer(("localhost", 8080), _CallbackHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    print("=" * 60)
    print("  LinkedIn OAuth — Authorization")
    print("=" * 60)
    print()
    print("Opening your browser to authorize the app...")
    print("If it doesn't open automatically, visit:")
    print(f"\n  {auth_url}\n")
    webbrowser.open(auth_url)
    print("Waiting for you to authorize in the browser (5-minute timeout)...")

    _callback_event.wait(timeout=300)
    server.shutdown()

    if _callback_error:
        print(f"\nAuthorization failed: {_callback_error}")
        return

    if not _callback_code:
        print("\nTimed out waiting for authorization.")
        return

    print("Authorization code received. Exchanging for access token...")

    # Exchange code for access token
    resp = httpx.post(TOKEN_URL, data={
        "grant_type": "authorization_code",
        "code": _callback_code,
        "redirect_uri": REDIRECT_URI,
        "client_id": client_id,
        "client_secret": client_secret,
    })

    if resp.status_code != 200:
        print(f"Token exchange failed ({resp.status_code}): {resp.text}")
        return

    token_data = resp.json()
    access_token = token_data["access_token"]
    expires_days = token_data.get("expires_in", 5184000) // 86400
    print(f"Access token received (valid for ~{expires_days} days)")

    # Get person URN — try /v2/me first, fall back to /v2/userinfo
    headers = {"Authorization": f"Bearer {access_token}", "X-Restli-Protocol-Version": "2.0.0"}
    person_urn = ""

    me_resp = httpx.get(ME_URL, headers=headers)
    if me_resp.status_code == 200:
        me_data = me_resp.json()
        person_id = me_data.get("id", "")
        person_urn = f"urn:li:person:{person_id}"
        first = me_data.get("localizedFirstName", "")
        last = me_data.get("localizedLastName", "")
        print(f"Name        : {first} {last}".strip())
        print(f"Person URN  : {person_urn}")
    else:
        # Fall back to /v2/userinfo (requires openid scope — may not be available)
        ui_resp = httpx.get(USERINFO_URL, headers=headers)
        if ui_resp.status_code == 200:
            sub = ui_resp.json().get("sub", "")
            person_urn = f"urn:li:person:{sub}"
            print(f"Person URN  : {person_urn}")
        else:
            print(f"Warning: could not retrieve person URN "
                  f"(/v2/me: {me_resp.status_code}, /v2/userinfo: {ui_resp.status_code})")
            print("You may need to add 'Sign In with LinkedIn using OpenID Connect' "
                  "to your app's Products tab.")

    # Save to .env
    _update_env({
        "LINKEDIN_ACCESS_TOKEN": access_token,
        "LINKEDIN_PERSON_URN": person_urn,
    })

    print()
    print("Saved to .env:")
    print("  LINKEDIN_ACCESS_TOKEN = [token saved]")
    print(f"  LINKEDIN_PERSON_URN   = {person_urn}")
    print()
    print("Run the social media manager to post:")
    print("  .venv/Scripts/python.exe src/social_media_manager.py "
          "--vault AI_Employee_Vault "
          "--post linkedin_post_20260223_ai_employee_hackathon0.md")


if __name__ == "__main__":
    main()
