release: python manage.py migrate --noinput && python manage.py createcachetable && python manage.py collectstatic --noinput
web: gunicorn midrus.wsgi --workers ${WEB_CONCURRENCY:-3} --timeout 60 --bind 0.0.0.0:${PORT:-8000} --log-file -
