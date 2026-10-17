from django.apps import AppConfig


class WikiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'wiki'
    verbose_name = 'Shizuha Wiki'

    def ready(self):
        import wiki.signals  # noqa
