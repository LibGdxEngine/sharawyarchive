from django.contrib import admin
from django.urls import include, path

from api.views import healthz, readyz

urlpatterns = [
    path('admin/', admin.site.urls),

    # Probes live at the root: an orchestrator should not need the API prefix.
    path('healthz', healthz, name='healthz'),
    path('readyz', readyz, name='readyz'),

    path('api/', include('api.urls')),
    path('api/', include('quran.urls')),
    path('api/', include('corpus.urls')),
    path('api/', include('clips.urls')),
    path('api/', include('search.urls')),
]
