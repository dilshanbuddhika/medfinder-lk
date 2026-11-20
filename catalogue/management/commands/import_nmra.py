"""Import the NMRA Maximum Retail Prices PDF into the medicine catalogue.

    python manage.py import_nmra data/nmra_mrp.pdf --dry-run
    python manage.py import_nmra data/nmra_mrp.pdf

Source: National Medicines Regulatory Authority, "Maximum Retail Prices of
Medicines", published 17 November 2025. The table gives generic name, dosage
form, strength, brand name, manufacturer, market authorization holder and the
maximum retail price per unit.

The PDF is a ruled table. pdfplumber's own table detection drops the first
data row of every page (it sits above the topmost ruling line), so this
command rebuilds rows itself from word positions and the table's ruling lines.
"""
import re
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from catalogue.models import (
    ActiveIngredient,
    DosageForm,
    Medicine,
    MedicineIngredient,
    StrengthUnit,
)

# --------------------------------------------------------------------------
# PDF extraction
# --------------------------------------------------------------------------

# Column boundaries, read off the PDF's own vertical ruling lines
X_BOUNDS = [69, 102, 198, 264, 334, 418, 532, 610, 760]
N_COLS = len(X_BOUNDS) - 1
FIELDS = ["no", "generic", "form", "strength", "brand", "manufacturer", "mah", "price"]


def _column_of(x):
    for i in range(N_COLS):
        if X_BOUNDS[i] <= x < X_BOUNDS[i + 1]:
            return i
    return None


def _row_bands(page, min_width=60, tol=2.5):
    """Row boundaries, taken from the table's horizontal ruling lines."""
    ys = sorted({
        round(e["top"], 1)
        for e in page.edges
        if e["orientation"] == "h" and (e["x1"] - e["x0"]) > min_width
    })
    bands = []
    for y in ys:
        if bands and y - bands[-1] <= tol:
            continue
        bands.append(y)
    return bands


def extract_rows(pdf_path):
    """Yield one dict per product row, with cells joined in reading order."""
    import pdfplumber

    rows = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            bands = _row_bands(page)
            if len(bands) < 2:
                continue

            words = page.extract_words(keep_blank_chars=False, use_text_flow=False)
            if not words:
                continue

            # The first data row of a page sits above the topmost ruling line.
            top_guard = min(w["top"] for w in words) - 1
            if top_guard < bands[0] - 3:
                bands = [top_guard] + bands

            cells = [[[] for _ in range(N_COLS)] for _ in range(len(bands) - 1)]
            for w in words:
                col = _column_of((w["x0"] + w["x1"]) / 2)
                if col is None:
                    continue
                y = (w["top"] + w["bottom"]) / 2
                for b in range(len(bands) - 1):
                    if bands[b] <= y < bands[b + 1]:
                        cells[b][col].append((w["top"], w["x0"], w["text"]))
                        break

            for band in cells:
                values = []
                for col in band:
                    col.sort(key=lambda t: (round(t[0], 0), t[1]))
                    text = " ".join(t[2] for t in col)
                    values.append(re.sub(r"\s+", " ", text).strip())
                if re.fullmatch(r"\d{1,4}", values[0]):
                    rows.append(dict(zip(FIELDS, values)))
    return rows


# --------------------------------------------------------------------------
# Normalisation
# --------------------------------------------------------------------------

# Release profile and route qualifiers, checked before the base form
FORM_QUALIFIERS = [
    (r"gastro[\s-]*resistant|delayed[\s-]*release", "_dr"),
    (r"sustained|extended|controlled|modified|depot", "_mr"),
    (r"chewable", "_chew"),
    (r"dispersible", "_disp"),
    (r"vaginal", "_vag"),
    (r"soft\s*gelatin", "_soft"),
    (r"pre[\s-]*filled", "_pfs"),
]

FORM_BASES = [
    (r"\btablets?\b", "tablet"),
    (r"\bcapsules?\b", "capsule"),
    (r"\binfusion\b", "infusion"),
    (r"\binjection\b", "injection"),
    (r"\bvaccine\b", "vaccine"),
    (r"\bsyrup\b", "syrup"),
    (r"oral\s+solution", "oral_solution"),
    (r"oral\s+suspension", "oral_suspension"),
    (r"oral\s+drops?", "oral_drops"),
    (r"nebuli[sz]er|respirator\s+solution", "nebuliser"),
    (r"inhal", "inhalation"),
    (r"nasal\s+spray", "nasal_spray"),
    (r"eye\s*/\s*ear\s+drops?", "eye_ear_drops"),
    (r"eye\s+drops?", "eye_drops"),
    (r"ear\s+drops?", "ear_drops"),
    (r"\bointment\b", "ointment"),
    (r"\bcream\b", "cream"),
    (r"\bgel\b", "gel"),
    (r"\bpessary\b", "pessary"),
    (r"\bsuppositor", "suppository"),
    (r"\bsuspension\b", "suspension"),
    (r"\bsolution\b", "solution"),
]

