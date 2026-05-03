"""
Unit tests for parser.py.

Test cases drawn from real production failures observed in the
Apr 28, 2026 deal_scraper_last_run_deals.json sample (362 deals,
~97% junk under v1 parser).

Run from ~/dealmatcher/:
    python3 -m pytest tests/test_parser.py -v
or:
    python3 tests/test_parser.py    # uses unittest fallback below
"""
import os
import sys
import unittest

# Add parent directory to path so we can import parser.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parser import (  # noqa: E402
    ADDRESS_RE,
    PRICE_FLOOR,
    ParsedDeal,
    clean_body,
    extract_whatsapp_message,
    find_addresses,
    is_whatsapp_forward,
    normalize_price,
    parse_block,
    parse_email_body,
    parse_whatsapp_body,
    safe_float,
    safe_int,
)


class TestSafeNumerics(unittest.TestCase):
    """The int() empty-string crash that killed 50+ Graph messages per run."""

    def test_empty_string(self):
        self.assertIsNone(safe_int(""))
        self.assertIsNone(safe_int("   "))
        self.assertIsNone(safe_float(""))

    def test_only_punctuation(self):
        # The actual v1 crash: regex captured ',,,' → int(',,,'.replace(',','')) → int('')
        self.assertIsNone(safe_int(",,,"))
        self.assertIsNone(safe_int("$,"))
        self.assertIsNone(safe_int("..."))

    def test_none(self):
        self.assertIsNone(safe_int(None))
        self.assertIsNone(safe_float(None))

    def test_valid_with_commas(self):
        self.assertEqual(safe_int("1,234,567"), 1234567)
        self.assertEqual(safe_int("$1,500"), 1500)
        self.assertEqual(safe_float("3.5"), 3.5)


class TestCleanBody(unittest.TestCase):
    """clean_body decodes entities, strips phone numbers + boilerplate."""

    def test_nbsp_decode(self):
        out = clean_body("789 &nbsp; NW &nbsp; 118th &nbsp; Street")
        self.assertNotIn("&nbsp;", out)
        self.assertNotIn("nbsp", out.lower())
        # Should look like clean text now
        self.assertIn("789", out)
        self.assertIn("NW", out)
        self.assertIn("Street", out)

    def test_unicode_nbsp(self):
        out = clean_body("789 NW Street")
        self.assertNotIn(" ", out)
        self.assertIn("789 NW Street", out)

    def test_amp_decode(self):
        out = clean_body("Smith &amp; Sons")
        self.assertEqual("Smith & Sons", out)

    def test_phone_stripped(self):
        out = clean_body("Call (954) 589-0144 then 822 33rd Street")
        # Phone gone
        self.assertNotIn("954", out)
        self.assertNotIn("589", out)
        # Address survives
        self.assertIn("822", out)
        self.assertIn("Street", out)

    def test_phone_dotted(self):
        out = clean_body("Reply 305.555.1234 about 1234 Main St")
        self.assertNotIn("305", out)
        self.assertNotIn("555", out)
        self.assertIn("1234 Main", out)

    def test_new_deal_boilerplate(self):
        out = clean_body("* NEW DEAL * 1234 Main St Miami")
        self.assertNotIn("NEW DEAL", out)
        self.assertNotIn("*", out)
        self.assertIn("1234 Main", out)

    def test_html_tags(self):
        out = clean_body("<p>1234 Main St</p><br>Miami FL")
        self.assertNotIn("<", out)
        self.assertNotIn(">", out)
        self.assertIn("1234 Main", out)

    def test_call_text_label_stripped(self):
        out = clean_body("Call: 1234 Main St Miami")
        # 'Call' gone, address survives
        self.assertNotIn("Call", out)
        self.assertIn("1234 Main", out)


