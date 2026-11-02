from django.urls import path

from shop.orders.interfaces import views

urlpatterns = [
    path('health/', views.health),
]
