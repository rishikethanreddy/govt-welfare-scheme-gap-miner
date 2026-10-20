"""
State name normalization against the reference list of states and union territories.

Only names supplied explicitly by a source are normalized; nothing is inferred
from other text. Unrecognized values are kept verbatim (not discarded) so they
remain visible in data-quality reports.
"""

import re
from typing import Optional

STATES_AND_UTS = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat", "Haryana",
    "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur",
    "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana",
    "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal",
    "Andaman and Nicobar Islands", "Chandigarh", "Dadra and Nagar Haveli and Daman and Diu", "Delhi",
    "Jammu and Kashmir", "Ladakh", "Lakshadweep", "Puducherry",
]

_ALIASES = {
    "orissa": "Odisha", "uttaranchal": "Uttarakhand", "pondicherry": "Puducherry", "nct of delhi": "Delhi",
    "new delhi": "Delhi", "delhi ncr": "Delhi", "j&k": "Jammu and Kashmir", "j and k": "Jammu and Kashmir",
    "jammu & kashmir": "Jammu and Kashmir", "andaman and nicobar": "Andaman and Nicobar Islands",
    "andaman & nicobar islands": "Andaman and Nicobar Islands", "a&n islands": "Andaman and Nicobar Islands",
    "dadra and nagar haveli": "Dadra and Nagar Haveli and Daman and Diu",
    "daman and diu": "Dadra and Nagar Haveli and Daman and Diu", "dnhdd": "Dadra and Nagar Haveli and Daman and Diu",
    "up": "Uttar Pradesh", "mp": "Madhya Pradesh", "tn": "Tamil Nadu", "wb": "West Bengal", "ap": "Andhra Pradesh",
    "chattisgarh": "Chhattisgarh", "telengana": "Telangana", "jharkand": "Jharkhand", "orrisa": "Odisha",
    "pondichery": "Puducherry", "uttaranchal pradesh": "Uttarakhand", "the dadra and nagar haveli and daman and diu": "Dadra and Nagar Haveli and Daman and Diu",
}
_BY_KEY = {re.sub(r"[^a-z]", "", s.lower()): s for s in STATES_AND_UTS}


def normalize_state(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    raw = re.sub(r"\s+", " ", str(name)).strip()
    if raw.lower() in ("unknown", "na", "n/a", "none", "-", "", "all india", "india"):
        return None
    low = raw.lower()
    if low in _ALIASES:
        return _ALIASES[low]
    key = re.sub(r"[^a-z]", "", low.replace("&", "and"))
    return _BY_KEY.get(key, raw)