class TestAddressExtraction(unittest.TestCase):
    """The headline bug: phone-number digits being matched as the leading house number."""

    def test_phone_prefix_does_NOT_create_fake_address(self):
        """v1 produced '900 Call (954) 589-0144 822 33rd Street' as a single address."""
        raw = "900 Call (954) 589-0144 Text (954) 754-4102 822&nbsp;33rd&nbsp;Street"
        cleaned = clean_body(raw)
        addrs = find_addresses(cleaned)
        self.assertGreaterEqual(len(addrs), 1)
        first = addrs[0].group(0)
        # Must NOT include the leading phone digits
        self.assertNotIn("Call", first)
        self.assertNotIn("954", first)
        # SHOULD include the actual house number 822
        self.assertIn("822", first)

    def test_short_house_number_rejected(self):
        """v1 produced '2 9451 Caribbean Blvd' — single-digit '2' was the address."""
        raw = "Property number 2 9451 Caribbean Blvd Cutler Bay FL 33189"
        cleaned = clean_body(raw)
        addrs = find_addresses(cleaned)
        self.assertGreaterEqual(len(addrs), 1)
        # The matched address should start with 9451 (4 digits), not 2
        first = addrs[0].group(0)
        self.assertIn("9451", first)
        self.assertIn("Caribbean", first)

    def test_sold_comp_rejection(self):
        """v1 sent 'SOLD $595K 1191 NE 165TH TER' to buyers AS THE DEAL ADDRESS."""
        raw = (
            "Property: 1410 NE 161st St North Miami Beach FL 33162. "
            "Asking $420K. COMPS: SOLD $595K 1191 NE 165TH TER. "
            "SOLD $644K 16961 NE 8TH PL."
        )
        cleaned = clean_body(raw)
        addrs = [m.group(0) for m in find_addresses(cleaned)]
        # The deal address (1410) IS present
        self.assertTrue(any("1410" in a for a in addrs),
                        f"deal address 1410 missing: {addrs}")
        # The comp addresses (1191, 16961) are NOT present
        self.assertFalse(any("1191" in a for a in addrs),
                         f"comp 1191 leaked into addresses: {addrs}")
        self.assertFalse(any("16961" in a for a in addrs),
                         f"comp 16961 leaked into addresses: {addrs}")

    def test_address_with_directional(self):
        raw = "1234 NW 23rd Avenue Miami FL 33125"
        cleaned = clean_body(raw)
        addrs = find_addresses(cleaned)
        self.assertEqual(len(addrs), 1)
        self.assertIn("NW", addrs[0].group(0))
        self.assertIn("23rd", addrs[0].group(0))


class TestPriceExtraction(unittest.TestCase):

    def test_label_anchored_picks_asking_over_sqft(self):
        """v1 picked '$1,500' (sqft typo) as the price."""
        raw = "1234 Main St Miami FL 33125. 3/2 1500 sqft. Asking $250,000. ARV $400K."
        d = parse_block(raw)
        self.assertEqual(d.asking_price, 250_000)
        self.assertEqual(d.sqft, 1500)

    def test_below_floor_price_rejected(self):
        """A parsed price below $30k is treated as a parse error."""
        raw = "1234 Main St Miami FL 33125. Asking $1,500"
        d = parse_block(raw)
        self.assertIsNone(d.asking_price)
        self.assertTrue(any("price_below_floor" in w for w in d.parse_warnings))

    def test_k_suffix(self):
        d = parse_block("1234 Main St Miami FL 33125. Asking $250K")
        self.assertEqual(d.asking_price, 250_000)

    def test_m_suffix(self):
        d = parse_block("1234 Main St Miami FL 33125. Asking $1.2M")
        self.assertEqual(d.asking_price, 1_200_000)

    def test_arv_separate_from_asking(self):
        raw = "1234 Main St Miami FL 33125. Asking $250K. ARV $400K."
        d = parse_block(raw)
        self.assertEqual(d.asking_price, 250_000)
        self.assertEqual(d.arv, 400_000)

    def test_arv_only_does_not_become_asking(self):
        """If only ARV is labeled and there's a bare $N, the bare $ should NOT be the asking."""
        raw = "1234 Main St Miami FL 33125. ARV $400K."
        d = parse_block(raw)
        self.assertIsNone(d.asking_price)
        self.assertEqual(d.arv, 400_000)


