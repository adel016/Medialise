FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Installer les dépendances de l'app
COPY ../frontend_backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Forcer une version récente du client Qdrant (avec search_points)
RUN pip install --no-cache-dir "qdrant-client>=1.6.0"

# Copier le code de l'application
COPY ../frontend_backend/ .

ENV PYTHONUNBUFFERED=1
EXPOSE 5000

CMD ["python", "app.py"]
