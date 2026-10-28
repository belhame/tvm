from django.apps import AppConfig

class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    def ready(self):
        from . import workflow_signals  # noqa: F401
        from . import ready_notifications  # noqa: F401
