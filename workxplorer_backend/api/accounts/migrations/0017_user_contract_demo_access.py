from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        (
            "accounts",
            "0016_rename_accounts_fl_owner__3f31d6_idx_accounts_fl_owner_i_c37d14_idx_and_more",
        ),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="has_signed_contract",
            field=models.BooleanField(
                default=False,
                help_text="Unlocks paid features and removes demo limits.",
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="demo_request_limit",
            field=models.PositiveIntegerField(
                default=5,
                help_text="Cargo/order limit while contract is not signed.",
            ),
        ),
    ]
