from django.conf import settings
from django.db import models
from django.utils import timezone

from customers.models import CustomerProfile
from documents.models import CustomerDocument


class ReminderRule(models.Model):
    class TriggerEvent(models.TextChoices):
        DOCUMENT_SENT = "DOCUMENT_SENT", "Dokument versendet"

    broker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="reminder_rules",
    )
    trigger_event = models.CharField(
        max_length=50,
        choices=TriggerEvent.choices,
        default=TriggerEvent.DOCUMENT_SENT,
    )
    days_after = models.PositiveIntegerField(
        default=14,
        help_text="Anzahl Tage nach dem Ereignis, wann der Reminder gesendet werden soll.",
    )
    brevo_template_id = models.CharField(
        max_length=64,
        blank=True,
        null=True,
        help_text="Optional: Brevo Template-ID. Wenn gesetzt, wird diese verwendet.",
    )
    subject = models.CharField(
        max_length=255,
        blank=True,
        help_text="Betreffzeile, falls keine Brevo Template-ID verwendet wird.",
    )
    body = models.TextField(
        blank=True,
        help_text="E-Mail-Text (HTML oder Klartext), falls keine Brevo Template-ID verwendet wird.",
    )
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"Reminder-Regel ({self.get_trigger_event_display()}) für {self.broker.email}"

    @property
    def uses_brevo_template(self) -> bool:
        return bool(self.brevo_template_id)


class ReminderLog(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Ausstehend"
        SENT = "sent", "Gesendet"
        FAILED = "failed", "Fehlgeschlagen"

    broker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="reminder_logs",
    )
    customer = models.ForeignKey(
        CustomerProfile,
        on_delete=models.CASCADE,
        related_name="reminder_logs",
    )
    document = models.ForeignKey(
        CustomerDocument,
        on_delete=models.CASCADE,
        related_name="reminder_logs",
        blank=True,
        null=True,
    )
    rule = models.ForeignKey(
        ReminderRule,
        on_delete=models.CASCADE,
        related_name="logs",
    )

    due_at = models.DateTimeField()
    sent_at = models.DateTimeField(blank=True, null=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    provider_response_id = models.CharField(max_length=255, blank=True)
    error_text = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("due_at",)

    def mark_sent(self, provider_response_id: str | None = None) -> None:
        self.status = self.Status.SENT
        self.sent_at = timezone.now()
        if provider_response_id:
            self.provider_response_id = provider_response_id
        self.save(update_fields=["status", "sent_at", "provider_response_id"])

    def mark_failed(self, error_text: str) -> None:
        self.status = self.Status.FAILED
        # Fehlertext etwas kürzen, damit das Feld nicht ausufert.
        self.error_text = (error_text or "")[:1000]
        self.save(update_fields=["status", "error_text"])



