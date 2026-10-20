"""
Scheme registry and boundary-aware, multi-scheme detection.

Aliases are split into two strengths:
  strong — unambiguous names/acronyms (e.g. "pmfby", "fasal bima")
  weak   — generic phrases that usually, but not always, mean the scheme
           (e.g. "crop insurance", "solar pump"); used only when no strong
           alias for any scheme is present.

Matching uses token boundaries, so "apy" does not match "happy".
No numeric confidence is produced: a dictionary match is not a calibrated
probability, so the output reports match strength and the matched spans.
"""

import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

UNKNOWN_SCHEME = "Other / Unknown"


@dataclass(frozen=True)
class SchemeDefinition:
    code: str                 # canonical short name stored on documents
    name: str                 # full official name
    category: str
    ministry: str
    official_url: str
    strong: tuple = ()
    weak: tuple = ()
    # Regex fragments that, if found right after a strong alias, cancel the match
    # (e.g. "PM Kisan Maan-dhan" is a different scheme from PM-KISAN).
    exclusions: tuple = ()


DEFAULT_SCHEMES: list[SchemeDefinition] = [
    SchemeDefinition(
        "PM-KISAN", "Pradhan Mantri Kisan Samman Nidhi", "agriculture",
        "Ministry of Agriculture & Farmers Welfare", "https://pmkisan.gov.in/",
        strong=("pm-kisan", "pm kisan", "pmkisan", "pm kisaan", "kisan samman nidhi",
                "pradhan mantri kisan samman", "किसान सम्मान निधि", "पीएम किसान"),
        exclusions=(r"[\s-]*(?:maan|man)[\s-]?dhan", r"[\s-]*credit card"),
    ),
    SchemeDefinition(
        "PMFBY", "Pradhan Mantri Fasal Bima Yojana", "insurance",
        "Ministry of Agriculture & Farmers Welfare", "https://pmfby.gov.in/",
        strong=("pmfby", "fasal bima", "pradhan mantri fasal bima", "फसल बीमा"),
        weak=("crop insurance",),
    ),
    SchemeDefinition(
        "PM-KUSUM", "Pradhan Mantri Kisan Urja Suraksha evam Utthaan Mahabhiyan", "energy",
        "Ministry of New and Renewable Energy", "https://pmkusum.mnre.gov.in/",
        strong=("pm-kusum", "pm kusum", "pmkusum", "kusum yojana", "kusum scheme", "कुसुम"),
        weak=("solar pump", "solar pumps"),
    ),
    SchemeDefinition(
        "PMAY", "Pradhan Mantri Awas Yojana", "housing",
        "Ministry of Housing and Urban Affairs / Ministry of Rural Development", "https://pmaymis.gov.in/",
        strong=("pmay", "pmay-g", "pmay-u", "pmayg", "pradhan mantri awas", "pm awas", "awas yojana",
                "awaas yojana", "आवास योजना"),
        weak=("housing scheme", "housing for all"),
    ),
    SchemeDefinition(
        "Ayushman Bharat PM-JAY", "Ayushman Bharat – Pradhan Mantri Jan Arogya Yojana", "health",
        "Ministry of Health and Family Welfare", "https://pmjay.gov.in/",
        strong=("pm-jay", "pmjay", "pm jay", "ab-pmjay", "ayushman bharat", "ayushman card",
                "ayushman", "jan arogya", "आयुष्मान"),
    ),
    SchemeDefinition(
        "MGNREGA", "Mahatma Gandhi National Rural Employment Guarantee Act", "employment",
        "Ministry of Rural Development", "https://nrega.nic.in/",
        strong=("mgnrega", "mgnregs", "mgnregea", "mnrega", "nrega", "narega",
                "mahatma gandhi national rural employment", "मनरेगा", "नरेगा"),
        weak=("job card", "100 days work", "100 days of work"),
    ),
    SchemeDefinition(
        "PMJDY", "Pradhan Mantri Jan Dhan Yojana", "financial_inclusion",
        "Ministry of Finance", "https://pmjdy.gov.in/",
        strong=("pmjdy", "jan dhan", "jan-dhan", "jandhan", "जन धन"),
        weak=("zero balance account",),
    ),
    SchemeDefinition(
        "PMMY", "Pradhan Mantri Mudra Yojana", "credit",
        "Ministry of Finance", "https://www.mudra.org.in/",
        strong=("pmmy", "mudra loan", "mudra yojana", "pm mudra", "mudra scheme", "मुद्रा लोन", "mudra"),
        weak=("shishu loan", "kishore loan", "tarun loan"),
    ),
    SchemeDefinition(
        "PM SVANidhi", "PM Street Vendor's AtmaNirbhar Nidhi", "credit",
        "Ministry of Housing and Urban Affairs", "https://pmsvanidhi.mohua.gov.in/",
        strong=("svanidhi", "pm svanidhi", "sva nidhi", "pm-svanidhi"),
        weak=("street vendor", "street vendors"),
    ),
    SchemeDefinition(
        "APY", "Atal Pension Yojana", "pension",
        "Ministry of Finance", "https://www.npscra.nsdl.co.in/scheme-details.php",
        strong=("apy", "atal pension", "अटल पेंशन"),
    ),
    SchemeDefinition(
        "PMJJBY", "Pradhan Mantri Jeevan Jyoti Bima Yojana", "insurance",
        "Ministry of Finance", "https://jansuraksha.gov.in/",
        strong=("pmjjby", "jeevan jyoti", "jivan jyoti"),
    ),
    SchemeDefinition(
        "PMSBY", "Pradhan Mantri Suraksha Bima Yojana", "insurance",
        "Ministry of Finance", "https://jansuraksha.gov.in/",
        strong=("pmsby", "suraksha bima"),
    ),
    SchemeDefinition(
        "NSAP", "National Social Assistance Programme", "social_security",
        "Ministry of Rural Development", "https://nsap.nic.in/",
        strong=("nsap", "national social assistance", "ignoaps", "ignwps", "igndps"),
        weak=("old age pension", "widow pension", "disability pension"),
    ),
    SchemeDefinition(
        "PMUY", "Pradhan Mantri Ujjwala Yojana", "energy",
        "Ministry of Petroleum and Natural Gas", "https://www.pmuy.gov.in/",
        strong=("pmuy", "ujjwala", "ujjawala", "उज्ज्वला"),
        weak=("free gas connection", "free lpg connection"),
    ),
    SchemeDefinition(
        "PM Vishwakarma", "PM Vishwakarma", "livelihood",
        "Ministry of Micro, Small and Medium Enterprises", "https://pmvishwakarma.gov.in/",
        strong=("pm vishwakarma", "pm-vishwakarma", "vishwakarma yojana", "vishwakarma scheme"),
        weak=("vishwakarma",),
    ),
]

