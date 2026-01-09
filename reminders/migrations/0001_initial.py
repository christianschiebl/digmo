from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("customers", "0001_initial"),
        ("documents", "0002_customerdocument_mapping_report"),
    ]

    operations = [
        migrations.CreateModel(
            name="ReminderRule",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "trigger_event",
                    models.CharField(
                        choices=[("DOCUMENT_SENT", "Dokument versendet")],
                        default="DOCUMENT_SENT",
                        max_length=50,
                    ),
                ),
                (
                    "days_after",
                    models.PositiveIntegerField(
                        default=14,
                        help_text="Anzahl Tage nach dem Ereignis, wann der Reminder gesendet werden soll.",
                    ),
                ),
                (
                    "brevo_template_id",
                    models.CharField(
                        blank=True,
                        help_text="Optional: Brevo Template-ID. Wenn gesetzt, wird diese verwendet.",
                        max_length=64,
                        null=True,
                    ),
                ),
                (
                    "subject",
                    models.CharField(
                        blank=True,
                        help_text="Betreffzeile, falls keine Brevo Template-ID verwendet wird.",
                        max_length=255,
                    ),
                ),
                (
                    "body",
                    models.TextField(
                        blank=True,
                        help_text="E-Mail-Text (HTML oder Klartext), falls keine Brevo Template-ID verwendet wird.",
                    ),
                ),
                ("enabled", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "broker",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="reminder_rules",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("-created_at",),
            },
        ),
        migrations.CreateModel(
            name="ReminderLog",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("due_at", models.DateTimeField()),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Ausstehend"),
                            ("sent", "Gesendet"),
                            ("failed", "Fehlgeschlagen"),
                        ],
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("provider_response_id", models.CharField(blank=True, max_length=255)),
                ("error_text", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "broker",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="reminder_logs",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "customer",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="reminder_logs",
                        to="customers.customerprofile",
                    ),
                ),
                (
                    "document",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=models.deletion.CASCADE,
                        related_name="reminder_logs",
                        to="documents.customerdocument",
                    ),
                ),
                (
                    "rule",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="logs",
                        to="reminders.reminderrule",
                    ),
                ),
            ],
            options={
                "ordering": ("due_at",),
            },
        ),
    ]



