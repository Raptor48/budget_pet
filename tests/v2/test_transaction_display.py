"""Tests for web/transactions/display.normalize_transaction_title."""
import pytest

from web.transactions.display import normalize_transaction_title


class TestPriorityOrder:
    def test_merchant_name_wins_when_pretty(self):
        assert (
            normalize_transaction_title({"merchant_name": "Spotify", "name": "SPOTIFY USA INC"})
            == "Spotify"
        )

    def test_counterparties_used_when_no_merchant(self):
        tx = {
            "name": "ACH DEBIT FROM AMAZON.COM",
            "counterparties": [
                {"name": "Amazon", "type": "merchant", "confidence_level": "VERY_HIGH"},
                {"name": "Amazon Webfront", "type": "data_processor", "confidence_level": "LOW"},
            ],
        }
        assert normalize_transaction_title(tx) == "Amazon"

    def test_counterparties_picks_highest_confidence(self):
        tx = {
            "name": "POS PURCHASE 12345 STARBUCKS",
            "counterparties": [
                {"name": "Starbucks Mobile", "type": "merchant", "confidence_level": "MEDIUM"},
                {"name": "Starbucks", "type": "merchant", "confidence_level": "VERY_HIGH"},
            ],
        }
        assert normalize_transaction_title(tx) == "Starbucks"

    def test_website_used_when_no_merchant_and_no_counterparties(self):
        tx = {
            "name": "ACH DEBIT FROM PAYMENT CO XXXXXX1234",
            "website": "https://www.netflix.com/billing",
        }
        assert normalize_transaction_title(tx) == "Netflix"


class TestRawCleanup:
    def test_strips_ach_prefix_and_metadata(self):
        title = normalize_transaction_title(
            {"name": "ACH DEBIT FROM CON ED OF NY CECONY 14427362240 CCD ID: 2462467002"}
        )
        assert "ACH" not in title.upper().split()
        assert "CCD" not in title.upper()
        assert "Con Ed Of Ny Cecony" in title or "Con Ed" in title

    def test_strips_zelle_prefix(self):
        title = normalize_transaction_title(
            {"name": "ZELLE PAYMENT TO JOHN DOE 1234567890"}
        )
        assert "ZELLE" not in title.upper()
        assert "John Doe" in title or "John" in title

    def test_strips_real_time_transfer_prefix(self):
        title = normalize_transaction_title(
            {"name": "REAL TIME TRANSFER RECD FROM JANE SMITH"}
        )
        assert "REAL TIME" not in title.upper()
        assert "TRANSFER" not in title.upper()
        assert "Jane Smith" in title

    def test_strips_debit_card_purchase_and_long_id(self):
        title = normalize_transaction_title(
            {"name": "DEBIT CARD PURCHASE TARGET 00012345678 03/27"}
        )
        assert "DEBIT" not in title.upper()
        assert "Target" in title
        assert "00012345678" not in title

    def test_strips_purchase_authorized_with_inline_date(self):
        title = normalize_transaction_title(
            {"name": "PURCHASE AUTHORIZED ON 03/15 IKEA BROOKLYN NY"}
        )
        assert "AUTHORIZED" not in title.upper()
        assert "IKEA" in title.upper()

    def test_keeps_short_already_pretty_name(self):
        assert normalize_transaction_title({"name": "Apple"}) == "Apple"

    def test_handles_pure_merchant_long_name(self):
        title = normalize_transaction_title(
            {"merchant_name": "Adobe Inc. — Creative Cloud Subscription Renewal Annual"}
        )
        assert title.endswith("\u2026")
        assert len(title) <= 42

    def test_truncates_long_cleaned_name(self):
        title = normalize_transaction_title(
            {"name": "ACH DEBIT FROM SOME REALLY VERY LONG MERCHANT NAME WITH MANY WORDS"}
        )
        assert len(title) <= 42

    def test_empty_inputs_falls_back(self):
        assert normalize_transaction_title({}) == "Transaction"
        assert normalize_transaction_title({"name": "", "merchant_name": ""}) == "Transaction"

    def test_non_dict_input_safe(self):
        assert normalize_transaction_title(None) == "Transaction"  # type: ignore[arg-type]


class TestRecurringStreamShape:
    def test_uses_description_when_no_name(self):
        title = normalize_transaction_title(
            {"description": "ADOBE *800-833-6687 ADOBE.LY/ENUS CA 03/19", "merchant_name": None}
        )
        assert "ADOBE" in title.upper()
        assert "03/19" not in title

    def test_merchant_name_still_wins_for_recurring(self):
        title = normalize_transaction_title(
            {"description": "SPECTRUM SPECTRUM PPD ID: 0000358635", "merchant_name": "Spectrum"}
        )
        assert title == "Spectrum"


class TestSmartTitle:
    def test_acronyms_preserved(self):
        title = normalize_transaction_title({"name": "IRS PAYMENT REFUND"})
        assert "IRS" in title

    def test_lowercase_connectors(self):
        title = normalize_transaction_title({"name": "BANK OF AMERICA TRANSFER"})
        assert "of" in title


@pytest.mark.parametrize(
    "raw, expected_substring",
    [
        ("APPLE.COM/BILL CA 03/27", "Apple"),
        ("Verizon Wireless", "Verizon"),
        ("UPSTART NETWORK UPST LOANS 23466173 WEB ID: 9088560612", "Upstart"),
        ("INTEREST CHARGE:PURCHASES", "Interest"),
    ],
)
def test_real_world_examples(raw, expected_substring):
    title = normalize_transaction_title({"name": raw})
    assert expected_substring.lower() in title.lower()
