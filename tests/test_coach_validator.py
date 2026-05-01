"""Unit tests for the coach response validator."""
import pytest


class TestParseEnvelope:
    def test_parses_required_sections(self):
        from coach_validator import parse_envelope
        raw = (
            "<schedule>X</schedule>\n"
            "<directive>Y</directive>\n"
            "<motivation>Z</motivation>\n"
        )
        s = parse_envelope(raw)
        assert s["schedule"] == "X"
        assert s["directive"] == "Y"
        assert s["motivation"] == "Z"
        assert "refusal" not in s

    def test_parses_optional_refusal(self):
        from coach_validator import parse_envelope
        raw = (
            "<schedule>X</schedule>\n"
            "<directive>Y</directive>\n"
            "<motivation>Z</motivation>\n"
            "<refusal>No.</refusal>\n"
        )
        s = parse_envelope(raw)
        assert s["refusal"] == "No."

    def test_returns_empty_dict_on_garbage(self):
        from coach_validator import parse_envelope
        s = parse_envelope("not an envelope")
        assert s == {}


class TestBannedPhraseScan:
    @pytest.mark.parametrize("phrase", [
        "your call",
        "if you feel up to it",
        "great job",
        "would you like",
        "let's see how",
    ])
    def test_catches_banned(self, phrase):
        from coach_validator import scan_banned_phrases
        result = scan_banned_phrases(f"Hey, {phrase} out there.")
        assert result == phrase

    def test_passes_clean_text(self):
        from coach_validator import scan_banned_phrases
        assert scan_banned_phrases("Lift now. Front Squat.") is None


class TestQuestionScan:
    def test_catches_question(self):
        from coach_validator import scan_questions
        assert scan_questions("How did that feel?") is True

    def test_passes_statement(self):
        from coach_validator import scan_questions
        assert scan_questions("Front Squat 5x5 at 175. Log it.") is False


class TestValidateResponse:
    def _ok_envelope(self):
        return (
            "<schedule>S</schedule>\n"
            "<directive>D</directive>\n"
            "<motivation>Lift now. Stay tight.</motivation>\n"
        )

    def test_valid_response_passes(self):
        from coach_validator import validate_response
        result = validate_response(
            raw=self._ok_envelope(),
            prefilled_schedule="<schedule>S</schedule>",
            prefilled_directive="<directive>D</directive>",
            refusal_required=False,
        )
        assert result.ok is True

    def test_altered_schedule_fails(self):
        from coach_validator import validate_response
        result = validate_response(
            raw=self._ok_envelope().replace("<schedule>S</schedule>", "<schedule>WRONG</schedule>"),
            prefilled_schedule="<schedule>S</schedule>",
            prefilled_directive="<directive>D</directive>",
            refusal_required=False,
        )
        assert result.ok is False
        assert "schedule" in result.failure_reason.lower()

    def test_banned_phrase_in_motivation_fails(self):
        from coach_validator import validate_response
        raw = (
            "<schedule>S</schedule>\n"
            "<directive>D</directive>\n"
            "<motivation>Great job today!</motivation>\n"
        )
        result = validate_response(
            raw=raw,
            prefilled_schedule="<schedule>S</schedule>",
            prefilled_directive="<directive>D</directive>",
            refusal_required=False,
        )
        assert result.ok is False
        assert "great job" in result.failure_reason.lower()

    def test_question_in_motivation_fails(self):
        from coach_validator import validate_response
        raw = (
            "<schedule>S</schedule>\n"
            "<directive>D</directive>\n"
            "<motivation>How did that feel?</motivation>\n"
        )
        result = validate_response(
            raw=raw,
            prefilled_schedule="<schedule>S</schedule>",
            prefilled_directive="<directive>D</directive>",
            refusal_required=False,
        )
        assert result.ok is False
        assert "question" in result.failure_reason.lower()

    def test_missing_required_refusal_fails(self):
        from coach_validator import validate_response
        result = validate_response(
            raw=self._ok_envelope(),
            prefilled_schedule="<schedule>S</schedule>",
            prefilled_directive="<directive>D</directive>",
            refusal_required=True,  # but no <refusal> in raw
        )
        assert result.ok is False
        assert "refusal" in result.failure_reason.lower()


class TestDeterministicFallback:
    def test_renders_basic(self):
        from coach_validator import deterministic_fallback
        out = deterministic_fallback(
            prefilled_schedule="<schedule>S</schedule>",
            prefilled_directive="<directive>D</directive>",
            refusal_required=False,
        )
        assert "S" in out
        assert "D" in out
        assert "?" not in out

    def test_includes_refusal_when_required(self):
        from coach_validator import deterministic_fallback
        out = deterministic_fallback(
            prefilled_schedule="<schedule>S</schedule>",
            prefilled_directive="<directive>Train as planned.</directive>",
            refusal_required=True,
        )
        assert "Train as planned" in out
