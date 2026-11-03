from shop.orders.infrastructure.repository import DjangoOrderRepository
from shop.queue import app


@app.task(queue='orders')
def record_note(note):
    DjangoOrderRepository().record(note)
