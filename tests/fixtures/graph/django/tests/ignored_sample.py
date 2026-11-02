from shop.orders.infrastructure.models import OrderModel


def test_x():
    OrderModel.objects.create(code='x')
