FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir pillow==11.3.0
COPY src/ src/
COPY config/ config/
ENV PYTHONUNBUFFERED=1
CMD ["python", "src/server.py"]
