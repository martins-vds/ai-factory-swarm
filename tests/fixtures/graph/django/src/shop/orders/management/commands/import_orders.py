from django.core.management.base import BaseCommand

from shop.orders.tasks import record_note


class Command(BaseCommand):
    help = 'Import order notes.'

    def handle(self, *args, **options):
        record_note.defer(note='imported')
