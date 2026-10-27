from django.apps import AppConfig


class InfoConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.info'

    def ready(self):
        import apps.info.signals  # noqa: F401
