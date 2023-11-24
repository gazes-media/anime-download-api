FROM python:3.12-alpine
WORKDIR /app
ENV PYTHONUNBUFFERED=0
COPY requirements.txt ./
RUN pip install -r requirements.txt && apk add ffmpeg
COPY ./src .
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8080"]