# Names seen in older imports / external datasets → canonical code.
LEGACY_NAME_MAP = {
    "pradhan mantri fasal bima yojana (pmfby)": "PMFBY",
    "pradhan mantri awas yojana (pmay)": "PMAY",
    "ayushman bharat - pm-jay": "Ayushman Bharat PM-JAY",
    "ayushman bharat pm-jay": "Ayushman Bharat PM-JAY",
    "pradhan mantri jan dhan yojana (pmjdy)": "PMJDY",
    "pradhan mantri mudra yojana (pmmy)": "PMMY",
    "atal pension yojana (apy)": "APY",
    "national social assistance programme (nsap)": "NSAP",
    "pradhan mantri ujjwala yojana (pmuy)": "PMUY",
}


@dataclass
class SchemeMatch:
    scheme: str
    alias: str
    start: int
    end: int
    strength: str  # strong | weak


@dataclass
class SchemeDetection:
    primary: Optional[str]
    schemes: list = field(default_factory=list)
    matches: list = field(default_factory=list)
    strength: Optional[str] = None

    @property
    def label(self) -> str:
        return self.primary or UNKNOWN_SCHEME

    def to_dict(self) -> dict:
        return {
            "primary": self.primary,
            "schemes": self.schemes,
            "strength": self.strength,
            "matches": [m.__dict__ for m in self.matches],
        }


def _alias_pattern(alias: str) -> str:
    # Separators inside an alias match any run of space/hyphen ("pm kisan" ~ "pm-kisan").
    parts = [re.escape(p) for p in re.split(r"[\s-]+", alias.strip()) if p]
    return r"[\s\-]*".join(parts)


