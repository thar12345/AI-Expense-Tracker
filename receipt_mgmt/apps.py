from django.apps import AppConfig


class ReceiptMgmtConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'receipt_mgmt'
    def ready(self):
        # Ensures receivers are connected in every process
        from . import signals
        