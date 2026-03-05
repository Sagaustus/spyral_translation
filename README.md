# African Localization of Voyant Tools

A reproducible, AI-assisted pipeline for translating the **Voyant Tools** digital humanities
interface into African languages — starting with Yoruba and designed from the ground up to
extend to Hausa, Igbo, Swahili, Amharic, isiZulu, and beyond.

Built with Django 5.2. Deployed on Heroku. ML pipeline runs locally or on any GPU server.

---

## Table of Contents

1. [Project Background](#1-project-background)
2. [Architecture Overview](#2-architecture-overview)
3. [Repository Structure](#3-repository-structure)
4. [Data Model](#4-data-model)
5. [The Translation Pipeline](#5-the-translation-pipeline)
6. [Web Application Pages](#6-web-application-pages)
7. [Reviewer Workflow](#7-reviewer-workflow)
8. [Staff Workflow](#8-staff-workflow)
9. [Local Development Setup](#9-local-development-setup)
10. [Environment Variables](#10-environment-variables)
11. [Management Commands Reference](#11-management-commands-reference)
12. [Deployment — Heroku](#12-deployment--heroku)
13. [Development History](#13-development-history)
14. [What Comes Next](#14-what-comes-next)

---

## 1. Project Background

**Voyant Tools** is a widely-used web-based platform for text analysis in the digital humanities.
It already ships with interface translations for French, German, Spanish, Arabic, Japanese, and
several other languages — but no African language has ever been supported.

This project addresses that gap with three goals:

1. **Produce a validated Yoruba translation** of the Voyant UI string bundle that can be
   submitted upstream.
2. **Build a replicable methodology** — every step is open Python, documented, and parameterised
   so any scholar can point the same pipeline at Amharic, Swahili, isiZulu, or any other language
   supported by NLLB-200.
3. **Demonstrate the pipeline publicly** through this Django application, which manages the full
   lifecycle: import → AI draft → human review → export.

### Why not just use a translation service?

African languages suffer from chronic under-representation in commercial MT systems. Generic
translation APIs hallucinate or silently omit UI-critical tokens (placeholders, HTML tags,
ICU syntax). Our pipeline:

- Protects every placeholder before translation and verifies restoration after
- Back-translates the draft to English and scores semantic similarity with XLM-R
- Surfaces low-quality drafts automatically so reviewers focus attention on strings that need it most
- Keeps a complete provenance trail (engine, score, QA flags, reviewer) on every string

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        Django 5.2 App                           │
│  voyant_l10n_hub/  (project settings, wsgi, urls)               │
│  l10n/             (the single application)                     │
│                                                                 │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────────────┐  │
│  │  Public     │  │  Reviewer    │  │  Staff                │  │
│  │  Pages      │  │  Workflow    │  │  Workflow             │  │
│  │  /          │  │  /apply/     │  │  /dashboard/          │  │
│  │  /about/    │  │  /review/    │  │  /pipeline/           │  │
│  │  /workflow/ │  │  /review/<n>/│  │  /import/             │  │
│  │  /progress/ │  │              │  │  /export/<locale>/    │  │
│  │  /team/     │  │              │  │  Django Admin         │  │
│  └─────────────┘  └──────────────┘  └───────────────────────┘  │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  l10n/services/                                          │   │
│  │  placeholder.py  translator.py  scorer.py  qa.py         │   │
│  │  exporter.py     locale_presets.py                       │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  l10n/management/commands/                               │   │
│  │  import_voyant_csv   run_pipeline   seed_locales         │   │
│  │  export_locale_csv   export_all_locales                  │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
              │
              │  ML dependencies (requirements-ml.txt)
              ▼
   ┌─────────────────────────────────────────────┐
   │  NLLB-200           (HuggingFace/local)     │
   │  XLM-R Scorer       (sentence-transformers) │
   │  OpenAI API         (optional)              │
   │  Ollama             (optional, local LLM)   │
   └─────────────────────────────────────────────┘
```

**Key design principle:** The web application and the ML pipeline are deliberately separated.
`requirements.txt` contains only the Django stack — Heroku-deployable, no GPU needed.
`requirements-ml.txt` holds the heavy ML libraries and is only installed where you intend
to run the translation pipeline (your laptop, a university server, or a GPU instance).

---

## 3. Repository Structure

```
spyral_translation/
│
├── voyant_l10n_hub/          Django project package
│   ├── settings.py           All settings including pipeline env vars
│   ├── urls.py               Root URL conf
│   ├── wsgi.py
│   └── asgi.py
│
├── l10n/                     Main Django application
│   │
│   ├── models.py             Locale, StringUnit, Translation,
│   │                         LocaleAssignment, TranslatorApplication
│   ├── views.py              All HTTP views
│   ├── urls.py               App URL patterns
│   ├── forms.py              ImportVoyantCSVForm, TranslationReviewForm,
│   │                         TranslatorApplicationForm
│   ├── admin.py              Django Admin configuration
│   │
│   ├── services/
│   │   ├── placeholder.py    Sentinel-based placeholder protection
│   │   ├── translator.py     NLLBEngine, OpenAIEngine, OllamaEngine
│   │   ├── scorer.py         XLM-R cosine similarity scorer
│   │   ├── qa.py             Structural QA checks (placeholders, HTML)
│   │   ├── exporter.py       CSV export helper
│   │   └── locale_presets.py Seed data for African + other locales
│   │
│   ├── management/commands/
│   │   ├── run_pipeline.py        Main AI pipeline orchestrator
│   │   ├── import_voyant_csv.py   Ingest existing Voyant CSV
│   │   ├── export_locale_csv.py   Export one locale to CSV
│   │   ├── export_all_locales.py  Export all enabled locales
│   │   └── seed_locales.py        Populate Locale table from presets
│   │
│   ├── migrations/
│   │   ├── 0001_initial.py              Locale, StringUnit, Translation
│   │   ├── 0002_localeassignment.py     LocaleAssignment, TranslatorApplication
│   │   ├── 0003_translation_qa_flags.py qa_flags JSONField
│   │   └── 0004_translation_pipeline_fields.py
│   │                                    back_translation, similarity_score, engine
│   │
│   ├── templates/l10n/
│   │   ├── base.html                Shared layout, nav, footer
│   │   ├── home.html                Landing page with hero
│   │   ├── about.html               Full project narrative
│   │   ├── workflow.html            7-step pipeline visual
│   │   ├── progress.html            Live per-language progress bars
│   │   ├── team.html                Approved reviewer cards
│   │   ├── call_translators.html    Recruitment page
│   │   ├── apply.html               Translator application form
│   │   ├── application_status.html  Applicant status page
│   │   ├── auth_login.html          Login page
│   │   ├── review_list.html         Review queue
│   │   ├── review_detail.html       Per-string review UI
│   │   ├── dashboard.html           Staff multi-locale dashboard
│   │   ├── pipeline_trigger.html    Web UI to trigger run_pipeline
│   │   └── import_voyant_csv.html   CSV upload form
│   │
│   └── static/l10n/
│       ├── site.css   African-inspired design system
│       └── site.js    Scroll reveal, stat counters, progress bars,
│                      hero word rotation, ripple, card tilt, toast
│
├── data/
│   └── .keep              Drop voyant_strings.csv here before importing
│
├── requirements.txt        Web app deps (Django, gunicorn, whitenoise…)
├── requirements-ml.txt     ML deps (torch, transformers, sentence-transformers…)
├── requirements-dev.txt    Dev deps (pytest, ruff, pre-commit…)
├── Procfile                Heroku: release phase runs migrate, web runs gunicorn
├── .env.example            Template for all environment variables
└── manage.py
```

---

## 4. Data Model

### `Locale`
Represents a target language. Seeded from `locale_presets.py`.

| Field | Notes |
|---|---|
| `code` | BCP-47-ish slug, e.g. `yo`, `sw`, `zh-hans`. Used as the primary identifier throughout. |
| `bcp47` | Formal BCP-47 tag |
| `name` | Display name, e.g. "Yoruba" |
| `script` | ISO 15924 script code, e.g. `Latn`, `Ethi` |
| `is_rtl` | Right-to-left flag |
| `enabled` | Controls visibility in progress tracker and pipeline |
| `legacy_column` | Column header as it appears in the Voyant CSV (e.g. `yo`) |

### `StringUnit`
One translatable string from the Voyant UI bundle.

| Field | Notes |
|---|---|
| `location` | File/context path from the Voyant CSV |
| `message_id` | String key within that file |
| `source_text` | English source text |
| `source_hash` | SHA-256 of the normalised source text. Auto-computed on save. When it changes, all `approved_text` translations for that string are automatically set to `STALE`. |

### `Translation`
One translated rendering of a `StringUnit` into a `Locale`. The combination `(string_unit, locale)` is unique.

| Field | Notes |
|---|---|
| `machine_draft` | Output of the AI translation engine |
| `reviewer_text` | Reviewer's edited version (may differ from draft) |
| `approved_text` | Final approved text. Only this field is exported. |
| `back_translation` | Machine draft translated back to English (for scoring) |
| `similarity_score` | XLM-R cosine similarity between source and back-translation (0–1). Populated by `run_pipeline`. |
| `engine` | Engine that produced `machine_draft`, e.g. `facebook/nllb-200-distilled-600M` |
| `qa_flags` | JSON list of flag objects `{code, message, details}`. Auto-updated on every save. |
| `status` | `MACHINE_DRAFT → IN_REVIEW → APPROVED` (or `FLAGGED`, `STALE`, `REJECTED`) |
| `provenance` | `MT` (NLLB), `LLM` (OpenAI/Ollama), `HUMAN`, `IMPORTED` |

### `TranslatorApplication`
Volunteer reviewer application. Staff approve/reject via Django Admin.
Once approved, the reviewer can access the review queue for their requested locale.

### `LocaleAssignment`
Maps a Django user to one or more locales, controlling which review queue entries they see in Admin.

---

## 5. The Translation Pipeline

### How a string goes from English to Approved Yoruba

```
Voyant CSV
    │
    ▼
import_voyant_csv        Upserts StringUnit rows (English source).
    │                    For languages already in the CSV, creates Translation
    │                    rows marked APPROVED / IMPORTED.
    │
    ▼
run_pipeline             For each StringUnit with no approved Translation
    │                    in the target locale:
    │
    ├─1─ protect()       Replaces {0}, %(name)s, <b>, &amp; etc. with §0§, §1§…
    │
    ├─2─ engine.translate(eng → yor)    NLLB-200 / OpenAI / Ollama
    │
    ├─3─ restore()       §0§, §1§… swapped back to original tokens
    │
    ├─4─ back_engine.translate(yor → eng)    Always NLLB-200
    │
    ├─5─ scorer.score(source, back_translation)    XLM-R cosine similarity
    │
    ├─6─ compute_qa_flags()    Placeholder integrity, HTML tags,
    │                          low_similarity flag if score < 0.75
    │
    └─7─ Translation.save()
              status = MACHINE_DRAFT  (or FLAGGED if QA issues)
              provenance = MT / LLM
    │
    ▼
review_queue             Approved reviewers see MACHINE_DRAFT strings.
    │                    review_detail shows: source, AI draft, engine,
    │                    back-translation, similarity score, QA flags.
    │
    ▼
reviewer action
    ├── Accept draft → copy to reviewer_text, set APPROVED
    ├── Edit draft   → fix in reviewer_text, set APPROVED
    ├── Reject       → set REJECTED
    └── Flag         → set FLAGGED (escalate to team)
    │
    ▼
export_locale_csv        Downloads CSV of all APPROVED strings for the locale.
    │                    Only approved_text is included.
    │
    ▼
Voyant upstream          Submit CSV to Voyant Tools project for inclusion.
```

### Placeholder protection in depth

Voyant strings contain ICU message syntax, HTML, and printf-style tokens that must
survive translation byte-for-byte. Example:

```
Source:  "Displaying {0} of {1} documents"
Problem: NLLB might translate {0} or drop it entirely
Fix:     protect()  →  "Displaying §0§ of §1§ documents"
         translate  →  "Fíhàn §0§ nínú §1§ àwọn ìwé"
         restore()  →  "Fíhàn {0} nínú {1} àwọn ìwé"
```

If a sentinel is missing from the translation, `compute_qa_flags()` catches it with a
`missing_placeholder` flag, and the string is saved as `FLAGGED` rather than `MACHINE_DRAFT`.

### NLLB-200 language codes

NLLB-200 uses its own floret codes rather than BCP-47. The mapping lives in
`l10n/services/translator.py` (`NLLB_LANG` dict). Current African language coverage:

| Locale code | NLLB floret code | Language |
|---|---|---|
| `yo` | `yor_Latn` | Yoruba |
| `ha` | `hau_Latn` | Hausa |
| `ig` | `ibo_Latn` | Igbo |
| `sw` | `swh_Latn` | Swahili |
| `am` | `amh_Ethi` | Amharic |
| `zu` | `zul_Latn` | isiZulu |
| `xh` | `xho_Latn` | isiXhosa |
| `so` | `som_Latn` | Somali |
| `rw` | `kin_Latn` | Kinyarwanda |
| `sn` | `sna_Latn` | Shona |
| `ti` | `tir_Ethi` | Tigrinya |

To add a new language: add an entry to `NLLB_LANG`, add a `LocaleSeed` to `locale_presets.py`,
run `seed_locales`, then run `run_pipeline --locale <code>`.

---

## 6. Web Application Pages

| URL | Access | Purpose |
|---|---|---|
| `/` | Public | Landing page with rotating hero word cycling through African language names |
| `/about/` | Public | Full project narrative: problem, approach, models, why it matters |
| `/workflow/` | Public | 7-step pipeline visual with sticky model reference card |
| `/progress/` | Public | Live per-language animated progress bars |
| `/team/` | Public | Approved reviewer cards with photos and affiliations |
| `/call-for-translators/` | Public | Recruitment page for volunteer reviewers |
| `/apply/` | Public | Translator application form (creates account + application) |
| `/application/` | Auth | Applicant status page |
| `/review/` | Auth (approved) | Review queue — lists MACHINE_DRAFT and FLAGGED strings |
| `/review/<id>/` | Auth (approved) | Per-string review detail: source, AI draft, back-translation, similarity score, QA flags, review form |
| `/dashboard/` | Staff | Multi-locale stats grid, pipeline CTA, quick export links |
| `/pipeline/` | Staff | Web UI to trigger `run_pipeline` for any locale |
| `/import/` | Staff | Upload a Voyant CSV to ingest strings |
| `/export/<locale>/` | Staff | Download approved translations as CSV |
| `/admin/` | Staff | Full Django Admin for data management |

---

## 7. Reviewer Workflow

1. Visit `/apply/` — fill in name, affiliation, language background, desired locale.
   An account is created if you do not already have one.

2. Staff approves the application via Django Admin (TranslatorApplication → set status APPROVED).

3. Log in at `/login/`. The nav now shows "My Application" and "Review Queue".

4. Open `/review/` — see all strings awaiting human validation for your locale.
   Strings are sorted with `FLAGGED` (QA issues) first, then `MACHINE_DRAFT`.

5. Click a string to open `/review/<id>/`. The page shows:
   - **Source** (English) — copy button
   - **AI draft** — the machine translation, with engine name shown
   - **Back-translation** — the draft translated back to English
   - **Similarity score** — colour-coded: green ≥ 0.75, amber 0.5–0.75, red < 0.5
   - **QA flags** — structural issues found automatically
   - **Review guide** — what Accept / Edit / Reject / Flag means

6. Choose an action:
   - **Accept** — paste the AI draft (or your edited version) into the reviewer text box,
     set status to *Approved*, save (`Ctrl+Enter`).
   - **Edit** — fix the draft in the reviewer text box, then approve.
   - **Reject** — leave reviewer text empty, set status to *Rejected*.
   - **Flag** — set *Flagged* to escalate to the team.

7. Only strings with `approved_text` set count toward the progress percentage and are
   included in CSV exports.

---

## 8. Staff Workflow

### Daily operation

```
# Check pipeline status on the dashboard
http://localhost:8000/dashboard/

# Run the pipeline for a new batch of strings
http://localhost:8000/pipeline/
# — or via CLI for larger batches:
python manage.py run_pipeline --locale yo --engine nllb --limit 100 --verbose

# Export approved strings for delivery
http://localhost:8000/export/yo/
```

### After a Voyant upstream update

```bash
# 1. Download the new Voyant CSV from the Voyant project
# 2. Import it — existing approved translations are NOT overwritten.
#    If a source string changed, its translations are set to STALE automatically.
python manage.py import_voyant_csv --path data/voyant_strings.csv

# 3. Re-run the pipeline for any newly added strings
python manage.py run_pipeline --locale yo --engine nllb

# 4. Review STALE strings (source changed since last approval)
# Admin → Translations → filter by status=STALE
```

### Approving a reviewer application

Admin → Translator Applications → select application → set Status to Approved → Save.
The reviewer can now access `/review/` for their requested locale.

---

## 9. Local Development Setup

### Prerequisites

- Python 3.12+
- PostgreSQL (or use SQLite for quick local dev — the app defaults to SQLite if `DATABASE_URL` is not set)
- `git`

### Steps

```bash
# 1. Clone
git clone <repo-url>
cd spyral_translation

# 2. Create virtualenv
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 3. Install web app dependencies
pip install -r requirements.txt -r requirements-dev.txt

# 4. Install ML pipeline dependencies (only on machines that will run translations)
pip install -r requirements-ml.txt

# 5. Configure environment
cp .env.example .env
# Edit .env — at minimum set DJANGO_SECRET_KEY and DATABASE_URL

# 6. Run migrations
python manage.py migrate

# 7. Seed locale table
python manage.py seed_locales

# 8. Create a superuser
python manage.py createsuperuser

# 9. Import the Voyant string bundle
#    (place the CSV in data/ first)
python manage.py import_voyant_csv --path data/voyant_strings.csv

# 10. Run your first pipeline batch (downloads NLLB-200 ~1.2 GB on first run)
python manage.py run_pipeline --locale yo --engine nllb --limit 30 --verbose

# 11. Start the server
python manage.py runserver

# 12. Open http://localhost:8000
```

### Running tests

```bash
pytest                          # all tests
pytest l10n/tests/ -v           # verbose
pytest -x                       # stop on first failure
```

### Linting and formatting

```bash
pre-commit run --all-files      # ruff + other hooks
```

---

## 10. Environment Variables

Copy `.env.example` to `.env` and fill in values. All variables have sane defaults for
local development; only `DJANGO_SECRET_KEY` and `DATABASE_URL` are required.

### Core Django

| Variable | Default | Description |
|---|---|---|
| `DJANGO_SECRET_KEY` | `changeme-in-local-dev-only` | **Required in production.** Generate with `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"` |
| `DJANGO_DEBUG` | `0` | Set to `1` for local dev. Never `1` in production. |
| `DATABASE_URL` | `sqlite:///db.sqlite3` | Full database URL. Heroku sets this automatically when Postgres is provisioned. |
| `DJANGO_ALLOWED_HOSTS` | `127.0.0.1,localhost` | Comma-separated list of allowed host headers. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | _(empty)_ | Required for Heroku HTTPS form submissions, e.g. `https://yourapp.herokuapp.com` |

### Translation Pipeline

| Variable | Default | Description |
|---|---|---|
| `TRANSLATION_ENGINE` | `nllb` | Default engine: `nllb`, `openai`, or `ollama` |
| `NLLB_MODEL_NAME` | `facebook/nllb-200-distilled-600M` | HuggingFace model ID. Use `nllb-200-1.3B` for higher quality (needs more RAM). |
| `OPENAI_API_KEY` | _(empty)_ | Required only when using the OpenAI engine. |
| `OPENAI_MODEL` | `gpt-4o-mini` | OpenAI model name. |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL (local). |
| `OLLAMA_MODEL` | `llama3` | Ollama model name. |
| `SIMILARITY_MODEL` | `paraphrase-multilingual-mpnet-base-v2` | Sentence-transformers model for XLM-R scoring. |
| `SIMILARITY_THRESHOLD` | `0.75` | Scores below this add a `low_similarity` QA flag. |
| `PIPELINE_WEB_LIMIT` | `30` | Max strings per web-triggered pipeline run (safety cap). Use CLI for larger batches. |
| `HF_TOKEN` | _(empty)_ | HuggingFace token — recommended for higher download rate limits and gated models. |

---

## 11. Management Commands Reference

### `import_voyant_csv`

Ingests the Voyant Tools CSV export. For languages already in the CSV, their translations
are created as `APPROVED / IMPORTED`. For languages not in the CSV (e.g. Yoruba, which has
no prior translation), only `StringUnit` rows are created — these become the input for the pipeline.

```bash
python manage.py import_voyant_csv --path data/voyant_strings.csv
python manage.py import_voyant_csv --path data/voyant_strings.csv --dry-run
python manage.py import_voyant_csv --path data/voyant_strings.csv --limit 50 --verbose
```

### `seed_locales`

Populates the `Locale` table from the preset list in `locale_presets.py`. Idempotent — safe
to re-run; existing locales are not overwritten.

```bash
python manage.py seed_locales
python manage.py seed_locales --preset global_plus_africa_india_chinese
```

### `run_pipeline`

The core AI pipeline. For each untranslated string in the target locale:
protect → translate → back-translate → score → QA → save as MACHINE_DRAFT.

```bash
# Basic run — all untranslated Yoruba strings, NLLB-200
python manage.py run_pipeline --locale yo --engine nllb

# Limit to 50 strings, print per-string progress
python manage.py run_pipeline --locale yo --engine nllb --limit 50 --verbose

# Dry-run — prints what would happen, no DB writes
python manage.py run_pipeline --locale yo --engine nllb --limit 20 --dry-run

# Re-translate strings that already have a draft (overwrite)
python manage.py run_pipeline --locale yo --engine nllb --force

# Use OpenAI instead (requires OPENAI_API_KEY in .env)
python manage.py run_pipeline --locale yo --engine openai --limit 50

# Skip back-translation and scoring (faster, no sentence-transformers needed)
python manage.py run_pipeline --locale ha --engine nllb --no-score

# Another locale — Swahili
python manage.py run_pipeline --locale sw --engine nllb --limit 100
```

### `export_locale_csv`

Exports all approved translations for a locale to a CSV file in `exports/`.

```bash
python manage.py export_locale_csv --locale yo
python manage.py export_locale_csv --locale yo --out-dir /tmp/voyant-exports
python manage.py export_locale_csv --locale yo --only-missing   # strings with no approved text
```

### `export_all_locales`

Runs `export_locale_csv` for every enabled locale in one go.

```bash
python manage.py export_all_locales
```

---

## 12. Deployment — Heroku

The `Procfile` defines two process types:

```
release: python manage.py migrate
web:     gunicorn voyant_l10n_hub.wsgi:application --bind 0.0.0.0:$PORT --log-file -
```

Migrations run automatically on every deploy via the `release` phase.

### Required config vars

Set these in Heroku → Settings → Config Vars:

```
DJANGO_SECRET_KEY          <strong random value>
DJANGO_DEBUG               0
DATABASE_URL               <set automatically by Heroku Postgres add-on>
DJANGO_ALLOWED_HOSTS       youapp.herokuapp.com
DJANGO_CSRF_TRUSTED_ORIGINS  https://yourapp.herokuapp.com
```

### First-time setup after deploying

```bash
# Run migrations (also happens via Procfile release phase)
heroku run python manage.py migrate -a <app>

# Seed locales
heroku run python manage.py seed_locales -a <app>

# Create superuser interactively (avoids password in shell history)
heroku run python manage.py shell -a <app>
```

```python
from django.contrib.auth import get_user_model
User = get_user_model()
u, _ = User.objects.get_or_create(username="yourname", defaults={"email": "you@example.com"})
u.is_staff = True
u.is_superuser = True
u.save()
```

```bash
heroku run python manage.py changepassword yourname -a <app>
```

> **Note on the ML pipeline and Heroku:** The NLLB-200 model (~1.2 GB) cannot be run on
> a standard Heroku dyno due to memory limits and ephemeral storage. Run the pipeline
> locally or on a separate GPU server, then let the web app (Heroku) handle only the
> review and export workflow.

---

## 13. Development History

This section records the major development phases so new team members can understand
how the codebase evolved and why decisions were made.

### Phase 1 — Django scaffold and data model

**What was built:**
The initial Django project (`voyant_l10n_hub`) and `l10n` application were created with the
core data model: `Locale`, `StringUnit`, `Translation`. The `Translation` model was designed
with three text layers from the start — `machine_draft` (AI output), `reviewer_text` (human
edit), `approved_text` (final) — along with a `status` state machine and `provenance` tracking.

Key infrastructure:
- `import_voyant_csv` management command — reads the Voyant CSV export, upserts `StringUnit`
  rows and, for languages that already have translations in the CSV (French, German, etc.),
  creates `Translation` rows marked `APPROVED / IMPORTED`.
- `source_hash` auto-computed on every `StringUnit.save()`. When the English source changes,
  all existing approved translations for that string are automatically set to `STALE`.
- `compute_qa_flags()` in `services/qa.py` — structural checks for placeholder integrity and
  HTML tag balance, run on every `Translation.save()`.
- `LocaleAssignment` model — maps reviewers to locales, controlling Admin access.
- `TranslatorApplication` model — volunteer onboarding with photo upload, language background.
- Locale presets for 11 African languages plus Indian and Chinese variants.
- Export service and management commands (`export_locale_csv`, `export_all_locales`).
- Django Admin hardened for multi-tenant reviewer access: reviewers only see translations
  for their assigned locale; superusers see everything.
- Tests for import, export, QA, seed_locales, and permission boundaries.

**Migrations at this stage:** 0001 → 0003

---

### Phase 2 — Design system and frontend

**What was built:**
The site was completely restyled with a bespoke design system rooted in an African warmth palette:

- **Colour tokens** — sunset orange `#E8630A`, amber gold `#F59E0B`, dark header `#16100A`
- **Typography** — Outfit (Google Fonts) loaded via CSS `@import`
- **Component library in `site.css`** — cards with shadow/hover lift, hero banner with
  radial gradient and noise texture overlay, gradient primary buttons, semantic badge colours
  driven by `data-status` CSS attribute selectors, stat cards, section labels, pipeline step
  connectors, locale progress bars, model card tags
- **Interactions in `site.js`** — all gated behind `prefers-reduced-motion`:
  - `IntersectionObserver` scroll-reveal with staggered delays on grid children
  - Animated stat counters (ease-out cubic count-up)
  - Animated progress bar fill (`data-width` attribute, triggered on scroll)
  - Hero rotating word cycling through 10 African language names (Yoruba, Hausa, Swahili…)
    with no layout shift (`min-width` reservation)
  - Button ripple effect (dynamically injected `.btn-ripple` spans)
  - 3D card tilt on `mousemove` (±5° perspective transform)
  - Sticky header with `backdrop-filter: blur(16px)` on scroll
  - Slide-up toast notification system
- **Placeholder protection for inline styles** — all inline `style=""` attributes were
  replaced with semantic CSS classes to eliminate VSCode embedded CSS linter false positives.

All templates were updated or rewritten: `base.html` got the dark sticky header and structured
footer; `home.html` got the hero with rotating language word; `about.html` became a full project
narrative with model cards (NLLB-200, OpenAI/Ollama, XLM-R, AfroLingu-MT); `review_detail.html`
got keyboard shortcuts, QA badge display, and `data-status` semantic colouring; `dashboard.html`
got the stat-card grid; `team.html` got member photo cards.

---

### Phase 3 — New pages and multi-locale backend

**What was built:**
- `workflow.html` — a 7-step visual pipeline walkthrough with a sticky model reference sidebar
- `progress.html` — public per-language progress tracker with animated progress bars
- `pipeline_trigger.html` — staff web UI to trigger the AI pipeline from the browser
- `dashboard.html` rewritten for multi-locale context — replaced hardcoded Yoruba stats with
  a per-locale grid fed by `locale_stats` context from the updated `dashboard` view
- `application_status.html` polished — status icon hero, semantic badge, `btn-primary` CTA

Backend:
- `workflow` and `progress` views added
- `dashboard` view generalised from Yoruba-only to multi-locale
- `_build_locale_csv()` DRY helper shared by `export_yo_csv` and new `export_locale_csv` view
- `/workflow/`, `/progress/`, `/export/<locale_code>/`, `/pipeline/` URLs added
- Base nav updated: Pipeline and Progress links added

---

### Phase 4 — Full AI translation pipeline

**What was built:**
This was the most significant backend development phase. The core gap before this phase:
for African languages with no prior Voyant translation, `Translation` rows with `machine_draft`
simply did not exist — reviewers had nothing to work on.

**New model fields on `Translation`** (migration 0004):
- `back_translation` — draft translated back to English
- `similarity_score` — XLM-R cosine similarity (0–1)
- `engine` — name of the engine that produced the draft

**New services:**
- `services/placeholder.py` — `protect(text)` / `restore(text, map)`. Replaces ICU tokens,
  HTML tags, percent-format strings with numbered `§N§` sentinels before translation and
  restores them after. Missing sentinels surface as `missing_placeholder` QA flags.
- `services/translator.py` — Protocol-based engine adapter system:
  - `NLLBEngine` — NLLB-200 via HuggingFace Transformers (local, CPU or GPU, no API key)
  - `OpenAIEngine` — Chat Completions with a UI-translation prompt
  - `OllamaEngine` — local Ollama REST API
  - `get_engine(name)` factory reads from Django settings
  - `NLLB_LANG` dict maps all locale codes to NLLB-200 floret codes
  - All engines lazy-load; missing dependencies raise `PipelineConfigError` with install instructions
- `services/scorer.py` — `SimilarityScorer` class wrapping `sentence-transformers`. Lazy
  module-level singleton. Returns cosine similarity in [0, 1].

**New management command: `run_pipeline`:**
Full per-string orchestration: protect → translate → restore → back-translate → score →
QA check → save. Supports `--engine`, `--limit`, `--force`, `--no-score`, `--dry-run`, `--verbose`.
Strings with QA issues are saved as `FLAGGED`; clean drafts as `MACHINE_DRAFT`.

**New staff view: `trigger_pipeline`** (`/pipeline/`):
Web form that calls `run_pipeline` via `call_command()` with captured stdout, renders results
inline. Locale selector, engine selector, limit field, force/no-score checkboxes.
Intended for small batches (≤ 30 strings); larger batches should use the CLI directly.

**Updated `review_detail.html`:**
Now surfaces all pipeline provenance data for reviewers: engine name, back-translation text,
similarity score (colour-coded green/amber/red), QA flags rendered as styled alert boxes
(warning for `low_similarity`, error for structural issues), and a concise review guide.

**Updated Django Admin:**
`engine`, `similarity_score`, `back_translation` added to fieldsets, list display, and
list filters on `TranslationAdmin`.

**New pipeline settings** in `settings.py`:
`TRANSLATION_ENGINE`, `NLLB_MODEL_NAME`, `OPENAI_API_KEY`, `OPENAI_MODEL`,
`OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `SIMILARITY_MODEL`, `SIMILARITY_THRESHOLD`,
`PIPELINE_WEB_LIMIT` — all controllable via environment variables.

---

## 14. What Comes Next

The following items represent the natural next development steps. They are not yet built.

### High priority

- **AfroLingu-MT benchmark integration** — `evaluate_afrolingu_mt` management command
  (referenced in original README) to measure NLLB-200 quality on African language pairs
  beyond the Voyant string set. Uses UBC-NLP's gated HuggingFace dataset.

- **Async pipeline execution** — The current web trigger runs synchronously, which works
  for small batches but will time out on Heroku for larger runs. The clean solution is
  Django-Q or Celery with a Redis broker so the pipeline runs in a background worker and
  the web UI polls for completion.

- **Reviewer locale enforcement** — Currently the review queue shows all MACHINE_DRAFT
  strings regardless of the logged-in reviewer's assigned locale. The view should filter
  by `LocaleAssignment` so reviewers only see strings for their language.

- **Bulk approve / reject** — Admin action exists, but the web review queue should support
  selecting multiple strings and bulk-approving them (especially useful for short UI labels
  where the AI draft is obviously correct).

### Medium priority

- **Domain glossary enforcement** — A `GlossaryTerm` model per locale (e.g. "Corpus" →
  "Àkójọpọ̀ ọ̀rọ̀" in Yoruba) with a QA check that flags strings where the source contains
  a known term but the translation does not use the agreed equivalent.

- **Multi-engine comparison view** — Run NLLB and OpenAI on the same string, store both
  drafts, let the reviewer pick the better one. The `engine` field already accommodates this;
  the UI and model need a minor extension.

- **Email notifications** — Notify reviewers when new MACHINE_DRAFT strings are available
  for their locale; notify staff when a reviewer submits their first approval.

- **Public API** — A simple read-only JSON endpoint returning approved translations per
  locale, so external tools can consume the data without downloading a CSV.

### Future / research scope

- **Extend to Hausa, Igbo, Swahili** — The pipeline already supports these (NLLB_LANG is
  populated); it's a matter of running `run_pipeline --locale ha` etc. and recruiting
  native-speaker reviewers.

- **Deeper NLP analysis support** — The current work localises the *interface* of Voyant.
  A longer-term goal is enabling Voyant's *analysis* capabilities (tokenisation, stop-word
  lists, frequency counts) for African language text corpora.

- **BLEU/chrF evaluation against AfroLingu-MT** — Systematic quality measurement beyond
  the XLM-R similarity score, enabling comparison between NLLB-200, OpenAI, and Ollama
  on the same string set.

---

*This README reflects the state of the codebase as of the end of Phase 4 development.
Update the [Development History](#13-development-history) section when new phases are completed.*
