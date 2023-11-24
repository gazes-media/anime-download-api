import asyncio
import glob
import os
import subprocess
import urllib.parse
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, BinaryIO, Literal

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, StreamingResponse

from async_downloader import download_form_m3u8, get_available_qualities

CHUNK_SIZE = 1024 * 1024

app = FastAPI()


class Status(Enum):
    STARTED = "started"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    ERROR = "error"


class Quality(Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(kw_only=True)
class Download:
    id: str
    origin_url: str
    quality: Quality
    status: Status
    process: subprocess.Popen[bytes] | None = None
    tasks: list[asyncio.Task[None]] = field(default_factory=list)
    total_seconds: float | None = None
    seconds_processed: float = 0

    @property
    def progress(self) -> float | None:
        if self.total_seconds is None:
            return None
        return round((self.seconds_processed / self.total_seconds * 100), 2)

    @property
    def video_path(self) -> Path:
        return Path(f"./tmp/{self.id}.mp4")


cached_downloads: dict[str, Download] = {}


def get_download(url: str, quality: Quality) -> Download | None:
    for download in cached_downloads.values():
        if download.origin_url == url and download.quality == quality:
            return download
    return None


for file in glob.glob("./tmp/*"):
    os.remove(file)


@app.get("/download")
async def download(url: str, quality: Quality = Quality.HIGH):
    url_parts = urllib.parse.urlsplit(url)
    url_parts._replace(query=f"url={urllib.parse.quote(url_parts.query[4:])}")
    url = f"{url_parts.scheme}://{url_parts.netloc}{url_parts.path}?url={urllib.parse.quote(url_parts.query[4:])}"

    if (download := get_download(url, quality)) is None:
        id = str(uuid.uuid4())
        download = cached_downloads[id] = Download(
            id=id, origin_url=url, quality=quality, status=Status.STARTED
        )

        qualities = await get_available_qualities(url)
        qualities = tuple(qualities.values())

        video_url: str
        match quality:
            case Quality.HIGH:
                video_url = qualities[0]
            case Quality.MEDIUM:
                video_url = qualities[len(qualities) // 2]
            case Quality.LOW:
                video_url = qualities[-1]

        process, duration = await download_form_m3u8(video_url, f"./tmp/{id}.mp4")
        download.process = process
        download.total_seconds = duration
        download.tasks.append(asyncio.create_task(download_task(download)))

    response_json: dict[str, Any] = {
        "status": str(download.status),
        "id": download.id,
        "result": None,
    }

    for task in download.tasks:
        if task.done():
            download.tasks.remove(task)
            if (e := task.exception()) is not None:
                download.status = Status.ERROR
                response_json.update({"message": str(e)})

    if download.status is Status.DONE:
        response_json.update({"result": f"/result?id={download.id}"})
        return response_json
    if download.status is Status.ERROR:
        return JSONResponse(status_code=500, content=response_json)
    if download.status is Status.IN_PROGRESS:
        response_json.update({"progress": download.progress})
        return response_json

    return response_json


@app.get("/result")
async def result(id: str, request: Request):
    if (download := cached_downloads.get(id)) is None:
        return Response(status_code=404, content="Link expired or invalid.")

    if download.status is not Status.DONE:
        return Response(status_code=425, content="Conversion not finished.")

    return range_requests_response(request, download.video_path, "video/mp4")


async def download_task(download: Download) -> None:
    download.status = Status.IN_PROGRESS
    process = download.process
    if process is None or download.total_seconds is None:
        return

    while process.poll() is None:
        if (progress := check_progression(f"./tmp/{download.id}-progress.txt")) is None:
            await asyncio.sleep(1)
            continue
        if progress == "end":
            download.status = Status.DONE
            break
        download.status = Status.IN_PROGRESS
        download.seconds_processed = progress
        await asyncio.sleep(1)

    if process.poll() == 0:
        download.status = Status.DONE
    else:
        download.status = Status.ERROR


def check_progression(file: str) -> float | Literal["end"] | None:
    if not os.path.exists(file):
        return None
    with open(file, "r") as f:
        # Seek to the end of the file
        f.seek(0, 2)
        end_pos = f.tell()

        def analyze_line(line: str) -> float | Literal["end"] | None:
            if line.startswith("progress=") and line.endswith("end"):
                return "end"
            if line.startswith("out_time_ms="):
                return float(line.split("=")[1]) / 1_000_000
            return None

        line: list[str] = []
        for pos in range(end_pos - 1, -1, -1):
            f.seek(pos, 0)
            char = f.read(1)
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


def range_requests_response(request: Request, file_path: str | Path, content_type: str):
    """Returns StreamingResponse using Range Requests of a given file"""

    file_size = os.stat(file_path).st_size
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


def clean_up(id: str):
    if os.path.exists(f"./tmp/{id}.m3u8"):
        os.remove(f"./{id}.m3u8")
    if os.path.exists(f"./tmp/{id}.mp4"):
        os.remove(f"./tmp/{id}.mp4")


# async def watcher(id: str):
#     process_state = current_processes[id]
#     while process_state.process is None:
#         await asyncio.sleep(1)

#     await asyncio.get_event_loop().run_in_executor(
#         None, process_state.process.wait, 10 * 60
#     )
#     await asyncio.sleep(10 * 60)
#     await asyncio.get_event_loop().run_in_executor(None, clean_up, id)
