from django.db import migrations, models

import common.storage


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0011_user_last_seen"),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="photo",
            field=models.ImageField(
                blank=True,
                null=True,
                storage=common.storage.avatar_storage,
                upload_to="avatars/",
            ),
        ),
    ]
