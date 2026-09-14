"""Background task that periodically deletes expired jobs."""
from __future__ import annotations

import asyncio
import logging

from app.config import get_settings
from app.services.storage import store

logger = logging.getLogger("app.cleanup")


async def cleanup_loop(stop_event: asyncio.Event) -> None:
    interval = get_settings().cleanup_interval_seconds
    logger.info("cleanup loop started (interval=%ss)", interval)
    try:
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass  # interval elapsed -> run a sweep
            if stop_event.is_set():
                break
            removed = await asyncio.to_thread(store.sweep_expired)
            if removed:
                logger.info("cleanup removed %d expired job(s)", removed)
    except asyncio.CancelledError:
        raise
    finally:
        logger.info("cleanup loop stopped")
