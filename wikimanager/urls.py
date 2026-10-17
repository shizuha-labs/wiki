"""URL configuration for Shizuha Wiki"""
import os
import mimetypes
from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.http import FileResponse, Http404, JsonResponse
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView
from wiki.security_events import boundary_event_metrics
from wiki.request_metrics import request_status_metrics


def health_check(request):
    """Simple health check endpoint for container health checks."""
    return JsonResponse({'status': 'healthy'})


def serve_media(request, path):
    """Serve local media during development only."""
    file_path = os.path.join(settings.MEDIA_ROOT, path)
    if os.path.exists(file_path) and os.path.isfile(file_path):
        content_type, _ = mimetypes.guess_type(file_path)
        return FileResponse(
            open(file_path, 'rb'),
            content_type=content_type or 'application/octet-stream'
        )
    raise Http404("File not found")

urlpatterns = [
    # Health check endpoint (for container healthchecks)
    path('api/health/', health_check, name='health-check'),
    path('api/metrics/security-events/', boundary_event_metrics, name='security-event-metrics'),
    path('api/metrics/request-status/', request_status_metrics, name='request-status-metrics'),

    # Prefixed URLs to match what nginx sends
    path('shizuha-wiki/admin/', admin.site.urls),
    path('shizuha-wiki/api/', include('wiki.urls')),
    path('shizuha-wiki/api/auth/', include('wiki.auth_urls')),

    # API Documentation (prefixed)
    path('shizuha-wiki/api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('shizuha-wiki/api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('shizuha-wiki/api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),

    # Also keep non-prefixed URLs for direct access
    path('admin/', admin.site.urls),
    path('api/', include('wiki.urls')),
    path('api/auth/', include('wiki.auth_urls')),

    # API Documentation (non-prefixed)
    path('api/schema/', SpectacularAPIView.as_view(), name='schema-direct'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema-direct'), name='swagger-ui-direct'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema-direct'), name='redoc-direct'),
]

# Serve static and pod-local media in development only. Production attachments
# are always streamed through the authorized API from shared object storage.
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += [
        re_path(r'^shizuha-wiki-media/(?P<path>.*)$', serve_media, name='serve_media'),
    ]