VALID_FORMS = {c for c, _ in DosageForm.choices}


def canonical_form(text):
    """'Tablet (sustained release)' -> 'tablet_mr'."""
    t = (text or "").lower().strip()
    if not t or t == "-":
        return DosageForm.OTHER
    base = DosageForm.OTHER
    for pattern, name in FORM_BASES:
        if re.search(pattern, t):
            base = name
            break
    for pattern, suffix in FORM_QUALIFIERS:
        if re.search(pattern, t):
            combined = f"{base}{suffix}"
            return combined if combined in VALID_FORMS else base
    return base


# Everything is reduced to one base unit so 0.5 g and 500 mg collide
UNIT_TO_BASE = {
    "mcg": ("mg", Decimal("0.001")),
    "ug": ("mg", Decimal("0.001")),
    "mg": ("mg", Decimal("1")),
    "g": ("mg", Decimal("1000")),
    "iu": ("iu", Decimal("1")),
    "ml": ("ml", Decimal("1")),
    "l": ("ml", Decimal("1000")),
    "%": ("%", Decimal("1")),
}

_NUM = r"(\d[\d,]*(?:\.\d+)?)"
_UNIT = r"(mcg|ug|mg|g|iu|ml|l|%)"
RE_RATIO = re.compile(_NUM + r"\s*" + _UNIT + r"\s*(?:i\s*)?/\s*" + _NUM + r"?\s*" + _UNIT,
                      re.IGNORECASE)
RE_SIMPLE = re.compile(_NUM + r"\s*" + _UNIT, re.IGNORECASE)

CONCENTRATION_UNITS = {("mg", "ml"): StrengthUnit.MG_PER_ML,
                       ("iu", "ml"): StrengthUnit.IU_PER_ML}


def _decimal(text):
    try:
        return Decimal(text.replace(",", ""))
    except (InvalidOperation, AttributeError):
        return None


def repair_digits(text):
    """The source PDF contains '5O mg' — a letter O typed for a zero."""
    return re.sub(r"(?<=\d)[Oo](?=\s*(?:mg|mcg|ml|g|iu|%))", "0", text or "")


def parse_strength(text):
    """Return (Decimal value, unit) or None.

    '500 mg'     -> (500.000, 'mg')
    '0.5 g'      -> (500.000, 'mg')
    '100mg/5mL'  -> (20.000, 'mg/ml')   concentration, reduced to per 1 mL
    '-'          -> None
    """
    t = repair_digits((text or "").strip())
    if not t or t == "-":
        return None

    match = RE_RATIO.search(t)
    if match:
        v1, u1, v2, u2 = match.group(1), match.group(2).lower(), match.group(3), match.group(4).lower()
        if u1 in UNIT_TO_BASE and u2 in UNIT_TO_BASE:
            base1, factor1 = UNIT_TO_BASE[u1]
            base2, factor2 = UNIT_TO_BASE[u2]
            amount = _decimal(v1)
            per = _decimal(v2) if v2 else Decimal(1)
            unit = CONCENTRATION_UNITS.get((base1, base2))
            if unit and amount is not None and per:
                value = (amount * factor1) / (per * factor2)
                return value.quantize(Decimal("0.001")), unit

    match = RE_SIMPLE.search(t)
    if match:
        value, unit = match.group(1), match.group(2).lower()
        if unit in UNIT_TO_BASE:
            base, factor = UNIT_TO_BASE[unit]
            amount = _decimal(value)
            if amount is not None and base in {u for u, _ in StrengthUnit.choices}:
                return (amount * factor).quantize(Decimal("0.001")), base
    return None


RE_PRICE = re.compile(r"(\d[\d,]*(?:\.\d+)?)")


def parse_price(text):
    """The first number is the retail price.

    Rows that quote two prices read '5.85/Tablet (Blister) 4.50/Tablet (Bulk)'.
    Blister is what a patient pays over the counter, so the first number wins.
    """
    match = RE_PRICE.search(text or "")
    return _decimal(match.group(1)) if match else None


def parse_price_unit(text):
    """The '/ Tablet' or '/ 5 mL' part, kept for display."""
    match = re.search(r"/\s*([^(,\n]+)", text or "")
    return re.sub(r"\s+", " ", match.group(1)).strip()[:50] if match else ""


