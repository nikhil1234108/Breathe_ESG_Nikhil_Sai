# Use official lightweight Python image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir gunicorn

# Copy project files
COPY . /app/

# Expose Django port
EXPOSE 8000

# Run migrations and start gunicorn
CMD python manage.py migrate --noinput && \
    python manage.py seed_data && \
    gunicorn breathe_esg_backend.wsgi:application --bind 0.0.0.0:$PORT
