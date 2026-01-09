from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("customers", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="DocumentTemplate",
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
                ("name", models.CharField(max_length=255)),
                (
                    "type",
                    models.CharField(
                        choices=[("DOCX", "DOCX"), ("PDF_ACROFORM", "PDF AcroForm")],
                        default="DOCX",
                        max_length=20,
                    ),
                ),
                ("file", models.FileField(upload_to="templates/")),
                ("field_schema", models.JSONField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "broker",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="document_templates",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("name",),
            },
        ),
        migrations.CreateModel(
            name="CustomerDocument",
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
                    "uploaded_file",
                    models.FileField(
                        blank=True, null=True, upload_to="customer_uploads/"
                    ),
                ),
                (
                    "generated_file",
                    models.FileField(
                        blank=True, null=True, upload_to="customer_generated/"
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Entwurf"),
                            ("sent", "Versendet"),
                            ("completed", "Abgeschlossen"),
                        ],
                        default="draft",
                        max_length=20,
                    ),
                ),
                ("sent_to_customer_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "broker",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="customer_documents",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "customer",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="documents",
                        to="customers.customerprofile",
                    ),
                ),
                (
                    "template",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=models.deletion.SET_NULL,
                        related_name="customer_documents",
                        to="documents.documenttemplate",
                    ),
                ),
            ],
            options={
                "ordering": ("-created_at",),
            },
        ),
    ]


