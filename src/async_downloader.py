import asyncio
import os
import re
import subprocess
from typing import NamedTuple

import aiofiles
import httpx

M3U8_RES = re.compile(
    r"#EXT-X-STREAM-INF:.+RESOLUTION=(?P<width>\d+)x(?P<height>\d+).+"
)

client = httpx.AsyncClient()


class Context(NamedTuple):
    url: str
    subtitles: str | None


class Quality(NamedTuple):
    url: str
    width: int
    height: int


class M3U8(NamedTuple):
    url: str
    image_url: str


async def get_m3u8_url(anime_id: int, episode: int, lang: str) -> M3U8:
    url = f"https://api.gazes.fr/anime/animes/{anime_id}/{episode}"
    response = (await client.get(url)).json()
    if response["success"] != True:
        raise ValueError(response["message"])

    data = response["data"].get(lang)
    if data is None:
        raise ValueError(
            f"Language {lang} is not available for anime {anime_id} and episode {episode}"
        )

    return M3U8(url=data["videoUri"], image_url=data["url_image"])


async def get_available_qualities(url: str) -> list[Quality]:
    response = await client.get(url)

    if not response.text.startswith("#EXTM3U"):
        raise ValueError("Not a m3u8 file")

    lines = iter(response.text.splitlines())
    next(lines)
    qualities: list[Quality] = []
    for line in lines:
        if line.startswith("#EXT"):
            if match := M3U8_RES.search(line):
                width, height = map(int, match.groups())
                qualities.append(Quality(url=next(lines), width=width, height=height))
    return qualities


async def download_form_m3u8(
    url: str, output: str
) -> tuple[asyncio.subprocess.Process, float]:
    filename = os.path.splitext(os.path.basename(output))[0]

    async with aiofiles.open(f"./tmp/{filename}.m3u8", "wb") as f:
        response = await client.get(url)
        await f.write(response.content)
        total_duration = sum(map(float, re.findall(r"#EXTINF:([\d.]+)", response.text)))

    args = [
        "ffmpeg",
        "-progress",
        f"./tmp/{filename}-progress.txt",
        "-y",  # overwrite output file
        "-protocol_whitelist",
        "file,http,https,tcp,tls,crypto",
        "-i",
        f"./tmp/{filename}.m3u8",
        "-bsf:a",
        "aac_adtstoasc",
        "-c",
        "copy",
        "-vcodec",
        "copy",
        # "-crf",
        # "1",
        output,
    ]

    process = await asyncio.create_subprocess_exec(
        *args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    return process, total_duration
