from __future__ import annotations

import asyncio
import datetime as dt
import logging
from collections import deque
from typing import TYPE_CHECKING, Any

from aiofiles import os

if TYPE_CHECKING:
    from api import Download, QualityInput

logger = logging.getLogger(__name__)


class DownloadCache:
    def __init__(self) -> None:
        self._maxlen = 20
        self._cache: deque[Download] = deque(maxlen=self._maxlen)

    def __len__(self) -> int:
        return len(self._cache)

    def __iter__(self) -> Any:
        return iter(self._cache)

    def update(self, value: Download) -> None:
        self._cache.remove(value)
        self._cache.append(value)
        value.last_access = dt.datetime.now()

    def get(self, id: str) -> Download | None:
        value = next((dl for dl in self._cache if dl.id == id), None)
        if value is not None:
            self.update(value)
        return value

    async def add(self, value: Download) -> None:
        if self._maxlen <= len(self._cache):
            value = self._cache.popleft()
            await self.clean(value)

        value.last_access = dt.datetime.now()
        self._cache.append(value)

    async def remove(self, value: Download) -> None:
        self._cache.remove(value)
        await self.clean(value)

    async def clean(self, value: Download) -> None:
        if value.process.returncode is None:
            value.process.terminate()
        if value.task is not None:
            value.task.cancel()

        id_ = value.id
        if await os.path.exists(f"./tmp/{id_}.mp4"):
            await os.remove(f"./tmp/{id_}.mp4")
        if await os.path.exists(f"./tmp/{id_}-progress.txt"):
            await os.remove(f"./tmp/{id_}-progress.txt")
        if await os.path.exists(f"./tmp/{id_}.m3u8"):
            await os.remove(f"./tmp/{id_}.m3u8")

    def retrieve(
        self, anime_id: int, episode: int, lang: str, quality: QualityInput
    ) -> Download | None:
        for download in self._cache:
            if (
                download.anime_id == anime_id
                and download.episode == episode
                and download.lang == lang
                and download.quality == quality
            ):
                self.update(download)
                return download
        return None

    async def cleaner(self):
        logger.info("Starting cleaner")
        while True:
            if len(self) and self._cache[0].expired:
                download = self._cache.popleft()
                await self.clean(download)
                logger.info(f"{download.id} removed from cache.")

            await asyncio.sleep(max((dl.expiration_time for dl in self), default=60))
