from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0014_user_is_verified"),
    ]

    operations = [
        migrations.CreateModel(
            name="FleetMembership",
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
                            ("pending", "Pending"),
                            ("accepted", "Accepted"),
                            ("declined", "Declined"),
                        ],
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("invited_at", models.DateTimeField(auto_now_add=True)),
                ("responded_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "member",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="fleet_invites",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "owner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="fleet_memberships",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-updated_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="fleetmembership",
            constraint=models.UniqueConstraint(
                fields=("owner", "member"),
                name="uniq_fleet_owner_member",
            ),
        ),
        migrations.AddConstraint(
            model_name="fleetmembership",
            constraint=models.CheckConstraint(
                check=~models.Q(owner=models.F("member")),
                name="fleet_owner_member_distinct",
            ),
        ),
        migrations.AddIndex(
            model_name="fleetmembership",
            index=models.Index(fields=["owner", "status"], name="accounts_fl_owner__3f31d6_idx"),
        ),
        migrations.AddIndex(
            model_name="fleetmembership",
            index=models.Index(fields=["member", "status"], name="accounts_fl_member__d14f44_idx"),
        ),
    ]
