"""Resolve free text to a catalogue Medicine, then find its substitutes.

Pipeline: input -> normalise -> exact match -> fuzzy match -> equivalence group
"""
from dataclasses import dataclass, field

from django.db.models import Q
from rapidfuzz import fuzz, process

from catalogue.models import Medicine

from .normalize import normalize_name, parse_strength

FUZZY_THRESHOLD = 85  # 0-100. Tune against pharmacist-validated data later.


@dataclass
class Resolution:
    """What the engine concluded about the user's text."""

    medicine: Medicine | None
    score: float
    method: str                  # "exact" | "fuzzy" | "none"
    candidates: list = field(default_factory=list)


def _apply_strength_filter(qs, text):
    """Narrow by strength when the user gave one, so 500mg != 1g."""
    parsed = parse_strength(text)
    if not parsed:
        return qs
    value, unit = parsed
    return qs.filter(
        medicine_ingredients__strength_value=value,
        medicine_ingredients__strength_unit=unit,
    )


def resolve(text, limit=5):
    """Turn user text into a Medicine.

    Never guesses silently: a weak match comes back as candidates for the
    user to confirm rather than being chosen automatically.
    """
    norm = normalize_name(text)
    if not norm:
        return Resolution(None, 0.0, "none")

    base = Medicine.objects.filter(is_active=True)

    # 1. Exact match on the normalised name
    exact = _apply_strength_filter(base.filter(normalized_name=norm), text).distinct()
    hit = exact.first()
    if hit:
        return Resolution(hit, 100.0, "exact")

        # 1b. Exact match on an ingredient (generic) name — prescriptions often
    # name the ingredient, not a brand.
    by_ingredient = _apply_strength_filter(
        base.filter(ingredients__normalized_name=norm), text
    ).distinct().order_by("max_retail_price")
    hit = by_ingredient.first()
    if hit:
        return Resolution(hit, 100.0, "exact", list(by_ingredient[1:6]))

    # 2. Fuzzy match — shortlist cheaply in SQL, then score in Python
    head = norm.split()[0][:4]
    shortlist = list(
        base.filter(
            Q(normalized_name__icontains=head) | Q(brand_name__icontains=head)
        ).distinct()[:400]
    )
    if not shortlist:
        shortlist = list(base[:2000])

    scored = process.extract(
        norm,
        {m.pk: m.normalized_name for m in shortlist},
        scorer=fuzz.WRatio,
        limit=limit,
    )
    by_pk = {m.pk: m for m in shortlist}
    ranked = [(by_pk[pk], score) for _, score, pk in scored]

    if ranked and ranked[0][1] >= FUZZY_THRESHOLD:
        return Resolution(ranked[0][0], ranked[0][1], "fuzzy", ranked[1:])

    return Resolution(None, ranked[0][1] if ranked else 0.0, "none", ranked)


def substitutes(medicine, include_self=False):
    """Every marketed product interchangeable with this one.

    Interchangeable = identical active ingredient(s), strength and dosage form.
    This is an information lookup, not a clinical recommendation.
    """
    key = medicine.equivalence_key or medicine.build_equivalence_key()
    qs = Medicine.objects.filter(equivalence_key=key, is_active=True)
    if not include_self:
        qs = qs.exclude(pk=medicine.pk)
    return qs.order_by("max_retail_price", "brand_name")