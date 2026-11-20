"""Text normalisation for medicine names and strengths.

Everything the substitution engine does depends on turning messy input
("Panadol 500MG", "panadol-500 mg", "PANADOL 0.5g") into one canonical form.
No database access here, so it stays fast and easy to unit test.
"""
import re
from decimal import Decimal, InvalidOperation

# Words that carry no identity — they describe the form, not the brand
NOISE_WORDS = {
    "tab", "tabs", "tablet", "tablets", "cap", "caps", "capsule", "capsules",
    "syp", "syrup", "susp", "suspension", "inj", "injection", "cream",
    "oint", "ointment", "drops", "drop", "inhaler", "infusion", "vial",
}

# Different ways people write the same unit
UNIT_ALIASES = {
    "milligram": "mg", "milligrams": "mg", "mgs": "mg",
    "microgram": "mcg", "micrograms": "mcg", "ug": "mcg",
    "gram": "g", "grams": "g", "gm": "g", "gms": "g",
    "millilitre": "ml", "milliliter": "ml", "mls": "ml",
    "units": "iu", "unit": "iu",
}

# Convert everything into one base unit so 0.5 g == 500 mg
UNIT_CANON = {
    "mcg": ("mg", Decimal("0.001")),
    "mg": ("mg", Decimal("1")),
    "g": ("mg", Decimal("1000")),
    "ml": ("ml", Decimal("1")),
    "l": ("ml", Decimal("1000")),
    "iu": ("iu", Decimal("1")),
    "%": ("%", Decimal("1")),
}

# Concentrations the catalogue can store, as (numerator, denominator)
CONCENTRATION_UNITS = {("mg", "ml"): "mg/ml", ("iu", "ml"): "iu/ml"}

_NUM = r"(\d[\d,]*(?:\.\d+)?)"
_UNIT = r"(mcg|ug|mg|mgs|g|gm|gms|ml|mls|l|iu|units?|%)"

STRENGTH_RE = re.compile(_NUM + r"\s*" + _UNIT + r"\b", re.IGNORECASE)
RATIO_RE = re.compile(
    _NUM + r"\s*" + _UNIT + r"\s*(?:i\s*)?/\s*" + _NUM + r"?\s*" + _UNIT,
    re.IGNORECASE,
)


def _decimal(text):
    try:
        return Decimal(text.replace(",", ""))
    except (InvalidOperation, AttributeError):
        return None


def repair_digits(text):
    """Source documents sometimes contain '5O mg' — a letter O typed for zero."""
    return re.sub(r"(?<=\d)[Oo](?=\s*(?:mg|mcg|ml|g|iu|%))", "0", text or "")


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
    >>> parse_strength("Amikacin 100mg/5mL")
    (Decimal('20.000'), 'mg/ml')
    """
    t = repair_digits((text or "").strip())
    if not t or t == "-":
        return None

    # A concentration first: "100mg/5mL" must not be read as plain "100mg"
    m = RATIO_RE.search(t)
    if m:
        raw_v1, raw_u1 = m.group(1), m.group(2).lower()
        raw_v2, raw_u2 = m.group(3), m.group(4).lower()
        u1 = UNIT_ALIASES.get(raw_u1, raw_u1)
        u2 = UNIT_ALIASES.get(raw_u2, raw_u2)
        if u1 in UNIT_CANON and u2 in UNIT_CANON:
            base1, factor1 = UNIT_CANON[u1]
            base2, factor2 = UNIT_CANON[u2]
            unit = CONCENTRATION_UNITS.get((base1, base2))
            amount = _decimal(raw_v1)
            per = _decimal(raw_v2) if raw_v2 else Decimal(1)
            if unit and amount is not None and per:
                value = (amount * factor1) / (per * factor2)
                return value.quantize(Decimal("0.001")), unit

    m = STRENGTH_RE.search(t)
    if m:
        raw_value, raw_unit = m.group(1), m.group(2).lower()
        unit = UNIT_ALIASES.get(raw_unit, raw_unit)
        if unit in UNIT_CANON:
            base, factor = UNIT_CANON[unit]
            amount = _decimal(raw_value)
            if amount is not None:
                return (amount * factor).quantize(Decimal("0.001")), base
    return None


def build_equivalence_key(ingredient_strengths, dosage_form):
    """Build the signature two interchangeable medicines share.

    ingredient_strengths: list of (normalized_name, Decimal value, unit)
    """
    parts = sorted(
        f"{name}:{value:.3f}{unit}" for name, value, unit in ingredient_strengths
    )
    return f"{'+'.join(parts)}|{dosage_form}"
