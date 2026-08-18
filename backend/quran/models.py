"""Canonical Quran text.

Rule 1 of the project: Quran text NEVER comes from ASR output. Every row in this
app is imported from Tanzil via ``manage.py import_quran`` and is treated as
read-only reference data everywhere else.
"""

from __future__ import annotations

from django.db import models


class RevelationPlace(models.TextChoices):
    MAKKAH = "makkah", "Makkah"
    MADINAH = "madinah", "Madinah"


class Surah(models.Model):
    """One of the 114 chapters. The chapter number is the primary key."""

    number = models.PositiveSmallIntegerField(primary_key=True)
    name_ar = models.CharField(max_length=100)
    name_ar_plain = models.CharField(
        max_length=100,
        help_text="name_ar passed through corpus.arabic.normalize_for_index.",
    )
    name_en = models.CharField(max_length=100)
    ayah_count = models.PositiveSmallIntegerField()
    revelation_place = models.CharField(max_length=8, choices=RevelationPlace.choices)
    order_revealed = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ["number"]
        verbose_name = "surah"
        verbose_name_plural = "surahs"

    def __str__(self) -> str:
        return f"{self.number}. {self.name_ar}"


class Ayah(models.Model):
    """A single verse, in both Uthmani and Imlaei script plus its index form."""

    surah = models.ForeignKey(Surah, on_delete=models.CASCADE, related_name="ayahs")
    number = models.PositiveSmallIntegerField()
    text_uthmani = models.TextField()
    text_imlaei = models.TextField()
    text_normalized = models.TextField(
        help_text="text_uthmani passed through corpus.arabic.normalize_for_index."
    )
    juz = models.PositiveSmallIntegerField()
    hizb = models.PositiveSmallIntegerField(help_text="Hizb quarter, 1-240.")
    page = models.PositiveSmallIntegerField(help_text="Madani mushaf page, 1-604.")
    sajda = models.BooleanField(default=False)

    class Meta:
        ordering = ["surah_id", "number"]
        constraints = [
            models.UniqueConstraint(fields=["surah", "number"], name="ayah_unique_surah_number"),
        ]
        indexes = [
            models.Index(fields=["surah", "number"], name="ayah_surah_number_idx"),
        ]
        verbose_name = "ayah"
        verbose_name_plural = "ayahs"

    def __str__(self) -> str:
        return f"{self.surah_id}:{self.number}"
