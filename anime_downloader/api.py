import asyncio
import glob
import os
import subprocess
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Response
from httpcore import Origin

from .async_downloader import (download_form_m3u8, get_available_qualities,
                               get_m3u8)

app = FastAPI()


@dataclass
class ProcessState:
    url: str
    tasks: list[asyncio.Task[Any]]
    process: subprocess.Popen[bytes] | None = None
    message: str | None = None


current_processes: dict[str, ProcessState] = {}


for file in glob.glob("./tmp/*"):
    os.remove(file)


@app.get("/from-link")
async def from_link(link: str):
    id = str(uuid.uuid4())
    print(link)
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
        current.process = await download_form_m3u8(quality, f"./tmp/{id}.mp4")
    except Exception as e:
        current.message = str(e)

        return


@app.get("/get-status")
async def id(id: str):
    if id not in current_processes:
        return {"status": "process not found", "message": ""}
    process_state = current_processes[id]
    if process_state.process is None:
        return {"status": "not started", "message": process_state.message or ""}
    if process_state.process.poll() is None:
        return {"status": "in progress..", "message": process_state.message or ""}

    with open(f"./tmp/{id}.mp4", "rb") as f:
        return Response(f.read(), media_type="video/mp4")


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
