#!/usr/bin/env python3
"""
test_classifier.py — local test of the SMS keyword classifier logic
BEFORE deploying the v2 Twilio Function.

Mirrors the classify() function in sms_v2.js. Run this against real
sample replies to verify the classifier behaves as expected, then deploy
the JS to Twilio Functions.

Run:
    cd ~/dealmatcher/twilio-functions
    python3 test_classifier.py
"""
import sys

NEGATIVE_RULES = [
    {
        "name": "wrong_number",
        "keywords": ["wrong number", "wrong #", "wrong person", "don't know who",
                     "not me", "not my number"],
        "status": "Wrong Number",
    },
    {
        "name": "doesnt_own",
        "keywords": ["don't own", "dont own", "no longer own", "sold the house",
                     "sold this house", "sold it", "previous owner",
                     "doesn't belong to me"],
        "status": "Doesn't own anymore",
    },
    {
        "name": "not_interested",
        "keywords": ["not interested", "don't want to sell", "dont want to sell",
                     "not selling", "never selling", "not gonna sell",
                     "no thanks", "no thank you", "i'm not interested"],
        "status": "Not Interested",
    },
    {
        "name": "opt_out",
        "keywords": ["stop", "stopped", "unsubscribe", "remove me", "remove from",
                     "take me off", "do not contact", "opt out", "opt-out",
                     "quit", "cancel", "leave me alone", "stop texting",
                     "lose my number", "fuck off", "fck off", "block", "spam",
                     "harassment"],
        "status": "Take me off the list",
    },
]

INTERESTED_KEYWORDS = [
    "yes", "interested", "tell me more", "how much", "what's your offer",
    "whats your offer", "make an offer", "send offer", "send me", "details",
    "more info", "more information", "still available", "available?", "call me",
    "let's talk", "lets talk", "when can", "i would like", "i'd like", "id like",
    "curious", "open to", "considering", "how does this work", "how would",
    "price?", "offer?", "need cash", "need to sell",
]


def classify(body: str) -> dict:
    lower = (body or "").lower().strip()
    if not lower:
        return {"type": "empty"}
    for rule in NEGATIVE_RULES:
        if any(k in lower for k in rule["keywords"]):
            return {"type": "negative", "rule": rule["name"], "status": rule["status"]}
    if any(k in lower for k in INTERESTED_KEYWORDS):
        return {"type": "interested"}
    return {"type": "ambiguous"}


# =============================================================================
# Test cases — every common reply pattern
# =============================================================================

TEST_CASES = [
    # NEGATIVE — wrong number
    ("Wrong number buddy", "negative", "Wrong Number"),
    ("This is the wrong number, sorry", "negative", "Wrong Number"),
    ("you have the wrong person", "negative", "Wrong Number"),

    # NEGATIVE — doesn't own
    ("I sold this house years ago", "negative", "Doesn't own anymore"),
    ("Don't own that property anymore", "negative", "Doesn't own anymore"),
    ("we sold it in 2022", "negative", "Doesn't own anymore"),

    # NEGATIVE — not interested
    ("Not interested thank you", "negative", "Not Interested"),
    ("I don't want to sell my house", "negative", "Not Interested"),
    ("never selling", "negative", "Not Interested"),
    ("No thanks", "negative", "Not Interested"),

    # NEGATIVE — opt out
    ("STOP", "negative", "Take me off the list"),
    ("stop texting me", "negative", "Take me off the list"),
    ("Take me off your list", "negative", "Take me off the list"),
    ("unsubscribe", "negative", "Take me off the list"),
    ("Remove me from this list", "negative", "Take me off the list"),
    ("leave me alone", "negative", "Take me off the list"),
    ("fuck off", "negative", "Take me off the list"),

    # INTERESTED
    ("Yes I'd be interested", "interested", None),
    ("How much would you offer?", "interested", None),
    ("What's your offer?", "interested", None),
    ("Tell me more about this", "interested", None),
    ("call me", "interested", None),
    ("Send me the details", "interested", None),
    ("I need to sell", "interested", None),

    # AMBIGUOUS
    ("hi", "ambiguous", None),
    ("ok", "ambiguous", None),
    ("?", "ambiguous", None),
    ("Who is this", "ambiguous", None),
    ("How did you get my number", "ambiguous", None),
]


def main() -> int:
    failures = 0
    print(f"Running {len(TEST_CASES)} classifier tests...\n")
    for body, expected_type, expected_status in TEST_CASES:
        result = classify(body)
        type_ok = result["type"] == expected_type
        status_ok = (
            expected_status is None
            or result.get("status") == expected_status
        )
        ok = type_ok and status_ok
        marker = "✓" if ok else "✗"
        line = f"  {marker} {body!r:<55} → {result['type']}"
        if "rule" in result:
            line += f" ({result['rule']} / {result['status']})"
        print(line)
        if not ok:
            failures += 1
            print(f"      Expected: type={expected_type}, status={expected_status}")
            print(f"      Got:      {result}")
    print()
    if failures:
        print(f"❌ {failures} test(s) FAILED")
        return 1
    print(f"✓ All {len(TEST_CASES)} tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
