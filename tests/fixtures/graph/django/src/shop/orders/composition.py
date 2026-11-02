from shop.orders.application import OrderLookup
from shop.orders.infrastructure.repository import DjangoOrderRepository
from shop.orders.interfaces.views import create_order_view


def compose_order_view():
    return create_order_view(OrderLookup(DjangoOrderRepository()))
