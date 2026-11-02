from typing import Protocol


class OrderRepository(Protocol):
    def find(self, order_id): ...
