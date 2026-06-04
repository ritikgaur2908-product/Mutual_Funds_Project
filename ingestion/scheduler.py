"""
scheduler.py
------------
Daily cron scheduler using APScheduler.
Triggers the full ingestion pipeline at 00:00 UTC every day to refresh
the vector store with the latest data from the 7 Groww scheme URLs.
"""

import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger("scheduler")

# Global scheduler instance reference
_scheduler = None


def start_scheduler(job_function) -> None:
    """
    Initializes and starts the AsyncIOScheduler.
    Schedules the indexing task at 00:00 UTC daily.
    
    Args:
        job_function: The async function to execute during refresh.
    """
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        logger.warning("Daily scheduler is already running, skipping start.")
        return

    _scheduler = AsyncIOScheduler()
    
    # Configure trigger: 00:00 UTC daily
    trigger = CronTrigger(hour=0, minute=0, timezone="UTC")
    
    _scheduler.add_job(
        job_function,
        trigger=trigger,
        id="daily_indexing_refresh",
        name="Daily Scraping & Re-indexing Job",
        replace_existing=True
    )
    
    _scheduler.start()
    logger.info("Daily scheduler started. Job 'daily_indexing_refresh' scheduled for 00:00 UTC.")


def stop_scheduler() -> None:
    """
    Stops the daily scheduler if it is currently running.
    """
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown()
        logger.info("Daily scheduler shut down successfully.")
        _scheduler = None
