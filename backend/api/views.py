from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.db import connection
from django.core.cache import cache
from .tasks import test_celery_task
import logging

logger = logging.getLogger(__name__)

@api_view(['GET'])
def hello_world(request):
    """
    Simple hello world API endpoint.
    """
    return Response({
        "message": "Hello from the Django backend!",
        "status": "success"
    })

@api_view(['GET'])
def system_status(request):
    """
    Checks the status of the Database, Redis (via cache), and triggers a Celery task.
    """
    status = {
        "database": "down",
        "redis": "down",
        "celery": "unknown"
    }

    # Check database connection
    try:
        connection.ensure_connection()
        status["database"] = "up"
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        status["database"] = f"down: {str(e)}"

    # Check redis connection (Django cache backend)
    try:
        cache.set("health_check_key", "ok", timeout=5)
        val = cache.get("health_check_key")
        if val == "ok":
            status["redis"] = "up"
    except Exception as e:
        logger.error(f"Redis health check failed: {e}")
        status["redis"] = f"down: {str(e)}"

    # Trigger async celery task
    try:
        task = test_celery_task.delay(4, 5)
        status["celery"] = {
            "status": "triggered",
            "task_id": task.id
        }
    except Exception as e:
        logger.error(f"Celery task trigger failed: {e}")
        status["celery"] = f"failed to trigger: {str(e)}"

    return Response(status)
