from shop.orders.domain.repository import OrderRepository


class OrderLookup:
    def __init__(self, orders: OrderRepository):
        self._orders = orders

    def find(self, order_id):
        return self._orders.find(order_id)
