FROM python:3.12-alpine
WORKDIR /app
ENV PYTHONUNBUFFERED=0
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && apk add ffmpeg --no-cache
COPY ./src .
EXPOSE 8080
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8080"]
