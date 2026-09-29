# Imagen del backend Django y del worker SNMP (mismo código, distinto comando).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt requirements-prod.txt ./
RUN pip install --no-cache-dir -r requirements-prod.txt

COPY backend/ backend/
COPY sonar/ sonar/
COPY scripts/ scripts/

RUN useradd --create-home sonar && mkdir -p /app/staticfiles && chown sonar /app/staticfiles
USER sonar

EXPOSE 8000
CMD ["gunicorn", "--chdir", "backend", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
