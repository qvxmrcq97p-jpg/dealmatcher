#!/usr/bin/env python3
"""
cc_v3.py — Constant Contact v3 API client for CheapHomesFLA.

Two responsibilities:
  A) Send the daily Bucket B statewide blast (create email campaign,
     associate with master list, schedule for immediate send).
  B) Remove SF-buyer emails from the CC master list so people who
     opted into Bucket A's filtered SendGrid stream never receive the
     CC mass blast too.

Environment variables (set on Railway + locally in .env.cheaphomesfla):
  CC_CLIENT_ID          App's client_id (UUID)
  CC_CLIENT_SECRET      App's client secret
  CC_REFRESH_TOKEN      Long-lived refresh token from the OAuth dance
  CC_LIST_ID            The master list UUID (the ~22K Cheap Homes FLA list)
  CC_AUTO_SEND          "true" to actually send; anything else creates a draft

Endpoints used (CC v3, Okta-backed authz):
  https://identity.constantcontact.com/oauth2/aus1lm3ry9mF7x2Ja0h8/v1/token
  https://api.cc.email/v3/emails
  https://api.cc.email/v3/emails/activities
  https://api.cc.email/v3/contacts          (find contact by email)
  https://api.cc.email/v3/contacts/{id}     (update contact list_memberships)

I am NOT 100% certain on all the exact request shapes — CC's v3 API has
evolved. Run with CC_AUTO_SEND=false on first deploy to inspect the draft
in CC's UI before flipping to live send.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

log = logging.getLogger(__name__)

TOKEN_URL = "https://identity.constantcontact.com/oauth2/aus1lm3ry9mF7x2Ja0h8/v1/token"
API_BASE  = "https://api.cc.email/v3"


# ---------------------------------------------------------------------------
# Token refresh
# ---------------------------------------------------------------------------

def _save_rotated_refresh_token(new_refresh: str) -> None:
    """Persist a rotated refresh token to ~/dealmatcher/.env.cheaphomesfla AND
    ~/Desktop/.env.cheaphomesfla so the next run doesn't try the dead old token.

    CC's OAuth server returns a NEW refresh_token with every refresh response
    when the app is configured for Rotating Refresh Tokens. We thought we'd
    set Long-Lived but the API behaviour proves otherwise. So we save the new
    one defensively after every successful refresh.
    """
    import re as _re
    from pathlib import Path as _Path
    candidates = [
        _Path.home() / "dealmatcher" / ".env.cheaphomesfla",
        _Path.home() / "Desktop" / ".env.cheaphomesfla",
    ]
    for p in candidates:
        if not p.exists():
            continue
        try:
            content = p.read_text()
            if _re.search(r"^CC_REFRESH_TOKEN=", content, flags=_re.MULTILINE):
                content = _re.sub(r"^CC_REFRESH_TOKEN=.*$", f"CC_REFRESH_TOKEN={new_refresh}", content, flags=_re.MULTILINE)
            else:
                if content and not content.endswith("\n"):
                    content += "\n"
                content += f"CC_REFRESH_TOKEN={new_refresh}\n"
            p.write_text(content)
            log.info("CC: persisted rotated refresh_token to %s", p)
        except Exception as e:  # noqa: BLE001
            log.warning("CC: could not write rotated refresh_token to %s: %s", p, e)
    # Also update in-process env so subsequent calls in the same run use the new one
    os.environ["CC_REFRESH_TOKEN"] = new_refresh


def refresh_access_token() -> str:
    """Exchange CC_REFRESH_TOKEN for a fresh access_token. Returns just the token string.

    Saves any rotated refresh_token back to the .env files so the next run
    uses the latest value. CC's OAuth server rotates refresh tokens by default
    even when the app is marked "Long-Lived" — we discovered this the hard way
    on 2026-05-19 when Bucket B failed with HTTP 400 on the second refresh in
    a single scraper run.
    """
    client_id     = os.environ["CC_CLIENT_ID"]
    client_secret = os.environ["CC_CLIENT_SECRET"]
    refresh_token = os.environ["CC_REFRESH_TOKEN"]

    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    body = urllib.parse.urlencode({
        "grant_type":    "refresh_token",
        "refresh_token": refresh_token,
    }).encode()
    req = urllib.request.Request(
        TOKEN_URL,
        data=body,
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type":  "application/x-www-form-urlencoded",
            "Accept":        "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            payload = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        log.error("CC token refresh HTTP %d: %s", e.code, body_text)
        raise RuntimeError(f"CC token refresh failed: HTTP {e.code} — {body_text}")

    tok = payload.get("access_token")
    if not tok:
        raise RuntimeError(f"No access_token in refresh response: {payload}")

    # CC rotates the refresh token — save the new one
    new_refresh = payload.get("refresh_token")
    if new_refresh and new_refresh != refresh_token:
        _save_rotated_refresh_token(new_refresh)

    log.info("CC: refreshed access_token (expires in %s s)", payload.get("expires_in", "?"))
    return tok


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _http(method: str, path: str, token: str, body: Any | None = None,
          query: dict | None = None, timeout: int = 25) -> tuple[int, Any]:
    url = f"{API_BASE}{path}"
    if query:
        url = url + "?" + urllib.parse.urlencode(query)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type":  "application/json",
            "Accept":        "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8")
            try:
                return r.status, json.loads(raw) if raw else None
            except json.JSONDecodeError:
                return r.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, raw


# ---------------------------------------------------------------------------
# Campaign create + send (Bucket B)
# ---------------------------------------------------------------------------

def create_email_campaign(token: str, name: str, subject: str, html: str,
                          from_name: str, from_email: str,
                          reply_to_email: str | None = None,
                          preheader: str = "",
                          contact_list_ids: list[str] | None = None,
                          physical_address_in_footer: dict | None = None) -> dict:
    """Create a v3 email campaign (CustomCodeCampaignV3 shape) as a draft.

    Returns the campaign object (incl. campaign_id and campaign_activities).

    CC's CustomCodeCampaignV3 spec accepts on the embedded activity:
      - format_type: 5 (Custom Code)
      - from_name, from_email, reply_to_email
      - subject, preheader (preview text)
      - html_content
      - physical_address_in_footer
      - contact_list_ids (audience set inline — preferred over separate PUT
        which loses from_email since CC's PUT requires the full activity body)
    """
    activity = {
        "format_type":   5,           # 5 = Custom Code
        "from_name":     from_name,
        "from_email":    from_email,
        "reply_to_email": reply_to_email or from_email,
        "subject":       subject,
        "preheader":     preheader,
        "html_content":  html,
        "physical_address_in_footer": physical_address_in_footer or {
            "address_line1": "PO Box 970307",
            "city":          "Coconut Creek",
            "state_code":    "FL",
            "postal_code":   "33097",
            "country_code":  "US",
        },
    }
    if contact_list_ids:
        activity["contact_list_ids"] = contact_list_ids

    body = {"name": name, "email_campaign_activities": [activity]}
    status, resp = _http("POST", "/emails", token, body=body)
    if status >= 400:
        raise RuntimeError(f"CC create_email_campaign {status}: {resp}")
    log.info("CC: created campaign '%s' (status %d) with %d list(s)",
             name, status, len(contact_list_ids or []))
    return resp


def get_primary_activity_id(campaign: dict) -> str | None:
    """From a campaign object returned by /emails, get the primary activity ID
    (role 'primary_email') which is the one we associate with a list and schedule."""
    for act in campaign.get("campaign_activities", []) or []:
        if act.get("role") == "primary_email":
            return act.get("campaign_activity_id")
    return None


def associate_activity_with_list(token: str, activity_id: str, list_id: str) -> dict:
    """Associate a campaign activity with a contact list (audience).

    CC's PUT /emails/activities/{id} requires the FULL CustomCodeCampaignActivityV3
    body — partial updates fail with 'From Email is null' / 'Subject is null' /
    etc. So we GET the current activity, merge in contact_list_ids, then PUT
    the full object back.
    """
    # Fetch current activity state
    status, current = _http("GET", f"/emails/activities/{activity_id}", token)
    if status >= 400:
        raise RuntimeError(f"CC get_activity {status}: {current}")

    # Build full update body. CC's PUT spec requires these top-level fields
    # on a CustomCode activity (format_type=5). Merge in contact_list_ids.
    body = {
        "format_type":   current.get("format_type", 5),
        "from_name":     current.get("from_name"),
        "from_email":    current.get("from_email"),
        "reply_to_email": current.get("reply_to_email"),
        "subject":       current.get("subject"),
        "preheader":     current.get("preheader", ""),
        "html_content":  current.get("html_content"),
        "physical_address_in_footer": current.get("physical_address_in_footer"),
        "contact_list_ids": [list_id],
    }
    # Strip None values that CC might reject
    body = {k: v for k, v in body.items() if v is not None}

    status, resp = _http("PUT", f"/emails/activities/{activity_id}", token, body=body)
    if status >= 400:
        raise RuntimeError(f"CC associate_list {status}: {resp}")
    log.info("CC: associated activity %s with list %s", activity_id, list_id)
    return resp


def schedule_send_now(token: str, activity_id: str) -> dict:
    """Schedule a campaign activity to send immediately.

    CC's "schedule" endpoint takes a scheduled_date in the future, OR
    "0" to send immediately (per CC docs). We use "0".
    """
    body = {"scheduled_date": "0"}
    status, resp = _http("POST", f"/emails/activities/{activity_id}/schedules", token, body=body)
    if status >= 400:
        raise RuntimeError(f"CC schedule_send_now {status}: {resp}")
    log.info("CC: scheduled activity %s to send now", activity_id)
    return resp


def send_bucket_b(html: str, subject: str, list_id: str,
                  from_name: str = "Christopher Johnson",
                  from_email: str = "info@cheaphomesfla.com",
                  reply_to_email: str = "info@cheaphomesfla.com",
                  campaign_name: str | None = None,
                  preheader: str = "",
                  auto_send: bool = False) -> dict:
    """High-level: create campaign, associate list, optionally send.

    Returns {campaign_id, activity_id, scheduled} dict.
    If auto_send is False, leaves the campaign as a DRAFT in CC's UI for
    manual review + send.
    """
    token = refresh_access_token()
    if campaign_name is None:
        # Include HH:MM:SS so retries during the same day don't collide with
        # CC's "Email Campaign Name is not unique" 409 error. Each retry
        # gets a unique name; the LATEST one wins as the canonical send.
        now = dt.datetime.now()
        campaign_name = f"CheapHomesFLA Daily Brief — {now.strftime('%Y-%m-%d %H:%M:%S')}"

    # Two-step: create campaign, then PUT activity with full body + list_ids.
    # Inline contact_list_ids in the create payload is silently ignored by
    # CC (discovered 2026-05-19 evening — schedule fails with 'no contact
    # list' even though we set it inline). The PUT must include the full
    # activity body or CC returns 'From Email is null'. associate_activity_with_list
    # now does GET→merge→PUT to handle this correctly.
    campaign = create_email_campaign(
        token, campaign_name, subject, html,
        from_name=from_name, from_email=from_email,
        reply_to_email=reply_to_email, preheader=preheader,
    )
    campaign_id = campaign.get("campaign_id")
    activity_id = get_primary_activity_id(campaign)
    if not activity_id:
        raise RuntimeError(f"No primary_email activity in response: {campaign}")

    associate_activity_with_list(token, activity_id, list_id)

    if auto_send:
        schedule_send_now(token, activity_id)
        scheduled = True
    else:
        log.info("CC: auto_send=False — campaign left as DRAFT for manual review")
        scheduled = False

    return {
        "campaign_id":  campaign_id,
        "activity_id":  activity_id,
        "scheduled":    scheduled,
        "campaign_name": campaign_name,
    }


# ---------------------------------------------------------------------------
# Contact list dedup (remove SF buyers from CC master list)
# ---------------------------------------------------------------------------

def find_contact_by_email(token: str, email: str) -> dict | None:
    """GET /contacts?email=... → returns first match or None."""
    status, resp = _http("GET", "/contacts", token, query={"email": email, "limit": 1})
    if status >= 400:
        log.warning("CC find_contact %s -> %d: %s", email, status, resp)
        return None
    if isinstance(resp, dict):
        contacts = resp.get("contacts", []) or []
        return contacts[0] if contacts else None
    return None


def remove_contact_from_list(token: str, contact_id: str, list_id: str) -> bool:
    """Remove a contact from a single list.

    CC v3: PUT /contacts/{id} with the FULL list_memberships array minus
    the list_id we want to remove. There's no DELETE-from-list shortcut.
    """
    status, resp = _http("GET", f"/contacts/{contact_id}", token)
    if status >= 400:
        log.warning("CC get_contact %s -> %d", contact_id, status)
        return False
    contact = resp if isinstance(resp, dict) else {}
    memberships = contact.get("list_memberships", []) or []
    if list_id not in memberships:
        return True  # Already not on the list
    new_memberships = [lid for lid in memberships if lid != list_id]
    body = {
        "list_memberships":   new_memberships,
        "update_source":      "Account",
    }
    status, resp = _http("PUT", f"/contacts/{contact_id}", token, body=body)
    if status >= 400:
        log.warning("CC update_contact %s -> %d: %s", contact_id, status, resp)
        return False
    return True


def dedup_sf_buyers_from_cc_list(emails: list[str], list_id: str) -> dict:
    """For each email in SF-buyers-on-Bucket-A, remove from CC master list.

    Returns {scanned, found, removed, errors} dict.
    Safe to run daily — idempotent.
    """
    if not emails:
        return {"scanned": 0, "found": 0, "removed": 0, "errors": 0}
    token = refresh_access_token()
    scanned = found = removed = errors = 0
    for email in emails:
        email = (email or "").strip().lower()
        if not email:
            continue
        scanned += 1
        try:
            c = find_contact_by_email(token, email)
            if not c:
                continue
            found += 1
            cid = c.get("contact_id")
            if cid and remove_contact_from_list(token, cid, list_id):
                removed += 1
        except Exception as e:  # noqa: BLE001
            errors += 1
            log.warning("CC dedup error for %s: %s", email, e)
        # Be polite to the API — CC v3 free tier is 10K/day, 4/sec
        time.sleep(0.25)
    return {"scanned": scanned, "found": found, "removed": removed, "errors": errors}
