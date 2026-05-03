"""Dump Salesforce Contact fields that look buyer-related.

Run with:
    python3 /Users/christopherjohnson/dealmatcher/list_buyer_fields.py
"""
import os
import sys

from dotenv import load_dotenv
from simple_salesforce import Salesforce

load_dotenv("/Users/christopherjohnson/dealmatcher/.env.cheaphomesfla")

sf = Salesforce(
    username=os.environ["SF_USERNAME"],
    password=os.environ["SF_PASSWORD"],
    security_token=os.environ["SF_SECURITY_TOKEN"],
)

fields = sf.Contact.describe()["fields"]
print("Contact fields containing 'buyer' in API name or label:")
print("-" * 80)
for f in fields:
    if "buyer" in f["name"].lower() or "buyer" in (f["label"] or "").lower():
        name = f["name"]
        label = f["label"]
        ftype = f["type"]
        print(f"  API: {name:<45}  label={label!r}  type={ftype}")

print()
print("Also showing: 'counties', 'strategy', 'budget', 'neighborhood' matches:")
print("-" * 80)
keywords = ("counties", "strategy", "budget", "neighborhood", "primary")
for f in fields:
    nl = f["name"].lower()
    ll = (f["label"] or "").lower()
    if any(k in nl or k in ll for k in keywords) and "buyer" not in nl and "buyer" not in ll:
        print(f"  API: {f['name']:<45}  label={f['label']!r}  type={f['type']}")
