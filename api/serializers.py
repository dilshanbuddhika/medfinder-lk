from rest_framework import serializers

from catalogue.models import Medicine
from pharmacies.models import StockItem


class MedicineSerializer(serializers.ModelSerializer):
    dosage_form_display = serializers.CharField(
        source="get_dosage_form_display", read_only=True
    )
    ingredients_text = serializers.SerializerMethodField()

    class Meta:
        model = Medicine
        fields = (
            "id", "brand_name", "dosage_form", "dosage_form_display",
            "manufacturer", "max_retail_price", "ingredients_text",
        )

    def get_ingredients_text(self, obj):
        """e.g. 'Paracetamol 500mg' — what the user actually needs to read."""
        parts = []
        for mi in obj.medicine_ingredients.select_related("ingredient"):
            text = format(mi.strength_value, "f")
            if "." in text:
                # Only strip zeros that follow a decimal point
                text = text.rstrip("0").rstrip(".")
            parts.append(f"{mi.ingredient.name} {text}{mi.strength_unit}")
        return ", ".join(parts)


class PharmacySummarySerializer(serializers.Serializer):
    """Only what a patient needs to decide where to go."""

    id = serializers.IntegerField()
    name = serializers.CharField()
    address = serializers.CharField()
    contact_no = serializers.CharField()
    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()

    def get_latitude(self, obj):
        return obj.location.y

    def get_longitude(self, obj):
        return obj.location.x


class SearchResultSerializer(serializers.ModelSerializer):
    medicine = MedicineSerializer(read_only=True)
    pharmacy = PharmacySummarySerializer(read_only=True)
    distance_m = serializers.SerializerMethodField()
    is_exact = serializers.SerializerMethodField()
    data_age_hours = serializers.SerializerMethodField()
    confidence = serializers.SerializerMethodField()

    class Meta:
        model = StockItem
        fields = (
            "id", "medicine", "pharmacy", "availability",
            "indicative_price", "distance_m", "is_exact",
            "data_age_hours", "confidence",
        )

    def get_distance_m(self, obj):
        return round(obj.distance.m) if hasattr(obj, "distance") else None

    def get_is_exact(self, obj):
        return obj.medicine_id == self.context.get("requested_medicine_id")

    def get_data_age_hours(self, obj):
        return round(obj.age_hours, 1)

    def get_confidence(self, obj):
        return round(obj.confidence(), 2)