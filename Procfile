web: gunicorn app:app --bind 0.0.0.0:$PORT
worker: celery -A celery_worker.celery worker --loglevel=info
beat: celery -A celery_worker.celery beat --loglevel=info
