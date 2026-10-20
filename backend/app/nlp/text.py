"""
Text processing primitives shared by ingestion, collection and inference.

- normalize_text: Unicode NFKC, zero-width removal, whitespace collapse.
  Meaning-preserving; used for storage, hashing and display.
- model_text: the exact string fed to classifiers (lowercased, URLs removed).
  Training and inference both call this, so they cannot drift apart.
- detect_language: script detection + langdetect + a romanized-Hindi check.
- redact_pii: removes phone numbers, Aadhaar, e-mail and PAN identifiers.
- content_hash: stable hash of normalized text for exact-duplicate detection.
"""

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

_ZERO_WIDTH = re.compile(r"[​‌‍⁠﻿]")
_WS = re.compile(r"\s+")
_URL = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)


def normalize_text(text: Optional[str]) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", str(text))
    text = _ZERO_WIDTH.sub("", text)
    return _WS.sub(" ", text).strip()


def model_text(text: Optional[str]) -> str:
    """Canonical model input. Must be identical at training and inference time."""
    text = normalize_text(text).lower()
    text = _URL.sub(" ", text)
    return _WS.sub(" ", text).strip()


def content_hash(text: Optional[str]) -> str:
    """SHA-256 of case-folded normalized text (punctuation-insensitive at the edges)."""
    key = normalize_text(text).casefold().strip(" .?!,;:\"'")
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


# ── PII ───────────────────────────────────────────────────────────────────

