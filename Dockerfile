# Stage 1: Build Frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend ./
RUN npm run build

# Stage 2: Build Python Backend
FROM python:3.12-slim
RUN apt-get update && apt-get install -y libpq-dev gcc default-libmysqlclient-dev ca-certificates && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend files
COPY . .

# Copy built frontend from Stage 1
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# Create non-root user for security
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser && \
    mkdir -p /app/runtime && \
    chown -R appuser:appgroup /app

USER appuser

EXPOSE 5003

# Run Gunicorn WSGI server
CMD ["gunicorn", "--bind", "0.0.0.0:5003", "--timeout", "120", "--workers", "4", "--threads", "4", "--max-requests", "1000", "--max-requests-jitter", "100", "app:app"]
