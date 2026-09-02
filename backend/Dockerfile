FROM python:3.12-slim-bookworm

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set working directory
WORKDIR /app

# Install system dependencies
# ffmpeg renders clip cards (clips/rendering.py): libx264 + AAC come from
# libavcodec, and showwaves/blend/ass from libavfilter, which pulls libass.
# fonts-noto-core carries NotoNaskhArabic-Regular.ttf — the exact face
# clips/subtitles.py asks for. fontconfig substitutes silently, so a missing
# font renders tofu boxes into a shareable video rather than failing; the
# assertions below turn that into a build failure instead.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        ffmpeg \
        fonts-noto-core \
        fontconfig \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && fc-cache -f \
    && for f in ass showwaves blend; do \
           ffmpeg -hide_banner -filters | awk '{print $2}' | grep -qx "$f" || exit 1; \
       done \
    && for e in libx264 aac; do \
           ffmpeg -hide_banner -encoders | awk '{print $2}' | grep -qx "$e" || exit 1; \
       done \
    && fc-match 'Noto Naskh Arabic' | grep -q NotoNaskhArabic

# Install Python dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy entrypoint script
COPY entrypoint.sh /app/
RUN chmod +x /app/entrypoint.sh

# Copy project files
COPY . /app/

# Set entrypoint
ENTRYPOINT ["/app/entrypoint.sh"]

# Expose Django port
EXPOSE 8000

# Default command for development
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