class SchemeRegistry:
    """Compiled registry. Build from defaults, or from DB rows to pick up admin edits."""

    def __init__(self, definitions: Iterable[SchemeDefinition]):
        self.definitions = {d.code: d for d in definitions}
        self._compiled = []
        for d in self.definitions.values():
            for strength, aliases in (("strong", d.strong), ("weak", d.weak)):
                for alias in aliases:
                    # (?<!\w) / (?!\w) are Unicode-aware boundaries; they also work for
                    # Devanagari, where \b is unreliable around combining marks.
                    pat = r"(?<![\w])" + _alias_pattern(alias) + r"(?![\w])"
                    excl = re.compile("|".join(d.exclusions), re.IGNORECASE) if d.exclusions else None
                    self._compiled.append((d.code, alias, strength, re.compile(pat, re.IGNORECASE), excl))
        # Longer aliases first so overlapping spans prefer the most specific alias.
        self._compiled.sort(key=lambda t: -len(t[1]))

    @classmethod
    def default(cls) -> "SchemeRegistry":
        return cls(DEFAULT_SCHEMES)

    @classmethod
    def from_db(cls, db) -> "SchemeRegistry":
        """Defaults plus any active Scheme rows (extra aliases are treated as strong)."""
        from backend.app.models.scheme import Scheme
        defs = {d.code: d for d in DEFAULT_SCHEMES}
        try:
            rows = db.query(Scheme).filter(Scheme.active == True).all()  # noqa: E712
        except Exception:
            rows = []
        for row in rows:
            code = row.short_name or row.name
            base = defs.get(code)
            extra = tuple(a for a in row.alias_list if a)
            weak_extra = tuple(a.strip().lower() for a in (getattr(row, "weak_aliases", None) or "").split(",") if a.strip())
            if base:
                defs[code] = SchemeDefinition(
                    base.code, base.name, base.category, base.ministry, base.official_url,
                    strong=tuple(dict.fromkeys(base.strong + extra)),
                    weak=tuple(dict.fromkeys(base.weak + weak_extra)),
                    exclusions=base.exclusions,
                )
            else:
                defs[code] = SchemeDefinition(code, row.name, row.category or "other", row.ministry or "",
                                              row.official_url or "", strong=extra or (code.lower(),),
                                              weak=weak_extra)
        return cls(defs.values())

    def canonicalize(self, name: Optional[str]) -> Optional[str]:
        """Map a free-text scheme label (e.g. from a CSV) to a canonical code."""
        if not name or not str(name).strip():
            return None
        raw = str(name).strip()
        if raw in self.definitions:
            return raw
        low = raw.lower()
        if low in ("other", "unknown", "other / unknown", "other/unknown", "none", "n/a"):
            return None
        if low in LEGACY_NAME_MAP:
            return LEGACY_NAME_MAP[low]
        for code in self.definitions:
            if code.lower() == low:
                return code
        detected = self.detect(raw)
        return detected.primary or raw  # keep unrecognized labels verbatim rather than discarding them

    def detect(self, text: str) -> SchemeDetection:
        if not text:
            return SchemeDetection(primary=None)
        taken: list[tuple[int, int]] = []
        matches: list[SchemeMatch] = []
        for code, alias, strength, pattern, excl in self._compiled:
            for m in pattern.finditer(text):
                s, e = m.span()
                if any(s < te and e > ts for ts, te in taken):
                    continue
                if excl and excl.match(text, e):
                    continue
                taken.append((s, e))
                matches.append(SchemeMatch(code, alias, s, e, strength))

        strong = [m for m in matches if m.strength == "strong"]
        used = strong or [m for m in matches if m.strength == "weak"]
        if not used:
            return SchemeDetection(primary=None)

        stats: dict[str, list] = {}
        for m in used:
            stats.setdefault(m.scheme, []).append(m.start)
        # Most mentions first; ties broken by earliest mention.
        ordered = sorted(stats, key=lambda c: (-len(stats[c]), min(stats[c])))
        used.sort(key=lambda m: m.start)
        return SchemeDetection(primary=ordered[0], schemes=ordered, matches=used,
                               strength="strong" if strong else "weak")


_default_registry: Optional[SchemeRegistry] = None


def default_registry() -> SchemeRegistry:
    global _default_registry
    if _default_registry is None:
        _default_registry = SchemeRegistry.default()
    return _default_registry
