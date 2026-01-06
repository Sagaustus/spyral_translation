# Voyant Skin Translation Hub

Minimal Django starter for the Voyant translation workflow.

## Setup
- Use Python 3.12 and create a virtualenv.
- Install deps: `pip install -r requirements.txt -r requirements-dev.txt`.
- Copy your Voyant CSV to `data/voyant_strings.csv` (a placeholder `.keep` is present).

## Running
- Start Postgres: `docker compose up -d`.
- Run migrations: `python manage.py migrate`.
- Create admin: `python manage.py createsuperuser`.
- Start the app: `python manage.py runserver`.
- Run tests: `pytest`.
- Lint/format: `pre-commit run --all-files`.