"""Tests for the posture audit — detects defensive-pushback failures."""
import pytest
from unittest.mock import MagicMock, patch
from coach_auditor import audit_posture, PostureResult


def test_response_accepting_user_correction_passes():
    user_msg = "but I have VO2 4x4 scheduled for thursday"
    response_text = "You're right — Thu has VO2 4x4, I missed it. Let me reconsider."
    fake_resp = MagicMock(content=[MagicMock(type="text", text="ok")])
    with patch("coach_auditor._anthropic_client") as mc:
        mc.return_value.messages.create.return_value = fake_resp
        result = audit_posture(user_msg, response_text)
    assert result.ok is True


def test_response_challenging_user_after_their_correction_fails():
    user_msg = "but I have VO2 4x4 scheduled for thursday"
    response_text = "What are you seeing on Thursday that says quality run?"
    fake_resp = MagicMock(content=[MagicMock(type="text",
                                              text="defensive: response challenges the user instead of re-reading data")])
    with patch("coach_auditor._anthropic_client") as mc:
        mc.return_value.messages.create.return_value = fake_resp
        result = audit_posture(user_msg, response_text)
    assert result.ok is False
    assert "defensive" in result.reason.lower() or "challenge" in result.reason.lower()
