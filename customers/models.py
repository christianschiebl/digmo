from django.conf import settings
from django.db import models
from django.utils import timezone


class CustomerProfile(models.Model):
    class Status(models.TextChoices):
        NEW = "new", "Neu"
        IN_PROGRESS = "in_progress", "In Bearbeitung"
        COMPLETE = "complete", "Abgeschlossen"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="customer_profile",
    )
    broker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="customer_profiles",
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.NEW
    )

    # Basis-Selbstauskunft (MVP)
    first_name = models.CharField("Vorname", max_length=150)
    last_name = models.CharField("Nachname", max_length=150)
    email = models.EmailField("E-Mail")
    phone = models.CharField("Telefon", max_length=50, blank=True)
    street = models.CharField("Straße/Hausnummer", max_length=255, blank=True)
    postal_code = models.CharField("PLZ", max_length=20, blank=True)
    city = models.CharField("Ort", max_length=100, blank=True)

    employment_status = models.CharField(
        "Beschäftigungsstatus", max_length=100, blank=True
    )
    monthly_income = models.DecimalField(
        "Monatliches Nettoeinkommen",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("last_name", "first_name")

    def __str__(self) -> str:
        return f"{self.last_name}, {self.first_name} ({self.email})"


class CustomerInvite(models.Model):
    broker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="customer_invites",
    )
    customer = models.ForeignKey(
        CustomerProfile,
        on_delete=models.CASCADE,
        related_name="invites",
    )
    token = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    @property
    def is_active(self) -> bool:
        return self.used_at is None and self.expires_at > timezone.now()

    def get_absolute_url(self):
        from django.urls import reverse

        return reverse("customer_invite_accept", args=[self.token])

    def __str__(self) -> str:
        return f"Invite für {self.customer} ({self.token})"


