from django.contrib import admin
from django.urls import include, path

from api.views import healthz, readyz
from core.sitemaps import sitemap_index, sitemap_quran, sitemap_segments

urlpatterns = [
    path('admin/', admin.site.urls),

    # Probes live at the root: an orchestrator should not need the API prefix.
    path('healthz', healthz, name='healthz'),
    path('readyz', readyz, name='readyz'),

    # Sitemaps
    path('sitemap.xml', sitemap_index, name='sitemap-index'),
    path('sitemap-quran.xml', sitemap_quran, name='sitemap-quran'),
    path('sitemap-segments.xml', sitemap_segments, name='sitemap-segments'),

    path('api/', include('api.urls')),
    path('api/', include('quran.urls')),
    path('api/', include('corpus.urls')),
    path('api/', include('clips.urls')),
    path('api/', include('search.urls')),
]
