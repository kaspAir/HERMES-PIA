FROM python:3.12-slim

# Nicht als root laufen
RUN useradd --create-home --shell /bin/bash methodos

WORKDIR /app

# Dependencies zuerst (Docker-Layer-Cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Quellcode
COPY --chown=methodos:methodos . .

# Datenbankverzeichnis (wird als Volume gemountet)
RUN mkdir -p /app/data && chown methodos:methodos /app/data

USER methodos

ENV DATABASE_URL=sqlite:////app/data/methodos.db
ENV FLASK_DEBUG=0

EXPOSE 5000

# Gunicorn: 2 Worker-Prozesse, 120s Timeout (wegen LLM-Calls)
CMD ["gunicorn", "run:app", \
     "--bind", "0.0.0.0:5000", \
     "--workers", "2", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
