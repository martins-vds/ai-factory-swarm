from django.db import models


class OrderModel(models.Model):
    code = models.CharField(max_length=10)

    class Meta:
        db_table = 'shop_orders'


class AuditModel(models.Model):
    note = models.TextField()


class Base(models.Model):
    class Meta:
        abstract = True
