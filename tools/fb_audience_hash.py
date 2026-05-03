#!/usr/bin/env python3
"""
fb_audience_hash.py — produce a Facebook-Custom-Audience-ready hashed CSV.

Facebook expects each PII column to be SHA-256 hashed of the
lowercased+trimmed value (with phone in E.164-ish form: digits only,
prefixed with country code, no leading +). This script normalizes +
hashes and outputs a CSV that you can drag straight into the Ads
Manager Custom Audience uploader.

Run:
    cd ~/dealmatcher
    python3 tools/fb_audience_hash.py \\
        --in  data/below_market_seed.csv \\
        --out data/fb_audience_below_market_hashed.csv

Or use --in data/sell_score_YYYYMMDD.csv for the seller-side audience.

Input CSV is expected to have any of these column names (case-sensitive):
    email, EMAIL, Email
    phone, PHONE, Phone, MobilePhone, mobile_phone
    first_name, FirstName, FIRST_NAME
    last_name, LastName, LAST_NAME
    zip, ZIP, postal_code
    country (defaults to "us")

Any other columns are dropped from the output (Facebook ignores them).

References:
    https://developers.facebook.com/docs/marketing-api/audiences/guides/custom-audiences/
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import re
from pathlib import Path

FIELD_OUT = ["email", "phone", "fn", "ln", "zip", "country"]

EMAIL_KEYS = ("email", "EMAIL", "Email")
PHONE_KEYS = ("phone", "PHONE", "Phone", "MobilePhone", "mobile_phone")
FIRST_KEYS = ("first_name", "FirstName", "FIRST_NAME", "fn")
LAST_KEYS  = ("last_name", "LastName", "LAST_NAME", "ln")
ZIP_KEYS   = ("zip", "ZIP", "postal_code", "PostalCode")
COUNTRY_KEYS = ("country", "COUNTRY", "Country")


def first(row: dict, keys) -> str:
    for k in keys:
        if k in row and row[k]:
            return str(row[k]).strip()
    return ""


def normalize_email(s: str) -> str:
    return s.strip().lower()


def normalize_phone(s: str, default_country_code: str = "1") -> str:
    """E.164 without the leading +. US default if no country code present."""
    digits = re.sub(r"\D", "", s or "")
    if not digits:
        return ""
    # If it's clearly missing a country code, prepend US 1
    if len(digits) == 10:
        digits = default_country_code + digits
    return digits


def normalize_name(s: str) -> str:
    return re.sub(r"[^a-z]", "", (s or "").lower())


def normalize_zip(s: str) -> str:
    digits = re.sub(r"\D", "", s or "")
    return digits[:5]


def sha256_or_blank(s: str) -> str:
    if not s:
        return ""
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def hash_row(row: dict) -> dict:
    email   = normalize_email(first(row, EMAIL_KEYS))
    phone   = normalize_phone(first(row, PHONE_KEYS))
    fn      = normalize_name(first(row, FIRST_KEYS))
    ln      = normalize_name(first(row, LAST_KEYS))
    zip_   = normalize_zip(first(row, ZIP_KEYS))
    country = (first(row, COUNTRY_KEYS) or "us").lower()
    return {
        "email":   sha256_or_blank(email),
        "phone":   sha256_or_blank(phone),
        "fn":      sha256_or_blank(fn),
        "ln":      sha256_or_blank(ln),
        "zip":     sha256_or_blank(zip_),
        "country": sha256_or_blank(country),
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--in",  dest="src", type=Path, required=True)
    p.add_argument("--out", dest="dst", type=Path, required=True)
    args = p.parse_args()

    with args.src.open(newline="", encoding="utf-8") as fin, \
         args.dst.open("w", newline="", encoding="utf-8") as fout:
        reader = csv.DictReader(fin)
        writer = csv.DictWriter(fout, fieldnames=FIELD_OUT)
        writer.writeheader()
        n_total = 0
        n_with_any = 0
        for row in reader:
            n_total += 1
            hashed = hash_row(row)
            if any(hashed[k] for k in ("email", "phone")):
                writer.writerow(hashed)
                n_with_any += 1
    print(f"Read {n_total} rows from {args.src}")
    print(f"Wrote {n_with_any} hashed rows to {args.dst}")
    print(f"  ({n_total - n_with_any} dropped — neither email nor phone present)")
    print()
    print("Next: in Facebook Ads Manager →")
    print("  Audiences → Create Audience → Custom Audience → Customer List → Upload from CSV")


if __name__ == "__main__":
    main()
