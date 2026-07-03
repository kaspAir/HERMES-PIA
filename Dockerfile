FROM python:3.12-slim

# Nicht als root laufen
RUN useradd --create-home --shell /bin/bash hermespia

WORKDIR /app

# Dependencies zuerst (Docker-Layer-Cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Quellcode
COPY --chown=hermespia:hermespia . .

# Datenbankverzeichnis (wird als Volume gemountet)
RUN mkdir -p /app/data && chown hermespia:hermespia /app/data

USER hermespia

ENV DATABASE_URL=sqlite:////app/data/hermespia.db
ENV FLASK_DEBUG=0

EXPOSE 5000

# Gunicorn: 2 Worker-Prozesse, 120s Timeout (wegen LLM-Calls)
CMD ["gunicorn", "run:app", \
     "--bind", "0.0.0.0:5000", \
     "--workers", "2", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
