FROM python:3.10-slim

WORKDIR /app

# The in-cluster cache shields builds from repeated WAN downloads, but a new
# wheel's first fill still crosses the capped upstream link. pip's 15-second
# read default killed both architecture builds while nginx was correctly
# completing that cold fill. Keep the build bounded but tolerant of the first
# fetch; subsequent cached reads remain local and complete in milliseconds.
ENV PIP_DEFAULT_TIMEOUT=180 \
    PIP_RETRIES=20

# Install system dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        postgresql-client \
        jq \
        build-essential \
        libpq-dev \
        netcat-traditional \
        supervisor \
        vim \
        curl \
        wget \
        libmagic1 \
        libjpeg-dev \
        zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . /app/

# Create required directories
RUN mkdir -p /var/log/django /var/log/supervisor /app/media /app/staticfiles

# Collect static files
RUN JWT_SECRET_KEY=build-static-only POSTGRES_PASSWORD=build-static-only python manage.py collectstatic --noinput

# Copy entrypoint script
COPY docker-entrypoint.sh /app/
RUN chmod +x /app/docker-entrypoint.sh

# Copy supervisord config
COPY supervisord.conf /app/

EXPOSE 8013 18105

ENTRYPOINT ["/app/docker-entrypoint.sh"]
