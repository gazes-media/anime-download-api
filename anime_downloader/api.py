import asyncio
import glob
import os
import subprocess
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from fastapi import FastAPI, Response

from .async_downloader import download_form_m3u8, get_available_qualities, get_m3u8

app = FastAPI()


@dataclass
class ProcessState:
    url: str
    tasks: list[asyncio.Task[Any]]
    process: subprocess.Popen[bytes] | None = None
    message: str | None = None
    duration: float | None = None


current_processes: dict[str, ProcessState] = {}


for file in glob.glob("./tmp/*"):
    os.remove(file)


@app.get("/from-link")
async def from_link(link: str):
    id = str(uuid.uuid4())
    current = current_processes[id] = ProcessState(link, [])
    current.tasks.append(asyncio.create_task(handle_download(id)))
    current.tasks.append(asyncio.create_task(watcher(id)))
    return {"status_id": id, "status_link": f"/get-status?id={id}"}


async def handle_download(id: str):
    current = current_processes[id]
    try:
        ctx = await get_m3u8(current.url)
    except Exception as e:
        current.message = str(e)
        return

    try:
        qualities = await get_available_qualities(ctx)
    except Exception as e:
        current.message = str(e)
        return

    quality = next(iter(qualities.values()))

    try:
        current.process, duration = await download_form_m3u8(quality, f"./tmp/{id}.mp4")
    except Exception as e:
        current.message = str(e)
        return

    current.duration = duration


@app.get("/get-status")
async def id(id: str):
    current = current_processes.get(id)
    if current is None:
        return {"status": "error", "message": "Process not found"}

    if current.process is None:
        return {"status": "starting", "message": "The process is starting..."}

    if current.process.poll() is None:
        value = check_progression(f"./tmp/{id}-progress.txt")
        if value == "end":
            return {
                "status": "done",
                "message": "You can now download the file.",
                "download_link": f"/get-file?id={id}",
            }
        if value is None or current.duration is None:
            return {"status": "working", "message": "In progression..."}
        return {
            "status": "working",
            "message": "In progression...",
            "progress": value / current.duration,
        }


@app.get("/get-file")
async def get_file(id: str):
    if (
        (current := current_processes.get(id)) is None
        or current.process is None
        or current.process.poll() is None
    ):
        return {"status": "error", "message": "File not found."}

    with open(f"./tmp/{id}.mp4", "rb") as f:
        return Response(f.read(), media_type="video/mp4")


def check_progression(file: str) -> float | Literal["end"] | None:
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


def clean_up(id: str):
    if os.path.exists(f"./tmp/{id}.m3u8"):
        os.remove(f"./{id}.m3u8")
    if os.path.exists(f"./tmp/{id}.mp4"):
        os.remove(f"./tmp/{id}.mp4")


async def watcher(id: str):
    process_state = current_processes[id]
    while process_state.process is None:
        await asyncio.sleep(1)

    await asyncio.get_event_loop().run_in_executor(
        None, process_state.process.wait, 10 * 60
    )
    await asyncio.sleep(10 * 60)
    await asyncio.get_event_loop().run_in_executor(None, clean_up, id)
