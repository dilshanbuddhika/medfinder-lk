from django.db import models


class DosageForm(models.TextChoices):
    """Canonical dosage forms.

    The release profile is part of the form, not a separate attribute: a plain
    tablet and a sustained-release tablet of the same drug and strength are NOT
    interchangeable, so they must never share an equivalence key.
    """

    TABLET = "tablet", "Tablet"
    TABLET_DR = "tablet_dr", "Tablet (delayed / gastro-resistant)"
    TABLET_MR = "tablet_mr", "Tablet (modified / sustained release)"
    TABLET_CHEW = "tablet_chew", "Tablet (chewable)"
    TABLET_DISP = "tablet_disp", "Tablet (dispersible)"
    TABLET_VAG = "tablet_vag", "Tablet (vaginal)"

    CAPSULE = "capsule", "Capsule"
    CAPSULE_DR = "capsule_dr", "Capsule (delayed release)"
    CAPSULE_SOFT = "capsule_soft", "Capsule (soft gelatin)"

    INJECTION = "injection", "Injection"
    INJECTION_MR = "injection_mr", "Injection (depot)"
    INJECTION_PFS = "injection_pfs", "Injection (pre-filled syringe / pen)"
    INFUSION = "infusion", "Infusion"
    VACCINE = "vaccine", "Vaccine"

    SYRUP = "syrup", "Syrup"
    ORAL_SOLUTION = "oral_solution", "Oral solution"
    ORAL_SUSPENSION = "oral_suspension", "Oral suspension"
    ORAL_DROPS = "oral_drops", "Oral drops"
    SUSPENSION = "suspension", "Suspension"
    SOLUTION = "solution", "Solution"

    INHALATION = "inhalation", "Inhaler / inhalation"
    NEBULISER = "nebuliser", "Nebuliser solution"
    NASAL_SPRAY = "nasal_spray", "Nasal spray"

    EYE_DROPS = "eye_drops", "Eye drops"
    EAR_DROPS = "ear_drops", "Ear drops"
    EYE_EAR_DROPS = "eye_ear_drops", "Eye / ear drops"

    CREAM = "cream", "Cream"
    OINTMENT = "ointment", "Ointment"
    GEL = "gel", "Gel"
    GEL_VAG = "gel_vag", "Gel (vaginal)"

    PESSARY = "pessary", "Pessary"
    SUPPOSITORY = "suppository", "Suppository"

    OTHER = "other", "Other"


class StrengthUnit(models.TextChoices):
    """Base units only.

    Everything is converted on import: mcg and g become mg, L becomes mL, and
    a concentration such as 100 mg/5 mL is reduced to 20 mg/mL. Two products
    written differently then compare equal.
    """

    MG = "mg", "mg"
    ML = "ml", "mL"
    IU = "iu", "IU"
    PERCENT = "%", "%"
    MG_PER_ML = "mg/ml", "mg/mL"
    IU_PER_ML = "iu/ml", "IU/mL"


class ActiveIngredient(models.Model):
    """The generic (INN) name — e.g. Paracetamol, Metformin hydrochloride."""

    name = models.CharField(max_length=200, unique=True)
    normalized_name = models.CharField(max_length=200, db_index=True, blank=True)
    atc_code = models.CharField(max_length=10, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Medicine(models.Model):
    """One marketed product (brand) — e.g. Panadol 500mg Tablet."""

    brand_name = models.CharField(max_length=200)
    normalized_name = models.CharField(max_length=200, db_index=True, blank=True)
    nmra_reg_no = models.CharField(max_length=50, blank=True, db_index=True)
    dosage_form = models.CharField(max_length=20, choices=DosageForm.choices)
    manufacturer = models.CharField(max_length=200, blank=True)
    max_retail_price = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="NMRA published MRP in LKR, where price-controlled",
    )
    price_unit = models.CharField(
        max_length=50, blank=True,
        help_text="What the MRP is per — 'Tablet', '5 mL', 'Vial'. Prices are "
                  "only comparable between products sharing this unit.",
    )
    equivalence_key = models.CharField(max_length=255, db_index=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    ingredients = models.ManyToManyField(
        ActiveIngredient, through="MedicineIngredient", related_name="medicines"
    )

    class Meta:
        ordering = ["brand_name"]
        indexes = [models.Index(fields=["equivalence_key", "is_active"])]

    def __str__(self):
        return f"{self.brand_name} ({self.get_dosage_form_display()})"

    def build_equivalence_key(self):
        """Signature shared by every interchangeable product."""
        from matching.normalize import build_equivalence_key as build_key

        parts = [
            (mi.ingredient.normalized_name, mi.strength_value, mi.strength_unit)
            for mi in self.medicine_ingredients.select_related("ingredient")
        ]
        return build_key(parts, self.dosage_form)

    def refresh_equivalence_key(self):
        """Recompute and save. Call after ingredients change."""
        self.equivalence_key = self.build_equivalence_key()
        Medicine.objects.filter(pk=self.pk).update(equivalence_key=self.equivalence_key)
        return self.equivalence_key


class MedicineIngredient(models.Model):
    """Links a medicine to an ingredient WITH its strength."""

    medicine = models.ForeignKey(
        Medicine, on_delete=models.CASCADE, related_name="medicine_ingredients"
    )
    ingredient = models.ForeignKey(ActiveIngredient, on_delete=models.PROTECT)
    strength_value = models.DecimalField(max_digits=12, decimal_places=3)
    strength_unit = models.CharField(max_length=10, choices=StrengthUnit.choices)

    class Meta:
        unique_together = [("medicine", "ingredient")]

    def __str__(self):
        return f"{self.ingredient.name} {self.strength_value}{self.strength_unit}"
