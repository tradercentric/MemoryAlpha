FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PORT=8080
ENV GCS_BUCKET=memory-alpha-397310840166
CMD exec gunicorn --bind :$PORT -w 2 app:app
