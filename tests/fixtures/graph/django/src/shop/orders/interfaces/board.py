from django.shortcuts import render

from shop.orders.infrastructure.repository import DjangoOrderRepository


def board(request):
    return render(request, 'orders/board.html')


def board_rows(request):
    return render(request, 'orders/rows.html', {'order': DjangoOrderRepository().find(request.GET.get('id'))})
