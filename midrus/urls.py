from django.contrib import admin
from django.db import connection
from django.http import JsonResponse
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

def healthz(request):
    """Liveness/readiness probe for load balancers: 200 only if the DB answers."""
    try:
        connection.ensure_connection()
    except Exception:
        return JsonResponse({'status': 'error'}, status=503)
    return JsonResponse({'status': 'ok'})


urlpatterns = [
    path('healthz/', healthz),
    path('admin/', admin.site.urls),
    path('api/auth/', include('accounts.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
