from django.urls import path

from .views import SearchView, SuggestView

urlpatterns = [
    path('search/', SearchView.as_view(), name='search'),
    path('search/suggest/', SuggestView.as_view(), name='search-suggest'),
]
