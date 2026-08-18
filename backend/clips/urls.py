from django.urls import path

from .views import ClipCreateView, ClipDetailView

urlpatterns = [
    path('clips/', ClipCreateView.as_view(), name='clip-create'),
    path('clips/<uuid:pk>/', ClipDetailView.as_view(), name='clip-detail'),
]
