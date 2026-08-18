from django.urls import path

from .views import AyahDetailView, SurahDetailView, SurahListView

urlpatterns = [
    path('surahs/', SurahListView.as_view(), name='surah-list'),
    path('surahs/<int:number>/', SurahDetailView.as_view(), name='surah-detail'),
    path('ayahs/<int:surah>/<int:ayah>/', AyahDetailView.as_view(), name='ayah-detail'),
]
