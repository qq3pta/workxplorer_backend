from api.notifications.services import check_expo_push_receipts
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Checks Expo push receipts and disables invalid push devices."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=300)

    def handle(self, *args, **options):
        checked_count = check_expo_push_receipts(limit=options["limit"])
        self.stdout.write(self.style.SUCCESS(f"Checked Expo push receipts: {checked_count}"))
