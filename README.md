# School Shuttle Bus Tracking System

A complete, production-ready real-time school shuttle bus tracking web application built with Django and Django Channels.

## Features

- **Real-time Tracking**: Live map tracking using WebSocket technology (Django Channels) and Leaflet.js.
- **Driver Dashboard**: Allows drivers to broadcast their GPS location directly from their mobile browser using the Geolocation API. No dedicated app required.
- **Admin Dashboard**: Comprehensive management interface for Buses, Routes, Stops, Users, and School Settings.
- **Dynamic Branding**: The entire UI updates automatically when the admin changes colors or uploads a new logo in the settings page. Colors are automatically extracted from the logo.
- **Role-based Access Control**: 
  - Admin: Full system access.
  - Driver: Access to their specific dashboard to broadcast location.
  - Student/Public: View-only access to track buses.
- **Responsive Design**: Beautiful, modern, Glassmorphism-inspired UI that works perfectly on desktops, tablets, and phones.

## Tech Stack

- **Backend**: Python 3, Django 4.2+, Django REST Framework, Django Channels (WebSockets)
- **Frontend**: HTML5, Vanilla CSS3 (with CSS variables), Vanilla JavaScript, Leaflet.js (for Maps)
- **Database**: SQLite (default for development), PostgreSQL (recommended for production)

## Setup Instructions

1. **Clone the repository** (or download the source):
   ```bash
   git clone <repo-url>
   cd shuttle-track
   ```

2. **Set up a virtual environment**:
   ```bash
   python -m venv venv
   # Windows:
   .\venv\Scripts\activate
   # Mac/Linux:
   source venv/bin/activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Apply database migrations**:
   ```bash
   python manage.py migrate
   ```
   Use `makemigrations` only when you have changed a model.

5. **Create a superuser (Admin)**:
   ```bash
   python manage.py createsuperuser
   ```

6. **Run the development server**:
   ```bash
   python manage.py runserver
   ```
   The local server uses the in-memory channel layer. To exercise production-style
   cross-process WebSocket broadcasts locally, set `REDIS_URL` to a reachable Redis
   service first.

7. **Access the Application**:
   - Website: `http://127.0.0.1:8000/`
   - Login: `http://127.0.0.1:8000/accounts/login/`

## Local environment

Copy `.env.example` to `.env`, generate a local key, and leave `DATABASE_URL` and
`REDIS_URL` unset to use the existing SQLite database and in-memory channel layer:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Paste the generated value into `.env`. `.env` is ignored by Git; do not commit it.
`SECRET_KEY`, `DATABASE_URL`, and `REDIS_URL` are read from the environment (or
local `.env`). When `DEBUG=False`, startup fails unless a secret key, PostgreSQL
`DATABASE_URL`, Redis `REDIS_URL`, Cloudinary credentials, and a production
host/origin are configured. To use Cloudinary locally, set all three
`CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, and `CLOUDINARY_API_SECRET`
values in `.env`; with none set, development continues to use local `MEDIA_ROOT`.

## Render deployment

The included `render.yaml` defines a free-tier Python web service, PostgreSQL
database, and Redis-compatible Key Value service in the Oregon region. Deploy it
from Render using **New > Blueprint Instance** and select the GitHub repository.
Render will prompt before creating the three free services; review the plan for
each resource and do not select a paid plan. The blueprint wires the database
and Redis connection URLs to the web service and generates a new `SECRET_KEY`.
Its build command is:

```bash
pip install -r requirements.txt && python manage.py collectstatic --noinput
```

Its start command applies migrations before serving HTTP and WebSockets through
Daphne:

```bash
python manage.py migrate --noinput && daphne -b 0.0.0.0 -p $PORT config.asgi:application
```

The blueprint sets `DEBUG=False`, generates `SECRET_KEY`, and supplies internal
`DATABASE_URL` and `REDIS_URL` references. Render supplies `PORT` and
`RENDER_EXTERNAL_HOSTNAME`. For a custom domain, configure:

| Variable | Value |
| --- | --- |
| `ALLOWED_HOSTS` | Optional comma-separated custom hostnames; Render's assigned hostname is added automatically |
| `CSRF_TRUSTED_ORIGINS` | Optional comma-separated full `https://` origins for custom domains; Render's hostname is added automatically |

