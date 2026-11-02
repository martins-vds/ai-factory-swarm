from django.urls import include, path

from shop.orders.composition import compose_order_view

urlpatterns = [
    path('', compose_order_view(), name='orders'),
    path('api/', include('shop.orders.interfaces.urls')),
]
