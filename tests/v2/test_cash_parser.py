"""
Tests for the V2.3 smart cash-entry parser.

Two layers:

* :func:`web.telegram.cash_parser.parse_deterministic` — a regex-only
  pass that has to handle every "amount-first / amount-last / weird
  Russian currency tokens" shape we have seen in user testing.
* :func:`web.telegram.cash_parser.parse_with_llm` — an OpenAI fallback
  invoked only when the deterministic pass returns ``None``. The LLM
  layer is mocked here; we test the wiring (timeout, JSON parsing,
  daily quota), not the model itself.

Quota tests use a MagicMock-backed asyncpg pool so they don't need a
live Postgres.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from tests.v2.conftest import make_mock_pool
from web.telegram import cash_parser


class TestParseDeterministic:
    @pytest.mark.parametrize(
        "text,amount,name",
        [
            # Classic "amount first" shorthand.
            ("5 coffee", 500, "coffee"),
            ("120 grocery", 12_000, "grocery"),
            # Decimal separators — both . and ,.
            ("5.50 latte", 550, "latte"),
            ("12,50 lunch", 1250, "lunch"),
            # Currency markers in different positions.
            ("$5 coffee", 500, "coffee"),
            ("5$ coffee", 500, "coffee"),
            ("$ 5 coffee", 500, "coffee"),
            ("5 € lunch", 500, "lunch"),
            # Russian style: amount first, ruble suffix, free text after.
            ("400р такси домой", 40_000, "такси домой"),
            ("400 руб такси", 40_000, "такси"),
            # USD/EUR inline, no spaces.
            ("5usd coffee", 500, "coffee"),
            # Number-last form.
            ("такси 400", 40_000, "такси"),
            ("coffee 5", 500, "coffee"),
            # Bare number — defaults to a generic description.
            ("5", 500, "Cash spend"),
            ("12.99", 1299, "Cash spend"),
        ],
    )
    def test_handles_common_shapes(self, text, amount, name):
        result = cash_parser.parse_deterministic(text)
        assert result is not None, f"Could not parse {text!r}"
        cents, parsed_name = result
        assert cents == amount, (
            f"{text!r} parsed as {cents/100} (expected {amount/100})"
        )
        assert parsed_name == name

    @pytest.mark.parametrize(
        "text",
        [
            "",  # empty
            "   ",  # whitespace
            "no amount here",  # no number
            "0 free thing",  # zero is invalid
            "-5 nope",  # negative — `-` isn't a delimiter; nothing matches
        ],
    )
    def test_returns_none_when_no_amount(self, text):
        assert cash_parser.parse_deterministic(text) is None


class TestStripCurrencyTokens:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("такси домой", "такси домой"),
            ("$ coffee", "coffee"),
            ("такси р", "такси"),
            ("usd coffee", "coffee"),
            ("EUR lunch", "lunch"),
            ("coffee", "coffee"),
            ("р", ""),
            ("", ""),
        ],
    )
    def test_strips_known_tokens(self, raw, expected):
        assert cash_parser._strip_currency_tokens(raw) == expected


class TestLLMFallback:
    """The LLM call is mocked. We validate the wiring around it — JSON
    contract, no-API-key short-circuit, normalization."""

    @pytest.mark.asyncio
    async def test_no_op_without_api_key(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        result = await cash_parser.parse_with_llm("400р такси домой")
        assert result is None

    @pytest.mark.asyncio
    async def test_normalizes_valid_response(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        # Patch the sync helper so we don't hit the network.
        def fake_run(_text):
            return {
                "amount_cents": 40_000,
                "currency": "RUB",
                "name": "такси домой",
                "is_private": False,
                "source": "llm",
            }

        with patch.object(cash_parser, "_run_openai_text", fake_run):
            out = await cash_parser.parse_with_llm("400р такси домой")
        assert out is not None
        assert out["amount_cents"] == 40_000
        assert out["currency"] == "RUB"
        assert out["name"] == "такси домой"
        assert out["is_private"] is False
        assert out["source"] == "llm"

    @pytest.mark.asyncio
    async def test_swallows_api_errors(self, monkeypatch):
        """The LLM layer is invisible UX magic — a backend error must not
        surface to the user. We expect ``None`` so the caller falls
        through to its existing 'Try `5 coffee`' hint."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        def boom(_text):
            raise RuntimeError("OpenAI 502")

        with patch.object(cash_parser, "_run_openai_text", boom):
            out = await cash_parser.parse_with_llm("400р такси домой")
        assert out is None

    @pytest.mark.asyncio
    async def test_long_input_is_skipped(self, monkeypatch):
        """200+ character text is almost certainly not a cash entry —
        skip the round trip rather than burn quota."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        called = False

        def fake_run(_text):
            nonlocal called
            called = True
            return {"amount_cents": 1, "currency": "USD", "name": "x"}

        with patch.object(cash_parser, "_run_openai_text", fake_run):
            out = await cash_parser.parse_with_llm("a" * 250)
        assert out is None
        assert called is False


class TestNormalizeLLMOutput:
    def test_drops_when_no_amount(self):
        assert cash_parser._normalize_llm_output({"amount_cents": None}) is None

    def test_drops_when_zero(self):
        assert cash_parser._normalize_llm_output({"amount_cents": 0}) is None

    def test_drops_bool_amount(self):
        # ``bool`` subclasses ``int`` — guard against ``True`` becoming $0.01.
        assert cash_parser._normalize_llm_output({"amount_cents": True}) is None

    def test_truncates_long_name(self):
        out = cash_parser._normalize_llm_output(
            {"amount_cents": 100, "name": "x" * 200}
        )
        assert out is not None
        assert len(out["name"]) <= 80

    def test_currency_alpha_only(self):
        out = cash_parser._normalize_llm_output(
            {"amount_cents": 100, "currency": "USD$"}
        )
        assert out is not None
        assert out["currency"] == "USD"

    def test_currency_falls_back_to_usd(self):
        out = cash_parser._normalize_llm_output(
            {"amount_cents": 100, "currency": ""}
        )
        assert out is not None
        assert out["currency"] == "USD"


class TestQuotaTracking:
    @pytest.mark.asyncio
    async def test_quota_remaining_when_no_usage(self, monkeypatch):
        monkeypatch.setenv("BOT_LLM_DAILY_QUOTA", "30")
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=None)
        pool = make_mock_pool(conn)
        with patch("web.telegram.cash_parser.get_pool", AsyncMock(return_value=pool)):
            assert await cash_parser.llm_quota_remaining(user_id=42) == 30

    @pytest.mark.asyncio
    async def test_quota_remaining_subtracts_usage(self, monkeypatch):
        monkeypatch.setenv("BOT_LLM_DAILY_QUOTA", "30")
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=12)
        pool = make_mock_pool(conn)
        with patch("web.telegram.cash_parser.get_pool", AsyncMock(return_value=pool)):
            assert await cash_parser.llm_quota_remaining(user_id=42) == 18

    @pytest.mark.asyncio
    async def test_quota_remaining_clamps_at_zero(self, monkeypatch):
        monkeypatch.setenv("BOT_LLM_DAILY_QUOTA", "30")
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=999)
        pool = make_mock_pool(conn)
        with patch("web.telegram.cash_parser.get_pool", AsyncMock(return_value=pool)):
            assert await cash_parser.llm_quota_remaining(user_id=42) == 0

    @pytest.mark.asyncio
    async def test_record_call_upserts_counter(self):
        captured: dict = {}
        conn = AsyncMock()

        async def fake_execute(sql, *args, **kwargs):
            captured["sql"] = sql
            captured["args"] = args
            return "INSERT 0 1"

        conn.execute = fake_execute
        pool = make_mock_pool(conn)
        with patch("web.telegram.cash_parser.get_pool", AsyncMock(return_value=pool)):
            await cash_parser.record_llm_call(user_id=42)
        assert "INSERT INTO bot_llm_usage" in captured["sql"]
        assert "ON CONFLICT (user_id, day) DO UPDATE" in captured["sql"]
        assert captured["args"][0] == 42

    @pytest.mark.asyncio
    async def test_zero_quota_returns_zero_without_db(self, monkeypatch):
        """Setting ``BOT_LLM_DAILY_QUOTA=0`` must short-circuit without
        even reading the DB so ops can disable the LLM path with one
        env knob."""
        monkeypatch.setenv("BOT_LLM_DAILY_QUOTA", "0")
        with patch(
            "web.telegram.cash_parser.get_pool",
            AsyncMock(side_effect=AssertionError("DB should not be hit")),
        ):
            assert await cash_parser.llm_quota_remaining(user_id=42) == 0
