from django.contrib import admin

from .models import ActiveIngredient, Medicine, MedicineIngredient


class MedicineIngredientInline(admin.TabularInline):
    """Edit a medicine's ingredients on the medicine page itself."""

    model = MedicineIngredient
    extra = 1
    autocomplete_fields = ("ingredient",)


@admin.register(Medicine)
class MedicineAdmin(admin.ModelAdmin):
    list_display = (
        "brand_name", "dosage_form", "manufacturer",
        "max_retail_price", "equivalence_key", "is_active",
    )
    list_filter = ("dosage_form", "is_active")
    search_fields = ("brand_name", "normalized_name", "nmra_reg_no")
    readonly_fields = ("normalized_name", "equivalence_key", "created_at")
    inlines = [MedicineIngredientInline]

    def save_related(self, request, form, formsets, change):
        """Ingredients are saved after the medicine, so rebuild the key here."""
        super().save_related(request, form, formsets, change)
        form.instance.refresh_equivalence_key()


@admin.register(ActiveIngredient)
class ActiveIngredientAdmin(admin.ModelAdmin):
    list_display = ("name", "normalized_name", "atc_code")
    search_fields = ("name", "normalized_name")
    readonly_fields = ("normalized_name",)