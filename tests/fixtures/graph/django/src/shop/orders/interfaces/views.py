from django.shortcuts import render

from shop.orders.application import OrderLookup


def create_order_view(lookup: OrderLookup):
    def view(request):
        return render(request, 'orders/list.html', {'order': lookup.find(request.GET.get('id'))})
    return view


def health(request):
    return render(request, 'orders/health.html')
