"""Background automation scheduler for SMART AGRIASSIST.

Runs the agricultural automations (weather retrieval, severe alert detection,
crop stage tracking, and reminder generation) periodically in a background
daemon thread without requiring the dashboard to remain open.
"""

from datetime import datetime
import logging
import os
import sys
import threading
import time

logger = logging.getLogger('agricultural.scheduler')

_scheduler_thread = None
_stop_event = threading.Event()


def _scheduler_loop(interval_seconds: int = 600):
    """Background worker loop executing the 12 agricultural workflows."""
    logger.info('Agricultural background scheduler loop started (interval=%ds).', interval_seconds)
    # Wait a short grace period on startup before first run
    time.sleep(5)

    while not _stop_event.is_set():
        try:
            from apps.core.automation import run_all_agricultural_automations
            logger.info('Executing scheduled agricultural automations...')
            result = run_all_agricultural_automations()
            data = result.to_dict()
            logger.info(
                'Scheduled automations completed: %d users, %d alerts, %d reminders, %d reminder notifications.',
                data['users_processed'],
                data['weather_alerts_generated'],
                data['reminders_generated'],
                data['reminder_notifications_sent'],
            )
        except Exception as exc:
            logger.error('Error in agricultural background scheduler cycle: %s', exc)

        # Sleep in small slices to respond promptly to stop event
        elapsed = 0
        while elapsed < interval_seconds and not _stop_event.is_set():
            time.sleep(2)
            elapsed += 2

    logger.info('Agricultural background scheduler loop stopped.')


def start_background_scheduler(interval_seconds: int = 600):
    """Start the background scheduler thread if not already running."""
    global _scheduler_thread

    # Skip in test environment or management commands that do not run a server
    if 'test' in sys.argv or 'makemigrations' in sys.argv or 'migrate' in sys.argv:
        return

    # In development runserver, Django uses an auto-reloader that spawns a child process.
    # We only start the thread in the child process (where RUN_MAIN == 'true').
    if 'runserver' in sys.argv and os.environ.get('RUN_MAIN') != 'true':
        return

    if _scheduler_thread is not None and _scheduler_thread.is_alive():
        return

    _stop_event.clear()
    _scheduler_thread = threading.Thread(
        target=_scheduler_loop,
        args=(interval_seconds,),
        name='AgriAssistBackgroundScheduler',
        daemon=True,
    )
    _scheduler_thread.start()
    logger.info('Agricultural background scheduler started as daemon thread.')


def stop_background_scheduler():
    """Signal the background scheduler thread to terminate."""
    global _scheduler_thread
    _stop_event.set()
    if _scheduler_thread is not None and _scheduler_thread.is_alive():
        _scheduler_thread.join(timeout=3)
        _scheduler_thread = None
