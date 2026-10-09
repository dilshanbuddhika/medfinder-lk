from django.db.models.signals import pre_save
from django.dispatch import receiver

from matching.normalize import normalize_name

from .models import ActiveIngredient, Medicine


@receiver(pre_save, sender=Medicine)
def set_medicine_normalized_name(sender, instance, **kwargs):
    instance.normalized_name = normalize_name(instance.brand_name)


@receiver(pre_save, sender=ActiveIngredient)
def set_ingredient_normalized_name(sender, instance, **kwargs):
    instance.normalized_name = normalize_name(instance.name)