FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY collector.py .
COPY config.example.yaml ./config.yaml

RUN mkdir -p /data
ENV EDGE_CONFIG_PATH=/app/config.yaml

CMD ["python", "collector.py"]
