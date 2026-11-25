FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends gosu && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd --create-home --uid 10001 kitaptakipappuser && chown -R kitaptakipappuser:kitaptakipappuser /app && sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "-b", "0.0.0.0:5010", "--workers", "2", "--timeout", "60", "application:app"]
