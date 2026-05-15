from django.db import migrations


def deactivate_rejected_offers(apps, schema_editor):
    Offer = apps.get_model("offers", "Offer")
    Offer.objects.filter(
        is_active=True,
        response_status__startswith="rejected",
    ).update(is_active=False)


def reactivate_rejected_offers(apps, schema_editor):
    Offer = apps.get_model("offers", "Offer")
    Offer.objects.filter(
        is_active=False,
        response_status__startswith="rejected",
    ).update(is_active=True)


class Migration(migrations.Migration):
    dependencies = [
        ("offers", "0014_offer_driver_currency_offer_driver_payment_method_and_more"),
    ]

    operations = [
        migrations.RunPython(deactivate_rejected_offers, reactivate_rejected_offers),
    ]
