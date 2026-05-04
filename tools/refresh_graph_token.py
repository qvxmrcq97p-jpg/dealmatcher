#!/usr/bin/env python3
"""
Refresh the Microsoft Graph token cache for the cloud scraper.

Run this on your Mac (NOT Railway) when:
- The cached refresh token has expired (~90 days)
- You see "Graph auth failed: AADSTS70008" in Railway logs
- You want to re-grant Mail.Read after a permission change

What it does:
1. Runs MSAL device flow on your Mac (you sign in via browser)
2. Saves the new token cache to ~/Desktop/.graph_token_cache.bin
3. Prints the base64-encoded value to paste into Railway's
   GRAPH_TOKEN_CACHE_B64 env var

After running:
- Open Railway dashboard → service 'dealmatcher' → Variables
- Update GRAPH_TOKEN_CACHE_B64 with the new value
- Service auto-redeploys
"""
import base64
import json
import os
import sys
from pathlib import Path

DESKTOP = Path.home() / "Desktop"
CACHE_FILE = DESKTOP / ".graph_token_cache.bin"
B64_FILE = DESKTOP / "graph_token_cache_b64.txt"

CLIENT_ID = os.getenv("GRAPH_CLIENT_ID", "b2143511-d5e1-49d9-a121-8df37116b895")
TENANT_ID = os.getenv("GRAPH_TENANT_ID", "8dd6dc0e-8291-438e-b64f-57dbd2854c38")
SCOPES = ["Mail.Read"]


def main():
    try:
        import msal
    except ImportError:
        print("Need msal: pip3 install --break-system-packages msal")
        sys.exit(1)

    print("\n═══ MICROSOFT GRAPH TOKEN REFRESH ═══\n")
    print(f"Client ID: {CLIENT_ID}")
    print(f"Tenant:    {TENANT_ID}")
    print(f"Scopes:    {SCOPES}\n")

    cache = msal.SerializableTokenCache()
    if CACHE_FILE.exists():
        cache.deserialize(CACHE_FILE.read_text())
        print(f"Loaded existing cache from {CACHE_FILE}")

    app = msal.PublicClientApplication(
        CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{TENANT_ID}",
        token_cache=cache,
    )

    # Try silent refresh first
    accounts = app.get_accounts()
    result = None
    if accounts:
        print(f"Found cached account(s): {[a.get('username') for a in accounts]}")
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
        if result and "access_token" in result:
            print("✓ Silent refresh succeeded — existing cache is still valid.")

    # Fall back to device flow if silent refresh fails
    if not result or "access_token" not in result:
        print("\nSilent refresh failed — initiating device flow...\n")
        flow = app.initiate_device_flow(scopes=SCOPES)
        if "user_code" not in flow:
            raise RuntimeError(f"Device flow init failed: {flow}")
        print(flow["message"])
        print("\nWaiting for you to sign in...\n")
        result = app.acquire_token_by_device_flow(flow)

    if "access_token" not in result:
        print(f"✗ Auth failed: {result.get('error_description')}")
        sys.exit(1)

    # Save cache
    CACHE_FILE.write_text(cache.serialize())
    print(f"\n✓ Saved cache to {CACHE_FILE}")

    # Generate base64
    b64 = base64.b64encode(CACHE_FILE.read_bytes()).decode("ascii")
    B64_FILE.write_text(b64)
    print(f"✓ Saved base64 to {B64_FILE} ({len(b64)} chars)")

    print("\n═══ NEXT STEPS ═══\n")
    print("1. Open Railway dashboard → project 'luminous-spontaneity'")
    print("2. Click service 'dealmatcher' → Variables tab")
    print("3. Edit GRAPH_TOKEN_CACHE_B64")
    print(f"4. Paste contents of {B64_FILE}")
    print("   (Easiest: `cat ~/Desktop/graph_token_cache_b64.txt | pbcopy` then Cmd+V)")
    print("5. Save — Railway auto-redeploys")
    print("6. Verify next scraper run succeeds in Railway logs\n")

    # Auto-copy to clipboard if possible (Mac only)
    try:
        import subprocess
        subprocess.run(["pbcopy"], input=b64.encode(), check=True)
        print("✓ Base64 also copied to your clipboard — just paste in Railway.\n")
    except Exception:
        pass


if __name__ == "__main__":
    main()
