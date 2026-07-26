FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Installer les dépendances de l'app
# NOTE: le build context est la racine du projet (voir docker-compose.yml: context: ..)
COPY frontend_backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copier le code de l'application
COPY frontend_backend/ .

# Copier aussi le dossier scrapers (à la racine du projet Medialise)
COPY scrapers/ ./scrapers/

# Compiler les traductions Flask-Babel
RUN if [ -d "translations" ]; then \
    pybabel compile -d translations -l fr && \
    pybabel compile -d translations -l en && \
    pybabel compile -d translations -l ar; \
    fi

ENV PYTHONUNBUFFERED=1
EXPOSE 5000

CMD ["python", "app.py"]
