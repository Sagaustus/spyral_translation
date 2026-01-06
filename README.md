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

## Heroku

### Config vars
Set these on Heroku (Settings → Config Vars):

- `DJANGO_SECRET_KEY`: required (set to a strong random value)
- `DJANGO_DEBUG`: set to `0`
- `DATABASE_URL`: your Heroku Postgres URL (usually set automatically when you add Heroku Postgres)
- `DJANGO_ALLOWED_HOSTS`: recommended, e.g. `transvoyant-d8b09fbc14d3.herokuapp.com`

Note: this repo also includes a small safety-net to allow `.herokuapp.com` automatically when running on Heroku, so forgetting `DJANGO_ALLOWED_HOSTS` won’t usually cause a blanket 400. Still, it’s best practice to set `DJANGO_ALLOWED_HOSTS` explicitly.

### Migrations
If you’re using the provided `Procfile` release phase, migrations will run on deploy. Otherwise:

- `heroku run python manage.py migrate -a <app>`

### Create a superuser (safe)
Avoid passing passwords via CLI args (they can end up in shell history/logs). Create/update the user, then set the password interactively:

- `heroku run python manage.py shell -a <app>`

```python
from django.contrib.auth import get_user_model
User = get_user_model()

u, _ = User.objects.get_or_create(
	username="sagaust",
	defaults={"email": "austineaf@gmail.com"},
)
u.is_staff = True
u.is_superuser = True
u.save()
```

- `heroku run python manage.py changepassword sagaust -a <app>`