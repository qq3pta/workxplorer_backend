from datetime import date

from django.test import TestCase

from api.accounts.models import User
from api.chat.models import Chat
from api.loads.choices import ContactPref, TransportType
from api.loads.models import Cargo
from api.orders.models import Order


class OrderChatSyncTests(TestCase):
    def test_sync_order_chat_keeps_custom_group_title(self):
        customer = User.objects.create_user(username="customer")
        cargo = Cargo.objects.create(
            customer=customer,
            origin_address="Origin address",
            origin_city="Tashkent",
            destination_address="Destination address",
            destination_city="Samarkand",
            load_date=date.today(),
            transport_type=TransportType.TENT,
            contact_pref=ContactPref.PHONE,
        )
        chat = Chat.objects.create(
            chat_type=Chat.ChatType.GROUP,
            title="Custom route group",
        )
        order = Order.objects.create(cargo=cargo, chat=chat)

        order.sync_order_chat()

        chat.refresh_from_db()
        self.assertEqual(chat.title, "Custom route group")

        with self.captureOnCommitCallbacks(execute=True):
            order.status = Order.OrderStatus.EN_ROUTE
            order.save(update_fields=["status"])

        chat.refresh_from_db()
        self.assertEqual(chat.title, "Custom route group")
