"""
Gmail Auth — one-time interactive OAuth2 setup for gmail.send scope.

Run this once to authorise the AI Employee to send email on your behalf.
A token file is saved so subsequent runs (via the MCP server) are silent.

Usage:
    python src/gmail_auth.py
    python src/gmail_auth.py --credentials path/to/credentials.json
    python src/gmail_auth.py --token-path path/to/.gmail_send_token.json
"""
import argparse
import sys
from pathlib import Path

# Allow importing gmail_sender from this script's location
sys.path.insert(0, str(Path(__file__).parent))


def main():
    parser = argparse.ArgumentParser(
        description="One-time OAuth2 setup for Gmail send access."
    )
    parser.add_argument(
        "--credentials",
        help="Path to gmail_credentials.json (overrides GMAIL_CREDENTIALS_PATH env var)",
    )
    parser.add_argument(
        "--token-path",
        help="Where to save the token (overrides GMAIL_SEND_TOKEN_PATH env var)",
    )
    args = parser.parse_args()

    import os
    if args.credentials:
        os.environ["GMAIL_CREDENTIALS_PATH"] = args.credentials
    if args.token_path:
        os.environ["GMAIL_SEND_TOKEN_PATH"] = args.token_path

    from gmail_sender import _send_token_path, get_gmail_service

    token_file = _send_token_path()
    print("=" * 60)
    print("Gmail Send — OAuth2 Setup")
    print("=" * 60)
    print()
    print("Opening browser for OAuth2 consent...")
    print("Scope: gmail.send  (cannot read your mail, only send)")
    print()
    print(f"Token will be saved to: {token_file}")
    print()

    try:
        get_gmail_service()
        print("=" * 60)
        if token_file.exists():
            print("  SUCCESS! Token saved.")
            print(f"  Token path: {token_file}")
            print()
            print("  The MCP server can now send emails via Gmail.")
            print("  You do NOT need to run this script again unless you")
            print("  revoke access or delete the token file.")
            print("=" * 60)
            print()
            print("  Add your Gmail address to .env:")
            print("  GMAIL_FROM_EMAIL=you@gmail.com")
        else:
            print("  ERROR: Auth completed but token file was not saved.")
            print(f"  Expected: {token_file}")
            sys.exit(1)
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
