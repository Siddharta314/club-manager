FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# System dependencies for Pillow + psycopg build fallback
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        libjpeg-dev \
        libpng-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first to leverage Docker layer cache
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && pip install -r /app/requirements.txt

# Copy application
COPY . /app

EXPOSE 8000

CMD ["gunicorn", "padel.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]