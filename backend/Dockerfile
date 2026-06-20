# HR5 Invest — backend image
FROM python:3.11-slim

WORKDIR /app

# System deps kept minimal; cryptography ships wheels so no build toolchain needed.
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
