from django.urls import path

from .views import (
    CorrectionCreateView,
    SegmentDetailView,
    SegmentRelatedView,
    SegmentTranscriptView,
    TopicDetailView,
    TopicListView,
)

urlpatterns = [
    path('segments/<int:pk>/', SegmentDetailView.as_view(), name='segment-detail'),
    path(
        'segments/<int:pk>/transcript/',
        SegmentTranscriptView.as_view(),
        name='segment-transcript',
    ),
    path('segments/<int:pk>/related/', SegmentRelatedView.as_view(), name='segment-related'),
    path('topics/', TopicListView.as_view(), name='topic-list'),
    path('topics/<slug:slug>/', TopicDetailView.as_view(), name='topic-detail'),
    path('corrections/', CorrectionCreateView.as_view(), name='correction-create'),
]