# Order matters: Aadhaar (12 digits) before phone (10 digits) so a 12-digit
# number is not partially consumed as a phone number.
_PII_PATTERNS = [
    ("aadhaar", re.compile(r"(?<!\d)[2-9]\d{3}[\s-]?\d{4}[\s-]?\d{4}(?!\d)"), "[AADHAAR]"),
    ("phone", re.compile(r"(?<!\d)(?:\+91[\s-]?|0)?[6-9]\d{4}[\s-]?\d{5}(?!\d)"), "[PHONE]"),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[EMAIL]"),
    ("pan", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"), "[PAN]"),
    # Bank account / application / registration numbers (9–18 digit runs).
    ("id_number", re.compile(r"(?<!\d)\d{9,18}(?!\d)"), "[NUMBER]"),
    # Postal PIN codes: labelled ("pin 227520") or standalone 6-digit numbers. A 6-digit
    # number next to a currency word/sign is treated as an amount and kept.
    ("pin_code", re.compile(r"(?i)\b(pin(?:\s*code)?|pincode)\s*[:.\-]?\s*\d{3}\s?\d{3}\b"), r"\1 [PIN]"),
    ("pin_code", re.compile(r"(?i)(?<![\d₹$])(?<!rs\.)(?<!rs )(?<!inr )(?<!rupees )[1-9]\d{2}\s?\d{3}(?!\d)(?!\s*(?:rs|rupees|inr|/-|₹|lakh|crore))"), "[PIN]"),
]


@dataclass
class RedactionResult:
    text: str
    redacted: bool
    kinds: list


def redact_pii(text: str) -> RedactionResult:
    kinds = []
    out = text or ""
    for name, pattern, replacement in _PII_PATTERNS:
        new = pattern.sub(replacement, out)
        if new != out:
            kinds.append(name)
            out = new
    return RedactionResult(text=out, redacted=bool(kinds), kinds=kinds)


# ── Language detection ────────────────────────────────────────────────────

# Unicode blocks for Indian scripts → ISO 639-1 code (best single guess per script).
_SCRIPTS = [
    ("devanagari", 0x0900, 0x097F, "hi"),
    ("bengali", 0x0980, 0x09FF, "bn"),
    ("gurmukhi", 0x0A00, 0x0A7F, "pa"),
    ("gujarati", 0x0A80, 0x0AFF, "gu"),
    ("oriya", 0x0B00, 0x0B7F, "or"),
    ("tamil", 0x0B80, 0x0BFF, "ta"),
    ("telugu", 0x0C00, 0x0C7F, "te"),
    ("kannada", 0x0C80, 0x0CFF, "kn"),
    ("malayalam", 0x0D00, 0x0D7F, "ml"),
]

# High-frequency function words of romanized Hindi ("Hinglish"). Deliberately
# excludes words that are also common English ("me", "to", "the", "is").
_ROMAN_HINDI = {
    "hai", "hain", "nahi", "nahin", "kya", "kaise", "kab", "kahan", "kyun", "kyon",
    "kitna", "kaun", "mera", "meri", "mere", "hamara", "hamare", "hamko", "humko",
    "mujhe", "aap", "aapka", "apna", "apne", "ko", "ka", "ki", "ke", "se", "par",
    "aur", "bhi", "tha", "thi", "raha", "rahi", "mila", "milega", "milta", "aaya",
    "gaya", "kar", "karo", "kare", "karna", "hoga", "sab", "abhi", "jab", "tak",
    "liye", "yojana", "ji", "sir", "pls", "kripya", "sarkar", "paisa", "ghar",
}


# Distinctive romanized Marathi function words (not shared with Hindi or English).
_ROMAN_MARATHI = {"aahe", "ahe", "aahet", "mala", "majha", "majhi", "majhe", "maza", "mazi", "maze", "tumhi",
                  "aamhi", "amhi", "kay", "kasa", "kashi", "kuthe", "nahi", "pan", "ghar", "ghara", "milala", "milel",
                  "kara", "karave", "hote", "hoti", "zala", "jhala", "sathi"}


@dataclass
class LanguageResult:
    code: str          # ISO 639-1 code, "hi-Latn" for romanized Hindi, "und" if undetermined
    script: str        # latin / devanagari / ... / mixed / unknown
    method: str        # script / langdetect / romanized_lexicon / too_short
    supported: bool    # True only for languages the trained models were trained on


# Languages with labelled training examples (English, Hindi, romanized Hindi). Other
# languages are still classified via the multilingual embedding model, but untested.
SUPPORTED_MODEL_LANGUAGES = {"en", "hi", "hi-Latn"}
# Latin-script languages that can plausibly occur in Indian public text.
PLAUSIBLE_LATIN_LANGUAGES = {"en", "und"}


def _script_profile(text: str) -> tuple[Optional[str], Optional[str], float]:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return None, None, 0.0
    counts = {}
    for c in letters:
        cp = ord(c)
        for name, lo, hi, code in _SCRIPTS:
            if lo <= cp <= hi:
                counts[(name, code)] = counts.get((name, code), 0) + 1
                break
    if not counts:
        return "latin", None, 0.0
    (name, code), n = max(counts.items(), key=lambda kv: kv[1])
    return name, code, n / len(letters)


def detect_language(text: str) -> LanguageResult:
    text = normalize_text(text)
    letters = sum(1 for c in text if c.isalpha())
    script, code, share = _script_profile(text)

    if script and script != "latin" and share >= 0.3:
        mixed = share < 0.8
        return LanguageResult(code=code, script="mixed" if mixed else script,
                              method="script", supported=code in SUPPORTED_MODEL_LANGUAGES)

    tokens = re.findall(r"[a-z]+", text.lower())
    if tokens:
        # Long comments are diluted by names and addresses, so require a minimum
        # number of function-word hits as well as a (lower) share.
        for code, lexicon in (("hi-Latn", _ROMAN_HINDI), ("mr-Latn", _ROMAN_MARATHI)):
            hits = sum(1 for t in tokens if t in lexicon)
            if len(tokens) >= 4 and hits >= 2 and (hits / len(tokens) >= 0.25 or (hits >= 3 and hits / len(tokens) >= 0.12)):
                return LanguageResult(code=code, script="latin", method="romanized_lexicon",
                                      supported=code in SUPPORTED_MODEL_LANGUAGES)

    if letters < 12:
        return LanguageResult(code="und", script=script or "unknown", method="too_short", supported=False)

    try:
        from langdetect import DetectorFactory, detect_langs
        DetectorFactory.seed = 0  # deterministic results
        best = detect_langs(text)[0]
        lang = best.lang if best.prob >= 0.70 else "und"
    except Exception:
        lang = "und"
    if lang not in PLAUSIBLE_LATIN_LANGUAGES:
        # langdetect often labels romanized Hindi as Indonesian, Swahili, Somali, …
        # For Indian sources those labels are implausible; fall back to the lexicon.
        has_hindi = tokens and sum(1 for t in tokens if t in _ROMAN_HINDI) / len(tokens) >= 0.1
        return LanguageResult(code="hi-Latn" if has_hindi else "und", script="latin",
                              method="romanized_lexicon" if has_hindi else "implausible_detection", supported=False)
    return LanguageResult(code=lang, script=script or "unknown", method="langdetect",
                          supported=lang in SUPPORTED_MODEL_LANGUAGES)


# Backwards compatibility with free-text values stored by older imports.
LEGACY_LANGUAGE_NAMES = {"english": "en", "hindi": "hi"}