class TestBedsBaths(unittest.TestCase):

    def test_long_form(self):
        d = parse_block("1234 Main St Miami FL 33125. 3 BR 2 BA 1500 sqft. Asking $250K.")
        self.assertEqual(d.beds, 3.0)
        self.assertEqual(d.baths, 2.0)

    def test_shorthand_3_2(self):
        d = parse_block("1234 Main St Miami FL 33125. 3/2 home. Asking $250K.")
        self.assertEqual(d.beds, 3.0)
        self.assertEqual(d.baths, 2.0)

    def test_shorthand_with_decimal(self):
        d = parse_block("1234 Main St Miami FL 33125. 4/2.5 home. Asking $300K.")
        self.assertEqual(d.beds, 4.0)
        self.assertEqual(d.baths, 2.5)

    def test_bd_ba_qualified(self):
        d = parse_block("1234 Main St Miami FL 33125. 3BD/2BA. Asking $250K.")
        self.assertEqual(d.beds, 3.0)
        self.assertEqual(d.baths, 2.0)


class TestMultiPropertySplit(unittest.TestCase):

    def test_three_properties(self):
        raw = (
            "Inventory blast:\n"
            "1410 NE 161st St North Miami Beach FL 33162 - Asking $420K. 3/2 1453 sqft.\n"
            "9451 Caribbean Blvd Cutler Bay FL 33189 - Asking $675K. 3/2 1888 sqft.\n"
            "8226 33rd Street Miami FL 33125 - Asking $300K. 4/2 2000 sqft.\n"
        )
        deals = parse_email_body(raw)
        self.assertEqual(len(deals), 3)
        addrs = [d.address for d in deals]
        self.assertTrue(any("1410" in a for a in addrs))
        self.assertTrue(any("9451" in a for a in addrs))
        self.assertTrue(any("8226" in a for a in addrs))

    def test_single_property_passthrough(self):
        raw = "1410 NE 161st St North Miami Beach FL 33162 - Asking $420K. 3/2 1453 sqft."
        deals = parse_email_body(raw)
        self.assertEqual(len(deals), 1)


class TestRealDirtyInputs(unittest.TestCase):
    """End-to-end: feed real dirty fragments observed in production, expect clean output."""

    def test_v1_dirty_sample_1(self):
        # Real dirty address from Apr 28 dump:
        #   '900 Call (954) 589-0144 230&nbsp;Ne&nbsp;164th&nbsp;Terrace'
        raw = "900 Call (954) 589-0144 230&nbsp;Ne&nbsp;164th&nbsp;Terrace Miami FL 33162. Asking $250K."
        deals = parse_email_body(raw)
        self.assertEqual(len(deals), 1)
        addr = deals[0].address
        self.assertNotIn("Call", addr)
        self.assertNotIn("954", addr)
        self.assertIn("230", addr)
        self.assertIn("164th", addr)
        self.assertEqual(deals[0].zip_code, "33162")
        self.assertEqual(deals[0].asking_price, 250_000)

    def test_v1_dirty_sample_2(self):
        # Real: '675k-&nbsp;3 Beds/2 baths - 1888 sqft 9451 Caribbean Blvd'
        raw = "Asking $675K. 3 Beds / 2 baths - 1888 sqft. 9451 Caribbean Blvd Cutler Bay FL 33189"
        deals = parse_email_body(raw)
        self.assertEqual(len(deals), 1)
        d = deals[0]
        self.assertIn("9451", d.address)
        self.assertEqual(d.asking_price, 675_000)
        self.assertEqual(d.beds, 3.0)
        self.assertEqual(d.baths, 2.0)
        self.assertEqual(d.sqft, 1888)
        self.assertEqual(d.zip_code, "33189")

    def test_v1_dirty_sample_3_zip_prefix(self):
        # Real: '33162 1410 NE 161st St' (zip got prepended)
        # Our new parser should give the address as just '1410 NE 161st St'.
        raw = "33162 1410 NE 161st St North Miami Beach FL 33162. Asking $420K"
        deals = parse_email_body(raw)
        self.assertEqual(len(deals), 1)
        # The captured address should START at '1410', not '33162'
        self.assertTrue(deals[0].address.startswith("1410"),
                        f"Address should start with 1410, got: {deals[0].address!r}")


