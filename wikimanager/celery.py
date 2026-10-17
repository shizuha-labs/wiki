"""Celery configuration for Shizuha Wiki"""
import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'wikimanager.settings')

app = Celery('shizuha_wiki')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

# Configure task routes
app.conf.task_routes = {
    'wiki.tasks.*': {'queue': 'shizuha_wiki'},
}
