from django.apps import AppConfig


class EmailMgmtConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'email_mgmt'
    def ready(self):
        # Ensures receivers are connected in every process
        from . import signals
