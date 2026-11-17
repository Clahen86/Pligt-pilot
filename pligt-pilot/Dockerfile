FROM docker.io/library/python:3.13-slim-bookworm

RUN pip install --no-cache-dir cryptography

COPY app /app
ENV PYTHONUNBUFFERED=1
CMD ["python3", "/app/main.py"]
