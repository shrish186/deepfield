FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir -r requirements-dev.txt

COPY . .

EXPOSE 8000

# Shell form so ${PORT} expands. Hosts like Railway inject PORT; locally it
# defaults to 8000 (matching docker-compose's published port).
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
