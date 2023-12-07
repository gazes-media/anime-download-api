import asyncio
import datetime as dt
import glob
import logging
import uuid
from dataclasses import dataclass
from enum import Enum
from functools import partial
from pathlib import Path
from typing import Any, BinaryIO, Literal, cast

import aiofiles
from aiofiles import os
from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from async_downloader import (
    Quality,
    download_form_m3u8,
    get_available_qualities,
    get_m3u8_url,
)
from download_cache import DownloadCache

CHUNK_SIZE = 1024 * 1024

app = FastAPI()
logger = logging.getLogger(__name__)
cached_downloads = DownloadCache()
background_tasks: set[asyncio.Task[Any]] = set()


class Status(Enum):
    STARTED = "started"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    ERROR = "error"


class QualityInput(Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(kw_only=True)
class Download:
    id: str
    anime_id: int
    episode: int
    lang: str
    image_url: str
    quality: QualityInput
    status: Status
    process: asyncio.subprocess.Process
    last_access: dt.datetime
    total_seconds: float
    seconds_processed: float = 0
    remaining_time: float | None = None
    error_message: str | None = None
    task: asyncio.Task[Any] | None = None
    width: int
    height: int

    def __eq__(self, __value: object) -> bool:
        if not isinstance(__value, Download):
            return False
        return self.id == __value.id

    def __hash__(self) -> int:
        return hash(self.id)

    @property
    def progress(self) -> float | None:
        return self.seconds_processed / self.total_seconds

    @property
    def video_path(self) -> Path:
        return Path(f"./tmp/{self.id}.mp4")

    @property
    def expiration_time(self) -> float:
        return (
            self.last_access - dt.datetime.now() + dt.timedelta(hours=12)
        ).total_seconds()

    @property
    def expired(self) -> float:
        return self.expiration_time < 0


@app.on_event("startup")
async def startup_event():
    if not await os.path.exists("./tmp"):
        await os.mkdir("./tmp")

    logger.info("Cleaning up tmp folder")
    for file in glob.glob("./tmp/*"):
        await os.remove(file)

    background_tasks.add(asyncio.create_task(cached_downloads.cleaner()))


@app.get("/download/{anime_id}/{episode}/{lang}")
async def download(
    anime_id: int, episode: int, lang: str, quality: QualityInput = QualityInput.HIGH
):
    download = cached_downloads.retrieve(anime_id, episode, lang, quality)
    if download is None:
        m3u8 = await get_m3u8_url(anime_id, episode, lang)
        id = str(uuid.uuid4())

        qualities = await get_available_qualities(m3u8.url)
        qualities = sorted(qualities, key=lambda q: q.width * q.height)

        video_quality: Quality
        match quality:
            case QualityInput.HIGH:
                video_quality = qualities[0]
            case QualityInput.MEDIUM:
                video_quality = qualities[len(qualities) // 2]
            case QualityInput.LOW:
                video_quality = qualities[-1]

        process, duration = await download_form_m3u8(
            video_quality.url, f"./tmp/{id}.mp4"
        )
        download = Download(
            id=id,
            anime_id=anime_id,
            episode=episode,
            lang=lang,
            image_url=m3u8.image_url,
            quality=quality,
            status=Status.STARTED,
            last_access=dt.datetime.now(),
            process=process,
            total_seconds=duration,
            width=video_quality.width,
            height=video_quality.height,
        )
        await cached_downloads.add(download)

        task = asyncio.create_task(download_task(download))
        download.task = task
        background_tasks.add(task)
        task.add_done_callback(partial(discard, download))

    response_json: dict[str, Any] = {
        "status": str(download.status),
        "id": download.id,
        "result": None,
    }

    if download.status is Status.DONE:
        response_json.update({"result": f"/result/{download.id}"})
        return response_json
    if download.status is Status.ERROR:
        response_json.update({"message": str(download.error_message)})
        await cached_downloads.remove(download)
        return JSONResponse(status_code=500, content=response_json)
    if download.status is Status.IN_PROGRESS:
        response_json.update(
            {
                "progress": round(download.progress * 100, 2)
                if download.progress
                else None,
                "estimated_remaining_time": round(download.remaining_time, 2)
                if download.remaining_time
                else None,
            }
        )
        return response_json

    return response_json


@app.get("/result/{id}")
async def result(id: str, request: Request):
    download = cached_downloads.get(id)
    if download is None or download.status is not Status.DONE:
        return Response(status_code=404, content="Link expired, not ready or invalid.")

    response = (
        '<meta name="twitter:card" content="player">\n'
        '<meta name="twitter:player" content="{video_url}">\n'
        '<meta name="twitter:player:stream" content="{video_url}">\n'
        '<meta name="twitter:image" content="{image_url}">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta property="og:image" content="{image_url}">\n'
        '<meta property="og:type" content="video.other">\n'
        '<meta property="og:video:url" content="{video_url}">\n'
        '<meta property="og:video:width" content="{width}">\n'
        '<meta property="og:video:height" content="{height}">\n'
        '<meta name="twitter:player:width" content="{width}">\n'
        '<meta name="twitter:player:height" content="{height}">\n'
        '<meta http-equiv="refresh" content="0;URL={video_url}">'
    ).format(
        video_url=f"/result/video/{id}.mp4",
        width=download.width,
        height=download.height,
        image_url=download.image_url,
    )

    return HTMLResponse(response)


@app.get("/result/video/{id}.mp4")
async def serve_video(id: str, request: Request):
    if (download := cached_downloads.get(id)) is None:
        return Response(status_code=404, content="Link expired or invalid.")

    if download.status is not Status.DONE:
        return Response(status_code=425, content="Conversion not finished.")

    return await range_requests_response(request, download.video_path, "video/mp4")


def discard(download: Download, task: asyncio.Task[Any]):
    if task.cancelled():
        return
    if task.exception() is not None:
        download.status = Status.ERROR
        download.error_message = str(task.exception())
    background_tasks.discard(task)
    download.task = None


async def download_task(download: Download) -> None:
    download.status = Status.IN_PROGRESS

    async def update_download():
        start_time = dt.datetime.now()
        while True:
            await asyncio.sleep(1)
            seconds_processed = await check_progression(
                f"./tmp/{download.id}-progress.txt"
            )
            if seconds_processed is None:
                continue

            if seconds_processed == "end":
                break

            download.status = Status.IN_PROGRESS
            download.seconds_processed = seconds_processed
            progress = cast(float, download.progress)
            delta = dt.datetime.now() - start_time
            if progress > 0:
                download.remaining_time = (
                    delta.total_seconds() / progress - delta.total_seconds()
                )

    task = asyncio.create_task(update_download())
    await download.process.wait()
    print("Process finished", flush=True)
    task.cancel()

    if download.process.returncode == 0:
        download.status = Status.DONE
    else:
        download.status = Status.ERROR


async def check_progression(file: str) -> float | Literal["end"] | None:
    if not await os.path.exists(file):
        return None
    async with aiofiles.open(file, "r") as f:
        # Seek to the end of the file
        await f.seek(0, 2)
        end_pos = await f.tell()

        def analyze_line(line: str) -> float | Literal["end"] | None:
            if line.startswith("progress=") and line.endswith("end"):
                return "end"
            if line.startswith("out_time_ms="):
                return float(line.split("=")[1]) / 1_000_000
            return None

        line: list[str] = []
        for pos in range(end_pos - 1, -1, -1):
            await f.seek(pos, 0)
            char = await f.read(1)
            if char == "\n":
                result = analyze_line("".join(reversed(line)))
                if result is not None:
                    return result
                line = []
            else:
                line.append(char)


def send_bytes_range_requests(
    file_obj: BinaryIO, start: int, end: int, chunk_size: int = 10_000
):
    """Send a file in chunks using Range Requests specification RFC7233

    `start` and `end` parameters are inclusive due to specification
    """
    with file_obj as f:
        f.seek(start)
        while (pos := f.tell()) <= end:
            read_size = min(chunk_size, end + 1 - pos)
            yield f.read(read_size)


def _get_range_header(range_header: str, file_size: int) -> tuple[int, int]:
    def _invalid_range():
        return HTTPException(
            status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
            detail=f"Invalid request range (Range:{range_header!r})",
        )

    try:
        h = range_header.replace("bytes=", "").split("-")
        start = int(h[0]) if h[0] != "" else 0
        end = int(h[1]) if h[1] != "" else file_size - 1
    except ValueError:
        raise _invalid_range()

    if start > end or start < 0 or end > file_size - 1:
        raise _invalid_range()
    return start, end


async def range_requests_response(
    request: Request, file_path: str | Path, content_type: str
):
    """Returns StreamingResponse using Range Requests of a given file"""

    file_size = (await os.stat(file_path)).st_size
    range_header = request.headers.get("range")

    headers = {
        "content-type": content_type,
        "accept-ranges": "bytes",
        "content-encoding": "identity",
        "content-length": str(file_size),
        "access-control-expose-headers": (
            "content-type, accept-ranges, content-length, "
            "content-range, content-encoding"
        ),
    }
    start = 0
    end = file_size - 1
    status_code = status.HTTP_200_OK

    if range_header is not None:
        start, end = _get_range_header(range_header, file_size)
        size = end - start + 1
        headers["content-length"] = str(size)
        headers["content-range"] = f"bytes {start}-{end}/{file_size}"
        status_code = status.HTTP_206_PARTIAL_CONTENT

    return StreamingResponse(
        send_bytes_range_requests(open(file_path, mode="rb"), start, end),
        headers=headers,
        status_code=status_code,
    )
