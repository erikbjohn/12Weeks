"""Tests for the single-claim auditor (Sonnet-backed)."""
import pytest
from unittest.mock import MagicMock, patch
from coach_auditor import audit_claim, AuditResult


def test_supported_claim_returns_supported():
    fake_resp = MagicMock(content=[MagicMock(type="text", text="supported")])
    with patch("coach_auditor._anthropic_client") as mc:
        mc.return_value.messages.create.return_value = fake_resp
        result = audit_claim(
            claim_text="207.2 lb today",
            source_rows=["body.weight.current = 207.2 (BodyWeight#4821)"],
        )
    assert result.supported is True


def test_unsupported_claim_returns_not_supported_with_reason():
    fake_resp = MagicMock(content=[MagicMock(type="text",
                                              text="not supported: 5 weeks before 50k != 5 weeks left in cut")])
    with patch("coach_auditor._anthropic_client") as mc:
        mc.return_value.messages.create.return_value = fake_resp
        result = audit_claim(
            claim_text="5 weeks left in the cut",
            source_rows=["race.weeks_until_50k = 5-6 weeks"],
        )
    assert result.supported is False
    assert "5 weeks" in result.reason
