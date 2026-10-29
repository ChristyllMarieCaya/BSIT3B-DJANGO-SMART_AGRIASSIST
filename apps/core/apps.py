import logging
from django.apps import AppConfig

logger = logging.getLogger(__name__)


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.core'

    def ready(self):
        try:
            from apps.core.admin_dashboard import setup_smart_admin
            setup_smart_admin()
        except Exception as exc:
            logger.warning('Could not setup smart admin: %s', exc)

        try:
            from apps.core.scheduler import start_background_scheduler
            start_background_scheduler(interval_seconds=600)
        except Exception as exc:
            logger.warning('Could not start background scheduler: %s', exc)
