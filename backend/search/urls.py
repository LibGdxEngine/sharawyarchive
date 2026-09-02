from django.urls import path

from .views import SearchView, SmartFeedbackView, SmartSearchView, SuggestView

urlpatterns = [
    path('search/', SearchView.as_view(), name='search'),
    path('search/suggest/', SuggestView.as_view(), name='search-suggest'),
    path('search/smart/', SmartSearchView.as_view(), name='search-smart'),
    path(
        'search/smart/<uuid:query_id>/feedback/',
        SmartFeedbackView.as_view(),
        name='search-smart-feedback',
    ),
]
