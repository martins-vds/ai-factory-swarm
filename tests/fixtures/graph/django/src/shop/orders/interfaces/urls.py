from django.urls import path

from shop.orders.interfaces import board, views

app_name = 'orders'

urlpatterns = [
    path('health/', views.health),
    path('board/', board.board, name='board'),
    path('board/rows/', board.board_rows, name='board-rows'),
]
