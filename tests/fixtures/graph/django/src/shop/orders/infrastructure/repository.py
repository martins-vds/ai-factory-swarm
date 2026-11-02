from shop.orders.domain.repository import OrderRepository
from shop.orders.infrastructure.models import AuditModel, OrderModel


class DjangoOrderRepository(OrderRepository):
    def find(self, order_id):
        return OrderModel.objects.filter(code=order_id).first()

    def record(self, note):
        entry = AuditModel(note=note)
        entry.save()
