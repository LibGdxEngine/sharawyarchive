from django.urls import path

from .views import ClipCreateView, ClipDetailView, ClipFileView

urlpatterns = [
    path('clips/', ClipCreateView.as_view(), name='clip-create'),
    path('clips/<uuid:pk>/', ClipDetailView.as_view(), name='clip-detail'),
    # Stable addresses for the bytes: `media` plays inline (the clip page and
    # its OpenGraph card), `download` saves to disk. Both re-sign per request,
    # so neither expires the way a presigned URL in a JSON body does.
    path(
        'clips/<uuid:pk>/media/',
        ClipFileView.as_view(as_attachment=False),
        name='clip-media',
    ),
    path(
        'clips/<uuid:pk>/download/',
        ClipFileView.as_view(as_attachment=True),
        name='clip-download',
    ),
]