class TestWhatsAppForward(unittest.TestCase):
    """WA messages arrive via Green-API → Cloudflare Worker → email.
    The scraper has to recognize them and strip the wrapper before parsing."""

    def test_recognize_wa_subject(self):
        self.assertTrue(is_whatsapp_forward("[WA-Group] Miami Deals — Antonio P", ""))
        self.assertTrue(is_whatsapp_forward("[WA-DM] Antonio Pacheco", ""))
        self.assertFalse(is_whatsapp_forward("Re: 1234 Main St", ""))

    def test_recognize_wa_from(self):
        self.assertTrue(is_whatsapp_forward("anything", "whatsapp-deals@cheaphomesfla.com"))
        self.assertTrue(is_whatsapp_forward("anything", "whatsapp-deals@cheaphomesFLA.com"))
        self.assertFalse(is_whatsapp_forward("anything", "wholesale@example.com"))

    def test_extract_message_block(self):
        body = (
            "Forwarded from WhatsApp via Green-API\n\n"
            "Sender:     Antonio Pacheco\n"
            "Chat:       Miami Deals (group)\n"
            "Chat ID:    1234567890@g.us\n"
            "Received:   2026-04-28T17:00:00Z\n\n"
            "From: Antonio Pacheco <wa-1234567890@whatsapp>\n\n"
            "--- MESSAGE ---\n"
            "1234 Main St Miami FL 33125 - Asking $250K - 3/2 1500 sqft\n"
            "--- END MESSAGE ---\n\n"
            "Media URL: https://example.com/img.jpg\n"
        )
        inner = extract_whatsapp_message(body)
        self.assertNotIn("Green-API", inner)
        self.assertNotIn("Sender:", inner)
        self.assertNotIn("Media URL", inner)
        self.assertIn("1234 Main St", inner)
        self.assertIn("$250K", inner)

    def test_parse_whatsapp_full_pipeline(self):
        body = (
            "Forwarded from WhatsApp via Green-API\n\n"
            "Sender: Antonio P\n\n"
            "--- MESSAGE ---\n"
            "1234 NW 23rd Avenue Miami FL 33125\n"
            "Asking $250K   ARV $400K\n"
            "3/2  1500 sqft\n"
            "--- END MESSAGE ---\n"
        )
        deals = parse_whatsapp_body(body)
        self.assertEqual(len(deals), 1)
        d = deals[0]
        self.assertIn("1234", d.address)
        self.assertIn("23rd", d.address)
        self.assertEqual(d.asking_price, 250_000)
        self.assertEqual(d.arv, 400_000)
        self.assertEqual(d.beds, 3.0)
        self.assertEqual(d.baths, 2.0)
        self.assertEqual(d.sqft, 1500)
        self.assertEqual(d.zip_code, "33125")

    def test_wa_wrapper_text_does_not_become_an_address(self):
        """The wrapper has 'wa-1234567890@whatsapp' — that 1234567890 must NOT match."""
        body = (
            "Sender: Antonio P\n"
            "From: Antonio P <wa-1234567890@whatsapp>\n"
            "--- MESSAGE ---\n"
            "9876 Caribbean Blvd Cutler Bay FL 33189 - $450K - 4/2\n"
            "--- END MESSAGE ---\n"
        )
        deals = parse_whatsapp_body(body)
        self.assertEqual(len(deals), 1)
        self.assertIn("9876", deals[0].address)
        # The phone-like 1234567890 from the wrapper must NOT be the address
        self.assertNotIn("1234567890", deals[0].address)


if __name__ == "__main__":
    unittest.main(verbosity=2)
