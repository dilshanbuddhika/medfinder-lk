"""Text normalisation for medicine names and strengths.

Everything the substitution engine does depends on turning messy input
("Panadol 500MG", "panadol-500 mg", "PANADOL 0.5g") into one canonical form.
No database access here, so it stays fast and easy to unit test.
"""
import re
from decimal import Decimal

# Words that carry no identity — they describe the form, not the brand
NOISE_WORDS = {
    "tab", "tabs", "tablet", "tablets", "cap", "caps", "capsule", "capsules",
    "syp", "syrup", "susp", "suspension", "inj", "injection", "cream",
    "oint", "ointment", "drops", "drop", "inhaler",
}

# Different ways people write the same unit
UNIT_ALIASES = {
    "milligram": "mg", "milligrams": "mg", "mgs": "mg",
    "microgram": "mcg", "micrograms": "mcg", "ug": "mcg",
    "gram": "g", "grams": "g", "gm": "g", "gms": "g",
    "millilitre": "ml", "milliliter": "ml", "mls": "ml",
    "units": "iu", "unit": "iu",
}

# Convert everything into one base unit so 0.5g == 500mg
UNIT_CANON = {
    "mcg": ("mg", Decimal("0.001")),
    "mg":  ("mg", Decimal("1")),
    "g":   ("mg", Decimal("1000")),
    "ml":  ("ml", Decimal("1")),
    "iu":  ("iu", Decimal("1")),
    "%":   ("%",  Decimal("1")),
}

STRENGTH_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(mcg|ug|mg|mgs|g|gm|gms|ml|mls|iu|units?|%)\b",
    re.IGNORECASE,
)


def normalize_name(text):
    """Lowercase, strip punctuation, strengths and dosage-form words.

    >>> normalize_name("Panadol 500mg Tablet")
    'panadol'
    """
    if not text:
        return ""
    s = text.lower()
    s = STRENGTH_RE.sub(" ", s)        # remove "500mg"
    s = re.sub(r"[^\w\s]", " ", s)     # punctuation -> space
    s = re.sub(r"\d+", " ", s)         # any leftover numbers
    tokens = [t for t in s.split() if t and t not in NOISE_WORDS]
    return " ".join(tokens)


def parse_strength(text):
    """Pull the strength out and convert it to a base unit.

    >>> parse_strength("Panadol 0.5 g")
    (Decimal('500.000'), 'mg')
    """
    if not text:
        return None
    m = STRENGTH_RE.search(text)
    if not m:
        return None
    raw_value = m.group(1).replace(",", ".")
    raw_unit = m.group(2).lower()
    unit = UNIT_ALIASES.get(raw_unit, raw_unit)
    if unit not in UNIT_CANON:
        return None
    canon_unit, factor = UNIT_CANON[unit]
    value = (Decimal(raw_value) * factor).quantize(Decimal("0.001"))
    return value, canon_unit


def build_equivalence_key(ingredient_strengths, dosage_form):
    """Build the signature two interchangeable medicines share.

    ingredient_strengths: list of (normalized_name, Decimal value, unit)
    """
    parts = sorted(
        f"{name}:{value:.3f}{unit}" for name, value, unit in ingredient_strengths
    )
    return f"{'+'.join(parts)}|{dosage_form}"