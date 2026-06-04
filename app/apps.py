from django.apps import AppConfig
import sys

class AppConfig(AppConfig):
    name = 'app'

    def ready(self):
        if 'migrate' not in sys.argv:
            import app.signals
            import app.signals_audit