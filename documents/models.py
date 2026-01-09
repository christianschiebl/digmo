from django.conf import settings
from django.db import models

from customers.models import CustomerProfile


class DocumentTemplate(models.Model):
    class Type(models.TextChoices):
        DOCX = "DOCX", "DOCX"
        PDF_ACROFORM = "PDF_ACROFORM", "PDF AcroForm"

    broker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="document_templates",
    )
    name = models.CharField(max_length=255)
    type = models.CharField(max_length=20, choices=Type.choices, default=Type.DOCX)
    file = models.FileField(upload_to="templates/")
    field_schema = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("name",)

    def __str__(self) -> str:
        return f"{self.name} ({self.type})"

    @property
    def filename(self) -> str:
        """
        Liefert den Dateinamen (ohne Pfad) der Template-Datei.
        """
        if not self.file or not self.file.name:
            return ""
        return self.file.name.rsplit("/", 1)[-1]


class CustomerDocument(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Entwurf"
        SENT = "sent", "Versendet"
        COMPLETED = "completed", "Abgeschlossen"

    broker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="customer_documents",
    )
    customer = models.ForeignKey(
        CustomerProfile,
        on_delete=models.CASCADE,
        related_name="documents",
    )
    template = models.ForeignKey(
        DocumentTemplate,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="customer_documents",
    )
    uploaded_file = models.FileField(
        upload_to="customer_uploads/", blank=True, null=True
    )
    generated_file = models.FileField(
        upload_to="customer_generated/", blank=True, null=True
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT
    )
    sent_to_customer_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    mapping_report = models.JSONField(blank=True, null=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"Dokument für {self.customer} ({self.get_status_display()})"

    @property
    def filename(self) -> str:
        """
        Liefert den Dateinamen (ohne Pfad) des relevanten Dokuments:
        - bevorzugt generated_file, sonst uploaded_file.
        """
        file_field = self.generated_file or self.uploaded_file
        if not file_field or not file_field.name:
            return ""
        return file_field.name.rsplit("/", 1)[-1]


