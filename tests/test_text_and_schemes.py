"""Preprocessing, PII redaction, language detection and scheme detection."""

import pytest

from backend.app.nlp.schemes import UNKNOWN_SCHEME, default_registry
from backend.app.nlp.text import content_hash, detect_language, model_text, normalize_text, redact_pii

R = default_registry()


# ── Normalization ─────────────────────────────────────────────────────────

def test_normalize_collapses_whitespace_and_zero_width():
    assert normalize_text("  PM​-KISAN \n\t status  ") == "PM-KISAN status"


def test_normalize_nfkc_fullwidth():
    assert normalize_text("ＰＭ ＫＩＳＡＮ") == "PM KISAN"


def test_model_text_lowercases_and_strips_urls():
    assert model_text("Apply at https://pmkisan.gov.in NOW") == "apply at now"


def test_content_hash_is_case_and_edge_punctuation_insensitive():
    assert content_hash("How do I apply?") == content_hash("  how do i apply ")
    assert content_hash("How do I apply?") != content_hash("How do I register?")


def test_empty_inputs():
    assert normalize_text(None) == ""
    assert model_text("") == ""


# ── PII ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,token,kind", [
    ("call me on 9876543210 please", "[PHONE]", "phone"),
    ("my number +91 98765 43210", "[PHONE]", "phone"),
    ("aadhaar 2345 6789 0123 is linked", "[AADHAAR]", "aadhaar"),
    ("mail ramesh.k@example.com", "[EMAIL]", "email"),
    ("PAN ABCDE1234F", "[PAN]", "pan"),
    ("account 123456789012345", "[NUMBER]", "id_number"),
    ("Ghazipur pin 227520", "[PIN]", "pin_code"),
    ("Chandan Nagar, Nagpur Maharashtra 440024", "[PIN]", "pin_code"),
])
def test_pii_redaction(raw, token, kind):
    r = redact_pii(raw)
    assert token in r.text and r.redacted and kind in r.kinds


def test_pii_keeps_amounts_and_years():
    for t in ("I received 6000 rupees in 2024 for the 15th installment", "a loan of Rs 500000 for my shop",
              "subsidy of ₹250000 under PMAY", "250000 rupees were sanctioned"):
        r = redact_pii(t)
        assert not r.redacted, t


# ── Language ──────────────────────────────────────────────────────────────

def test_language_english():
    lang = detect_language("How do I apply for the PM-KISAN scheme online?")
    assert lang.code == "en" and lang.supported


def test_language_devanagari_is_hindi():
    lang = detect_language("मनरेगा की मजदूरी अभी तक नहीं मिली है")
    assert lang.code == "hi" and lang.method == "script" and lang.supported


def test_language_romanized_hindi():
    lang = detect_language("Mujhe abhi tak PM Kisan ka paisa nahi mila hai")
    assert lang.code == "hi-Latn" and lang.supported


def test_language_too_short_is_undetermined():
    assert detect_language("ok sir").code == "und"


# ── Scheme detection ──────────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("pm-kisan 15th installment not received", "PM-KISAN"),
    ("PM KISAN status check", "PM-KISAN"),
    ("pmkisan ekyc", "PM-KISAN"),
    ("Fasal Bima claim rejected", "PMFBY"),
    ("my MGNREGA job card", "MGNREGA"),
    ("NREGA wages pending", "MGNREGA"),
    ("ujjwala refill subsidy", "PMUY"),
    ("Ayushman card hospital list", "Ayushman Bharat PM-JAY"),
    ("Atal Pension contribution", "APY"),
    ("मनरेगा मजदूरी", "MGNREGA"),
])
def test_scheme_aliases(text, expected):
    assert R.detect(text).primary == expected


def test_scheme_word_boundaries_avoid_false_positives():
    assert R.detect("I am happy with the service").primary is None      # 'apy' inside 'happy'
    assert R.detect("the snapy app crashed").primary is None
    assert R.detect("Soil health card kaise milega").primary is None     # not PM-JAY 'health card'


def test_scheme_exclusion_pm_kisan_maandhan():
    assert R.detect("PM Kisan Maan-dhan pension enrolment").primary is None
    assert R.detect("PM Kisan and PM Kisan Maan-dhan").primary == "PM-KISAN"


def test_multi_scheme_ordered_by_mentions():
    d = R.detect("APY or PMJJBY? I already have APY and want to compare")
    assert d.schemes == ["APY", "PMJJBY"] and d.strength == "strong"


def test_weak_alias_only_without_strong_match():
    assert R.detect("crop insurance claim delayed").schemes == ["PMFBY"]
    assert R.detect("crop insurance claim delayed").strength == "weak"
    d = R.detect("crop insurance under Ujjwala?")
    assert d.schemes == ["PMUY"] and d.strength == "strong"


def test_unknown_scheme_label():
    d = R.detect("When will the state scholarship be paid?")
    assert d.primary is None and d.label == UNKNOWN_SCHEME


def test_canonicalize_legacy_names():
    assert R.canonicalize("Pradhan Mantri Fasal Bima Yojana (PMFBY)") == "PMFBY"
    assert R.canonicalize("Ayushman Bharat - PM-JAY") == "Ayushman Bharat PM-JAY"
    assert R.canonicalize("Other / Unknown") is None
    assert R.canonicalize("Soil Health Card") == "Soil Health Card"  # unrecognised labels are kept verbatim


# ── Geography ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("Orissa", "Odisha"), ("uttar pradesh", "Uttar Pradesh"), ("J&K", "Jammu and Kashmir"),
    ("Andaman & Nicobar Islands", "Andaman and Nicobar Islands"), ("Unknown", None), ("", None),
    ("Atlantis", "Atlantis"),   # unrecognised values are kept verbatim, never guessed
])
def test_state_normalization(raw, expected):
    from backend.app.nlp.geo import normalize_state
    assert normalize_state(raw) == expected
