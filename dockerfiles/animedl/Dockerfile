FROM python:3.11.3-alpine3.17
WORKDIR /app
ENV PYTHONUNBUFFERED=0
COPY requirements.txt ./
RUN pip install -r requirements.txt && apk add ffmpeg
COPY . .
RUN ls
CMD ["uvicorn", "anime_downloader.api:app", "--host", "0.0.0.0", "--reload"]
