"""Unit tests for merchant rule key normalization (no DB)."""

from web.merchant_rules.keys import display_merchant_label, merchant_key


def test_merchant_key_prefers_entity_id():
    assert merchant_key("AbC-12", "Some Name") == "eid:abc-12"


def test_merchant_key_falls_back_to_name():
    assert merchant_key(None, "  Whole Foods  ") == "name:whole foods"
    assert merchant_key("", "Whole Foods") == "name:whole foods"


def test_merchant_key_empty():
    assert merchant_key(None, None) is None
    assert merchant_key("", "  ") is None


def test_display_label_name_prefix():
    assert display_merchant_label("name:new york smoke shop") == "new york smoke shop"


def test_display_label_eid_short():
    assert display_merchant_label("eid:abc") == "abc"


def test_display_label_eid_long():
    lab = display_merchant_label("eid:abcdefghijklmnop")
    assert "…" in lab
    assert lab.startswith("abcdef")