def clean_ingredient_name(text):
    """'Paclitaxel(Protein bound particles)' -> 'Paclitaxel'."""
    t = re.sub(r"\(.*?\)", " ", text or "")
    t = re.sub(r"\b(?:BP|USP|IP)\b", " ", t, flags=re.IGNORECASE)
    t = re.sub(r"\s+", " ", t).strip(" ,.-")
    return t


# --------------------------------------------------------------------------
# Command
# --------------------------------------------------------------------------

class Command(BaseCommand):
    help = "Import the NMRA Maximum Retail Prices PDF into the medicine catalogue."

    def add_arguments(self, parser):
        parser.add_argument("pdf", help="Path to the NMRA MRP PDF")
        parser.add_argument("--dry-run", action="store_true",
                            help="Parse and report, write nothing")
        parser.add_argument("--limit", type=int, default=0,
                            help="Only process the first N rows")

    def handle(self, *args, **options):
        try:
            import pdfplumber  # noqa: F401
        except ImportError:
            raise CommandError("pdfplumber is not installed. Run: pip install pdfplumber")

        path = options["pdf"]
        rows = extract_rows(path)
        if not rows:
            raise CommandError(f"No table rows found in {path}. Is this the NMRA MRP PDF?")

        if options["limit"]:
            rows = rows[: options["limit"]]

        self.stdout.write(f"Parsed {len(rows)} rows from {path}")

        created_ingredients = created_medicines = updated_medicines = 0
        skipped = []

        with transaction.atomic():
            for row in rows:
                ingredient_name = clean_ingredient_name(row["generic"])
                strength = parse_strength(row["strength"])
                brand = row["brand"].strip()
                form = canonical_form(row["form"])
                price = parse_price(row["price"])

                if not ingredient_name or not brand:
                    skipped.append((row["no"], "missing name or brand", row["generic"]))
                    continue
                if strength is None:
                    # Vaccines and multivitamins carry no comparable strength,
                    # so they cannot take part in substitution. Record and move on.
                    skipped.append((row["no"], "unparsed strength", row["strength"]))
                    continue

                value, unit = strength

                ingredient, made = ActiveIngredient.objects.get_or_create(
                    name=ingredient_name
                )
                created_ingredients += int(made)

                # A brand can be marketed at several strengths (LIPITOR 10 mg
                # and LIPITOR 40 mg are different products), so the strength
                # has to be part of the identity, not just brand and form.
                medicine = Medicine.objects.filter(
                    brand_name=brand,
                    dosage_form=form,
                    medicine_ingredients__ingredient=ingredient,
                    medicine_ingredients__strength_value=value,
                    medicine_ingredients__strength_unit=unit,
                ).first()

                if medicine is None:
                    medicine = Medicine.objects.create(
                        brand_name=brand,
                        dosage_form=form,
                        manufacturer=row["manufacturer"][:200],
                        max_retail_price=price,
                        price_unit=parse_price_unit(row["price"]),
                    )
                    MedicineIngredient.objects.create(
                        medicine=medicine,
                        ingredient=ingredient,
                        strength_value=value,
                        strength_unit=unit,
                    )
                    created_medicines += 1
                else:
                    # Same product listed again at another pack size. Keep the
                    # smallest pack's price, which is the one a patient is most
                    # likely to be quoted.
                    if price is not None and (
                        medicine.max_retail_price is None
                        or price < medicine.max_retail_price
                    ):
                        medicine.max_retail_price = price
                        medicine.price_unit = parse_price_unit(row["price"])
                    medicine.manufacturer = row["manufacturer"][:200]
                    medicine.save(update_fields=["manufacturer", "max_retail_price",
                                                 "price_unit", "normalized_name"])
                    updated_medicines += 1

                medicine.refresh_equivalence_key()

            if options["dry_run"]:
                transaction.set_rollback(True)

        self.stdout.write("")
        self.stdout.write(f"  ingredients created : {created_ingredients}")
        self.stdout.write(f"  medicines created   : {created_medicines}")
        self.stdout.write(f"  medicines updated   : {updated_medicines}")
        self.stdout.write(f"  rows skipped        : {len(skipped)}")

        if skipped:
            self.stdout.write("")
            self.stdout.write("Skipped rows:")
            for no, reason, detail in skipped:
                self.stdout.write(f"  #{no:<4} {reason:<20} {detail[:50]}")

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("\nDry run — nothing was written."))
        else:
            self.stdout.write(self.style.SUCCESS("\nImport complete."))
