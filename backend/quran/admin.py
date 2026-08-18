from django.contrib import admin

from .models import Ayah, Surah


@admin.register(Surah)
class SurahAdmin(admin.ModelAdmin):
    list_display = ("number", "name_ar", "name_en", "ayah_count", "revelation_place")
    list_filter = ("revelation_place",)
    search_fields = ("name_ar", "name_ar_plain", "name_en")
    ordering = ("number",)


@admin.register(Ayah)
class AyahAdmin(admin.ModelAdmin):
    list_display = ("surah", "number", "juz", "hizb", "page", "sajda")
    list_filter = ("juz", "sajda")
    search_fields = ("text_normalized",)
    raw_id_fields = ("surah",)
    ordering = ("surah", "number")
