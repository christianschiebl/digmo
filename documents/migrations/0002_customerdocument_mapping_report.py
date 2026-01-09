from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="customerdocument",
            name="mapping_report",
            field=models.JSONField(blank=True, null=True),
        ),
    ]


