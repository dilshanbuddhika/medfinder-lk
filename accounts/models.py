from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models


class Role(models.TextChoices):
    PATIENT = "patient", "Patient"
    PHARMACY = "pharmacy", "Pharmacy staff"
    ADMIN = "admin", "Administrator"


class Language(models.TextChoices):
    SINHALA = "si", "Sinhala"
    TAMIL = "ta", "Tamil"
    ENGLISH = "en", "English"


class UserManager(BaseUserManager):
    """Needed because we authenticate by mobile_no, not username."""

    use_in_migrations = True

    def create_user(self, mobile_no, password=None, **extra):
        if not mobile_no:
            raise ValueError("mobile_no is required")
        user = self.model(mobile_no=mobile_no, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, mobile_no, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("role", Role.ADMIN)
        extra.setdefault("is_mobile_verified", True)
        return self.create_user(mobile_no, password, **extra)


class User(AbstractUser):
    username = None
    mobile_no = models.CharField(max_length=15, unique=True, db_index=True)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.PATIENT)
    preferred_language = models.CharField(
        max_length=2, choices=Language.choices, default=Language.ENGLISH
    )
    is_mobile_verified = models.BooleanField(default=False)

    USERNAME_FIELD = "mobile_no"
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        indexes = [models.Index(fields=["role"])]

    def __str__(self):
        return f"{self.mobile_no} ({self.role})"