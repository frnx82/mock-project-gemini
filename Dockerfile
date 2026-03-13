# Pass your internal trivy image as an argument (defaults to the public one)
ARG TRIVY_IMAGE=aquasec/trivy:latest

# Stage 1: Extract Trivy binary
FROM ${TRIVY_IMAGE} as trivy-source

# Stage 2: Build the Python app
FROM python:3.12-slim

# Copy the Trivy binary from the source image
COPY --from=trivy-source /usr/local/bin/trivy /usr/local/bin/trivy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

CMD ["gunicorn", "-k", "geventwebsocket.gunicorn.workers.GeventWebSocketWorker", "-w", "1", "--timeout", "300", "--keep-alive", "120", "--graceful-timeout", "30", "-b", "0.0.0.0:8080", "app:app"]

