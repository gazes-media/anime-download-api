import base64
import json
import os
import re
import subprocess
from typing import Any, NamedTuple
from urllib.parse import urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup

from .constants import BASE_URL
from .utils import set_worker

VIDEO_REGEX = re.compile(r"video\[0\] = '(.+)';", re.MULTILINE)
M3U8_REGEX = [
    re.compile(r'e\.parseJSON\(atob\(t\).slice\(2\)\)\}\(\"([^;]*)"\),'),
    re.compile(r'e\.parseJSON\(n\)}\(\"([^;]*)"\),'),
    re.compile(r'n=atob\("([^"]+)"'),
]
M3U8_RES = re.compile(r"#EXT-X-STREAM-INF:.+RESOLUTION=(\d+x\d+).+")

client = httpx.AsyncClient()


class Context(NamedTuple):
    url: str
    subtitles: str | None


async def get_m3u8(url: str) -> Context:
    url_split: list[Any] = list(urlparse(url))
    url_split[1] = BASE_URL
    episode_url: str = urlunparse(url_split)  # type: ignore

    response = await client.get(episode_url)

    if not (match := VIDEO_REGEX.search(response.text)):
        raise ValueError("No source found")

    response = await client.get(set_worker(match.group(1)))
    soup = BeautifulSoup(response.text, features="html.parser")

    scripts = soup.find_all("script")
    sources = [script["src"] for script in scripts if script.get("src")]

    for src in sources:
        try:
            script_content = (await client.get(set_worker(src))).text
        except httpx.HTTPError as e:
            continue
        b64_m3u8: str | None = None
        for regex in M3U8_REGEX:
            if match := regex.search(script_content):
                b64_m3u8 = match.group(1)
                break

        if b64_m3u8:
            raw = base64.b64decode(b64_m3u8).decode("utf-8")
            if "|||" in raw:
                raw = raw.split("|||")[1]
            if raw.startswith("{") and raw[1] != '"':
                raw = raw[1 + raw[1:].find("{") :]
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as e:
                print("Something waw wrong with this json :", raw)
                raise e

            url = next(
                set_worker(value)
                for value in data.values()
                if isinstance(value, str) and value.startswith("https")
            )

            subtitles = data.get("subtitles")
            return Context(url, subtitles)
    raise ValueError("No m3u8 found")


async def get_available_qualities(ctx: Context) -> dict[str, str]:
    response = await client.get(ctx.url)

    if not response.text.startswith("#EXTM3U"):
        raise ValueError("Not a m3u8 file")

    lines = iter(response.text.splitlines())
    next(lines)
    qualities: dict[str, str] = {}
    for line in lines:
        if line.startswith("#EXT"):
            if match := M3U8_RES.search(line):
                quality = match.group(1)
                qualities[quality] = next(lines)
    return qualities


async def download_form_m3u8(
    url: str, output: str
) -> tuple[subprocess.Popen[bytes], float]:
    filename = os.path.splitext(os.path.basename(output))[0]
    if not os.path.exists("./tmp"):
        os.mkdir("./tmp")

    with open(f"./tmp/{filename}.m3u8", "wb") as f:
        response = await client.get(url)
        f.write(response.content)  # worker is already set
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
        "-crf",
        "1",
        output,
    ]

    process = subprocess.Popen(
        args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    return process, total_duration
