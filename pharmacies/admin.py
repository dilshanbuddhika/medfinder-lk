from django.contrib import admin
from django.contrib.gis import admin as gis_admin

from .models import PharmacyProfile, StockItem


class StockItemInline(admin.TabularInline):
    model = StockItem
    extra = 1
    autocomplete_fields = ("medicine",)


@admin.register(PharmacyProfile)
class PharmacyProfileAdmin(gis_admin.GISModelAdmin):
    list_display = ("name", "city", "district", "is_verified", "accuracy_rating")
    list_filter = ("is_verified", "district")
    search_fields = ("name", "city", "contact_no")
    inlines = [StockItemInline]

    # Centre the map on Kandy instead of somewhere in the Atlantic
    gis_widget_kwargs = {
        "attrs": {
            "default_lat": 7.2906,
            "default_lon": 80.6337,
            "default_zoom": 12,
        }
    }


@admin.register(StockItem)
class StockItemAdmin(admin.ModelAdmin):
    list_display = (
        "medicine", "pharmacy", "availability",
        "indicative_price", "last_updated_at",
    )
    list_filter = ("availability",)
    search_fields = ("medicine__brand_name", "pharmacy__name")
    autocomplete_fields = ("medicine", "pharmacy")