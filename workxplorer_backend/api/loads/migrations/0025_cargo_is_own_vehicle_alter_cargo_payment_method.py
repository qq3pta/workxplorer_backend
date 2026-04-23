from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("loads", "0024_cargo_destination_region_cargo_origin_region"),
    ]

    operations = [
        migrations.AddField(
            model_name="cargo",
            name="is_own_vehicle",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Заявка для собственного транспорта заказчика: "
                    "не выходит на публичный борд, цена и способ оплаты не заполняются, "
                    "участники добавляются только через приглашение/ссылку."
                ),
                verbose_name="Своя машина",
            ),
        ),
        migrations.AlterField(
            model_name="cargo",
            name="payment_method",
            field=models.CharField(
                blank=True,
                choices=[
                    ("cash", "Наличные"),
                    ("cashless", "Безналичный расчёт"),
                    ("both", "Наличные + безналичный расчёт"),
                ],
                default="cash",
                max_length=10,
                null=True,
                verbose_name="Способ оплаты",
            ),
        ),
    ]
