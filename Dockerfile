FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENTRYPOINT ["python", "docker-entrypoint.py"]
CMD ["uvicorn", "backend.api:app", "--host", "0.0.0.0", "--port", "8000"]
