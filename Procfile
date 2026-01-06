release: python manage.py migrate
web: gunicorn voyant_l10n_hub.wsgi:application --bind 0.0.0.0:$PORT --log-file -