Add your custom domain to both the allowed-host and CSRF origin configuration.
Keep credentials in Render's environment settings rather than in source control.
The blueprint deliberately leaves the Cloudinary environment variables
unsynchronized so credentials are entered through Render's dashboard.

To configure persistent uploads, create a Cloudinary account and copy its cloud
name, API key, and API secret from the Cloudinary console. In Render, open
**Dashboard → campus-shuttle (Web Service) → Environment → Add Environment
Variable** and add:

| Key | Value |
| --- | --- |
| `CLOUDINARY_CLOUD_NAME` | Your Cloudinary cloud name |
| `CLOUDINARY_API_KEY` | Your Cloudinary API key |
| `CLOUDINARY_API_SECRET` | Your Cloudinary API secret |

Save these variables before deploying the code update. The API secret belongs
only in Render's environment settings (or an ignored local `.env`); never put
its value in GitHub, `render.yaml`, or `.env.example`. Production startup fails
if any Cloudinary credential is missing. The Django `ImageField`s for school
logos, favicons, and user profile pictures then save to Cloudinary. Existing
forms, admin previews, and templates continue using Django's normal `.url`
interface. Static assets remain on WhiteNoise and are not sent to Cloudinary.

To verify uploads after deployment, sign in as an administrator, open School
Settings, upload and save a new logo and favicon, then reload the page and check
that both images still display and their image URLs point to Cloudinary. Upload
a profile picture through the user editor in Django admin and check its preview
as well. Redeploy, then reload the page and confirm the same images remain
available. A live test requires valid Cloudinary credentials; it cannot be
completed until these are configured.

Changing the storage backend does not copy files already on a local or Render
filesystem into Cloudinary. Existing database records and local media files are
not deleted or rewritten, but any existing record that points to a local-only
file must have that original file transferred to Cloudinary before it will
display through the new backend. Keep a backup of existing media and complete
that transfer before switching production storage if the current deployment
already has uploads.

`collectstatic` runs during the build and WhiteNoise serves compressed,
manifested static assets (including Django admin assets). Migrations run at
startup; keep a single web instance during deployment/migration, and review
model migrations before deploying schema changes.

The app requires Redis in production: an in-memory layer is process-local and
cannot reliably broadcast updates to users connected to different workers.
Render currently offers a free Key Value plan, but free instances do not persist
data across restarts. This is acceptable for transient Channels group state;
clients must reconnect after service restarts. If the free plan is unavailable
in your workspace, stop and use a reachable Redis-compatible provider rather
than falling back to in-memory channels. The blueprint does not allow external
Redis connections; the web service uses the private internal connection.

**Free Render services are for testing and hobby projects, not production
availability.** Free web services spin down after 15 minutes without traffic
and can take about a minute to wake. Free Postgres is limited to 1 GB, has no
backups, and expires 30 days after creation. After a further 14-day grace period,
Render deletes the database and its data. Arrange a verified database export
and move to a durable database plan before expiration; do not rely on free
Postgres for irreplaceable live campus data. Check the current Render free-plan
terms before creating resources.

Before pushing to GitHub, run locally:

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py test
```

These commands use your local SQLite database. Production checks require the
production environment variables to be present; do not put production secrets
in `.env.example` or commit `.env`.

## Using the System

1. **Setup School Info**: Log in as admin, go to Admin -> School Settings. Upload a logo to automatically generate a brand color palette!
2. **Add Routes**: Go to Admin -> Routes. Create a route, define start/end, and add intermediate stops.
3. **Add Drivers**: Go to Admin -> Users. Create a user and select the "Driver" role.
4. **Add Buses**: Go to Admin -> Buses. Create a bus, assign a route, and assign a driver.
5. **Start Tracking**: 
   - The driver logs in on their phone and clicks "START SHARING LOCATION".
   - Students go to the website, click "Track Bus", and watch the bus move on the live map.

## Architecture Highlights
- **WebSockets**: `tracking/consumers.py` handles bidirectional real-time data using Redis in production (or InMemoryChannelLayer for dev) to broadcast driver coordinates to all connected tracking clients immediately. Student clients retry with exponential backoff; the driver dashboard reconnects with capped exponential backoff and sends its latest buffered GPS fix after reconnection.
- **Singleton Settings**: The `SchoolSettings` model overrides the `save()` method to ensure only one record exists, providing global branding.
- **Inline Formsets**: Route stops are dynamically managed using Django's inline formsets, completely styled with custom CSS for a better UX.
