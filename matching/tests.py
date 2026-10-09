from decimal import Decimal

from django.test import SimpleTestCase

from .normalize import build_equivalence_key, normalize_name, parse_strength


class NormalizeNameTests(SimpleTestCase):
    def test_strips_strength_and_form(self):
        self.assertEqual(normalize_name("Panadol 500mg Tablet"), "panadol")

    def test_strips_punctuation_and_case(self):
        self.assertEqual(normalize_name("PANADOL-500 mg"), "panadol")

    def test_keeps_multiword_brand(self):
        self.assertEqual(normalize_name("Augmentin Duo 625mg tabs"), "augmentin duo")

    def test_empty_input(self):
        self.assertEqual(normalize_name(""), "")


class ParseStrengthTests(SimpleTestCase):
    def test_milligrams(self):
        self.assertEqual(parse_strength("Panadol 500mg"), (Decimal("500.000"), "mg"))

    def test_grams_convert_to_mg(self):
        self.assertEqual(parse_strength("Panadol 0.5 g"), (Decimal("500.000"), "mg"))

    def test_micrograms_convert_to_mg(self):
        self.assertEqual(parse_strength("Salbutamol 100mcg"), (Decimal("0.100"), "mg"))

    def test_no_strength_present(self):
        self.assertIsNone(parse_strength("Panadol"))


class EquivalenceKeyTests(SimpleTestCase):
    def test_single_ingredient(self):
        key = build_equivalence_key([("paracetamol", Decimal("500"), "mg")], "tablet")
        self.assertEqual(key, "paracetamol:500.000mg|tablet")

    def test_combination_is_order_independent(self):
        a = build_equivalence_key([
            ("amoxicillin", Decimal("500"), "mg"),
            ("clavulanic acid", Decimal("125"), "mg"),
        ], "tablet")
        b = build_equivalence_key([
            ("clavulanic acid", Decimal("125"), "mg"),
            ("amoxicillin", Decimal("500"), "mg"),
        ], "tablet")
        self.assertEqual(a, b)

    def test_dosage_form_separates_groups(self):
        tab = build_equivalence_key([("paracetamol", Decimal("500"), "mg")], "tablet")
        syp = build_equivalence_key([("paracetamol", Decimal("500"), "mg")], "syrup")
        self.assertNotEqual(tab, syp)

    def test_different_strength_separates_groups(self):
        a = build_equivalence_key([("paracetamol", Decimal("500"), "mg")], "tablet")
        b = build_equivalence_key([("paracetamol", Decimal("250"), "mg")], "tablet")
        self.assertNotEqual(a, b)

from decimal import Decimal as D

from django.test import TestCase

from catalogue.models import (
    ActiveIngredient, DosageForm, Medicine, MedicineIngredient, StrengthUnit,
)

from .engine import resolve, substitutes


class ResolveTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        para = ActiveIngredient.objects.create(name="Paracetamol")

        def make(brand, strength, price):
            m = Medicine.objects.create(
                brand_name=brand, dosage_form=DosageForm.TABLET,
                max_retail_price=price,
            )
            MedicineIngredient.objects.create(
                medicine=m, ingredient=para,
                strength_value=D(strength), strength_unit=StrengthUnit.MG,
            )
            m.refresh_equivalence_key()
            return m

        cls.panadol = make("Panadol", "500", 15)
        cls.setamol = make("Setamol", "500", 8)
        cls.calpol = make("Calpol", "250", 10)

    def test_exact_brand_match(self):
        r = resolve("Panadol")
        self.assertEqual(r.medicine, self.panadol)
        self.assertEqual(r.method, "exact")

    def test_case_and_noise_insensitive(self):
        self.assertEqual(resolve("PANADOL 500mg tablet").medicine, self.panadol)

    def test_typo_resolves_via_fuzzy(self):
        r = resolve("panadl")
        self.assertEqual(r.medicine, self.panadol)
        self.assertEqual(r.method, "fuzzy")

    def test_unknown_text_returns_nothing(self):
        self.assertIsNone(resolve("xyzzy").medicine)

    def test_generic_name_picks_cheapest(self):
        r = resolve("paracetamol 500mg")
        self.assertEqual(r.medicine, self.setamol)

    def test_strength_narrows_the_match(self):
        self.assertEqual(resolve("Paracetamol 250mg").medicine, self.calpol)


class SubstituteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ResolveTests.setUpTestData.__func__(cls)

    def test_same_strength_and_form_are_interchangeable(self):
        self.assertEqual(list(substitutes(self.panadol)), [self.setamol])

    def test_different_strength_is_not_a_substitute(self):
        self.assertEqual(list(substitutes(self.calpol)), [])

    def test_include_self_orders_by_price(self):
        got = list(substitutes(self.panadol, include_self=True))
        self.assertEqual(got, [self.setamol, self.panadol])