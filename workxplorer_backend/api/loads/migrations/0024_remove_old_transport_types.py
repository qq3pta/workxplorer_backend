from django.db import migrations, models


REMOVED_TYPES = ("GRAIN", "LOG", "PICKUP")


def normalize_removed_transport_types(apps, schema_editor):
    Cargo = apps.get_model("loads", "Cargo")
    Cargo.objects.filter(transport_type__in=REMOVED_TYPES).update(transport_type="OTHER")


class Migration(migrations.Migration):

    dependencies = [
        ("loads", "0023_cargo_category_and_optional_fields"),
    ]

    operations = [
        migrations.RunPython(
            normalize_removed_transport_types,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="cargo",
            name="transport_type",
            field=models.CharField(
                choices=[
                    ("TENT", "Тент"),
                    ("CONT", "Контейнер"),
                    ("REEFER", "Рефрижератор"),
                    ("DUMP", "Самосвал"),
                    ("CARTR", "Автотранспортер"),
                    ("MEGA", "Мега фура"),
                    ("OTHER", "Другое"),
                ],
                max_length=10,
            ),
        ),
    ]
