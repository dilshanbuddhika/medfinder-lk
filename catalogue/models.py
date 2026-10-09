from django.db import models


class DosageForm(models.TextChoices):
    TABLET = "tablet", "Tablet"
    CAPSULE = "capsule", "Capsule"
    SYRUP = "syrup", "Syrup"
    SUSPENSION = "suspension", "Suspension"
    INJECTION = "injection", "Injection"
    CREAM = "cream", "Cream / ointment"
    DROPS = "drops", "Drops"
    INHALER = "inhaler", "Inhaler"
    OTHER = "other", "Other"


class StrengthUnit(models.TextChoices):
    MG = "mg", "mg"
    ML = "ml", "ml"
    IU = "iu", "IU"
    PERCENT = "%", "%"


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
        Medicine.objects.filter(pk=self.pk).update(
            equivalence_key=self.equivalence_key
        )
        return self.equivalence_key


class MedicineIngredient(models.Model):
    """Links a medicine to an ingredient WITH its strength."""

    medicine = models.ForeignKey(
        Medicine, on_delete=models.CASCADE, related_name="medicine_ingredients"
    )
    ingredient = models.ForeignKey(ActiveIngredient, on_delete=models.PROTECT)
    strength_value = models.DecimalField(max_digits=10, decimal_places=3)
    strength_unit = models.CharField(max_length=10, choices=StrengthUnit.choices)

    class Meta:
        unique_together = [("medicine", "ingredient")]

    def __str__(self):
        return f"{self.ingredient.name} {self.strength_value}{self.strength_unit}"