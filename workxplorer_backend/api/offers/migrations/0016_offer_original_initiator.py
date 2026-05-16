from django.db import migrations, models


def backfill_original_initiator(apps, schema_editor):
    """
    Заполняем original_initiator для уже существующих офферов.

    Если по офферу есть лог изменений — самый ранний лог хранит состояние
    ДО первого контр-предложения, т.е. в его old_state лежит настоящий
    исходный инициатор. Если логов нет — оффер ни разу не контрился,
    значит текущий initiator и есть исходный.
    """
    Offer = apps.get_model("offers", "Offer")
    OfferStatusLog = apps.get_model("offers", "OfferStatusLog")

    for offer in Offer.objects.all().iterator():
        original = offer.initiator

        first_log = (
            OfferStatusLog.objects.filter(offer_id=offer.id).order_by("created_at", "id").first()
        )
        if first_log and isinstance(first_log.old_state, dict):
            logged = first_log.old_state.get("initiator")
            if logged:
                original = logged

        offer.original_initiator = original
        offer.save(update_fields=["original_initiator"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("offers", "0015_deactivate_rejected_offers"),
    ]

    operations = [
        migrations.AddField(
            model_name="offer",
            name="original_initiator",
            field=models.CharField(
                blank=True,
                choices=[
                    ("CUSTOMER", "Заказчик"),
                    ("CARRIER", "Перевозчик"),
                    ("LOGISTIC", "Логист"),
                ],
                max_length=16,
                null=True,
            ),
        ),
        migrations.RunPython(backfill_original_initiator, noop_reverse),
    ]
