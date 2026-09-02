"""Staff view of smart-search traffic: what was asked, what it cost, what readers thought."""

from __future__ import annotations

from django.contrib import admin
from django.http import HttpRequest

from .models import SmartQuery


@admin.register(SmartQuery)
class SmartQueryAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "short_question",
        "status",
        "cost_usd",
        "total_latency_ms",
        "feedback",
        "cache_hit",
    )
    list_filter = ("status", "feedback", "cache_hit", "prompt_version")
    search_fields = ("question",)
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    readonly_fields = [field.name for field in SmartQuery._meta.fields]

    @admin.display(description="question")
    def short_question(self, obj: SmartQuery) -> str:
        return obj.question if len(obj.question) <= 80 else obj.question[:77] + "…"

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: SmartQuery | None = None) -> bool:
        return False
