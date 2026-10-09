from django.conf import settings
from django.contrib.gis.db import models as gis
from django.db import models
from django.utils import timezone


class PharmacyProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="pharmacy"
    )
    name = models.CharField(max_length=200)
    address = models.TextField()
    city = models.CharField(max_length=100, db_index=True)
    district = models.CharField(max_length=100, db_index=True)
    contact_no = models.CharField(max_length=15)

    location = gis.PointField(geography=True, srid=4326, spatial_index=True)

    opening_hours = models.JSONField(
        default=dict, blank=True,
        help_text='e.g. {"mon": ["08:00", "20:00"], "sun": null}',
    )
    is_verified = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True)
    accuracy_rating = models.FloatField(
        default=0.0, help_text="Rolling mean of patient accuracy ratings, 0-1"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["is_verified", "district"])]

    def __str__(self):
        return f"{self.name}, {self.city}"


class Availability(models.TextChoices):
    IN_STOCK = "in", "In stock"
    LOW = "low", "Low stock"
    OUT = "out", "Out of stock"


class StockItem(models.Model):
    """What a pharmacy declares it has. Availability, not quantity on hand."""

    pharmacy = models.ForeignKey(
        PharmacyProfile, on_delete=models.CASCADE, related_name="stock_items"
    )
    medicine = models.ForeignKey(
        "catalogue.Medicine", on_delete=models.CASCADE, related_name="stock_items"
    )
    availability = models.CharField(
        max_length=3, choices=Availability.choices, default=Availability.IN_STOCK
    )
    indicative_price = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    last_updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("pharmacy", "medicine")]
        indexes = [
            models.Index(fields=["medicine", "availability"]),
            models.Index(fields=["last_updated_at"]),
        ]

    def __str__(self):
        return f"{self.medicine} @ {self.pharmacy} [{self.availability}]"

    @property
    def age_hours(self):
        return (timezone.now() - self.last_updated_at).total_seconds() / 3600

    def confidence(self, stale_hours=72):
        """Freshness weight for ranking. 1.0 fresh, decays toward 0."""
        if self.availability == Availability.OUT:
            return 0.0
        return max(0.0, 1.0 - self.age_hours / stale_hours)