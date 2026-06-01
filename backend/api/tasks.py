from celery import shared_task
import time

@shared_task
def test_celery_task(x, y):
    """
    A simple task that simulates a long-running calculation.
    """
    time.sleep(2)
    return x + y
