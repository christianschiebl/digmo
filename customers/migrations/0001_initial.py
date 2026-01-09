from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CustomerProfile",
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
                    "status",
                    models.CharField(
                        choices=[
                            ("new", "Neu"),
                            ("in_progress", "In Bearbeitung"),
                            ("complete", "Abgeschlossen"),
                        ],
                        default="new",
                        max_length=20,
                    ),
                ),
                ("first_name", models.CharField(max_length=150, verbose_name="Vorname")),
                ("last_name", models.CharField(max_length=150, verbose_name="Nachname")),
                ("email", models.EmailField(max_length=254, verbose_name="E-Mail")),
                ("phone", models.CharField(blank=True, max_length=50, verbose_name="Telefon")),
                (
                    "street",
                    models.CharField(
                        blank=True, max_length=255, verbose_name="Straße/Hausnummer"
                    ),
                ),
                (
                    "postal_code",
                    models.CharField(blank=True, max_length=20, verbose_name="PLZ"),
                ),
                ("city", models.CharField(blank=True, max_length=100, verbose_name="Ort")),
                (
                    "employment_status",
                    models.CharField(
                        blank=True, max_length=100, verbose_name="Beschäftigungsstatus"
                    ),
                ),
                (
                    "monthly_income",
                    models.DecimalField(
                        blank=True,
                        decimal_places=2,
                        max_digits=10,
                        null=True,
                        verbose_name="Monatliches Nettoeinkommen",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "broker",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="customer_profiles",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "user",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=models.deletion.SET_NULL,
                        related_name="customer_profile",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("last_name", "first_name"),
            },
        ),
        migrations.CreateModel(
            name="CustomerInvite",
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
                ("token", models.CharField(max_length=64, unique=True)),
                ("expires_at", models.DateTimeField()),
                ("used_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "broker",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="customer_invites",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "customer",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="invites",
                        to="customers.customerprofile",
                    ),
                ),
            ],
            options={
                "ordering": ("-created_at",),
            },
        ),
    ]


