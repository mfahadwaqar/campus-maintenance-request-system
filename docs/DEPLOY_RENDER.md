# Deploying for free: GitHub, Render and Neon

This puts the application online without paying for anything:

| Part | Service | What it holds |
|---|---|---|
| Code | GitHub | the repository |
| Web application | Render (free web service) | the Django app, built from the `Dockerfile` |
| Database and photos | Neon (free PostgreSQL) | tickets, accounts **and the uploaded photos** |

Render's free plan has no disk that survives a restart, so photos are kept in the database
(`PHOTO_STORAGE=database`). They stay private: they are only served through the permission-checked
download page.

Free plans change. Check the current limits on render.com/pricing and neon.com/pricing before the
presentation. At the time of writing: a free Render service goes to sleep after about 15 minutes with no
visits (the next visit takes up to a minute to wake it), and a free Neon database has a small size cap
and also pauses when idle.

---

## 1. Put the code on GitHub without the database backup

The repository has one file that must not go public: `database-backup-20261108-165959.dump`. These steps
copy the project, remove that file from every commit of the copy, and push the copy. Your GitLab
repository and your working folder are not touched.

```powershell
git clone --branch feature/free-deploy --single-branch "E:\Downloads\AIT\Third Semester\Full Stack Application Development\Project\campus-maintainance-request-system" "E:\Downloads\AIT\Third Semester\Full Stack Application Development\Project\campus-github"
```

```powershell
cd "E:\Downloads\AIT\Third Semester\Full Stack Application Development\Project\campus-github"
```

```powershell
pip install git-filter-repo
```

```powershell
git filter-repo --path database-backup-20261108-165959.dump --invert-paths
```

Check that the file is gone from the history. This must print nothing:

```powershell
git log --all --oneline -- database-backup-20261108-165959.dump
```

Stop dumps from being added again, name the branch `main`, then create the GitHub repository and push
(you are already signed in to GitHub as `mfahadwaqar`):

```powershell
Add-Content .gitignore "`n*.dump"; git add .gitignore; git commit -m "Ignore database dumps"; git branch -M main
```

```powershell
gh repo create campus-maintenance-request-system --private --source . --remote origin --push
```

Open `https://github.com/mfahadwaqar/campus-maintenance-request-system` and check the files are there.
Private is fine: Render can build from a private repository once you allow it.

## 2. Create the free database on Neon

1. Go to neon.com and sign up (the "Continue with GitHub" button is quickest).
2. Create a project: name `campus-maintenance`, pick the region closest to you (Singapore if offered),
   keep the default PostgreSQL version.
3. On the project page click **Connect**. Turn **Connection pooling off** so you get the direct address.
4. Copy the connection string. It looks like
   `postgresql://user:password@ep-something.region.aws.neon.tech/neondb?sslmode=require`.
   Keep it somewhere private; it contains the database password.

## 3. Create the web service on Render

1. Go to render.com and sign up with GitHub. When asked, allow Render to see the
   `campus-maintenance-request-system` repository.
2. Click **New**, then **Web Service**, choose the repository.
3. Fill in:
   - **Name:** `campus-maintenance` (your address becomes `https://campus-maintenance.onrender.com`;
     if the name is taken Render adds letters, and you must use the address it actually shows)
   - **Region:** the same as the database (Singapore)
   - **Branch:** `main`
   - **Language / Runtime:** `Docker`
   - **Instance type:** `Free`
4. Open **Advanced** and set:
   - **Docker Command:** `sh scripts/render_start.sh`
   - **Health Check Path:** `/health/`
5. Add these **Environment Variables** (replace `campus-maintenance` if Render gave you another name):

| Name | Value |
|---|---|
| `DJANGO_SECRET_KEY` | a long random text. Make one with: `python -c "import secrets; print(secrets.token_urlsafe(60))"` |
| `DJANGO_ALLOWED_HOSTS` | `campus-maintenance.onrender.com` (no `https://`) |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://campus-maintenance.onrender.com` |
| `SITE_BASE_URL` | `https://campus-maintenance.onrender.com` |
| `DATABASE_URL` | the Neon connection string from step 2 |
| `PHOTO_STORAGE` | `database` |
| `DJANGO_SUPERUSER_USERNAME` | your admin username |
| `DJANGO_SUPERUSER_EMAIL` | your email |
| `DJANGO_SUPERUSER_PASSWORD` | your admin password |
| `PRESENTATION_USER_PASSWORD` | the password for the presentation accounts |

6. Click **Create Web Service**. The first build takes a few minutes. Open the **Logs** tab and wait for
   the lines `Booting worker` (from the web server) and `Your service is live`.
7. If the address Render shows differs from the one you typed, correct the three variables that
   contain it (`DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, `SITE_BASE_URL`) under
   **Environment**; Render restarts the service by itself.

Each time the service starts, `scripts/render_start.sh` creates the tables, loads the categories, units
and buildings, and creates your admin and the presentation accounts if they do not exist. Running it
again changes nothing that is already there.

## 4. Check that it works

1. Open `https://campus-maintenance.onrender.com/health/` (it should show `{"status": "ok"}`) and then `/login/`.
2. Sign in as `resident.ali` with the presentation password, submit a request **with a photo**.
3. In a private window sign in as `staff.sarah`, review the ticket and assign it to the
   technician of the matching unit, for example `tech.electrical`.
4. In another private window sign in as that technician and open the work order. The resident's photo
   must show.
5. Sign in at `/admin/` with the admin account you set.

The presentation accounts are:

| Role | Username |
|---|---|
| Call Center Staff | `staff.sarah` |
| Residents | `resident.ali`, `resident.mai` |
| Technicians | `tech.plumbing`, `tech.electrical`, `tech.hvac`, `tech.carpentry`, `tech.painting`, `tech.housekeeping`, `tech.pest`, `tech.gardening`, `tech.accommodation` |

## 5. Updating the site later

Push to the `main` branch of the GitHub repository. Render rebuilds and redeploys by itself.

## Before the presentation

- Open the site about five minutes early so the free service is awake and Neon has resumed.
- Do the whole demo once beforehand, including the photo, so the first screens are warm.
- Email is not set up, so notification emails are recorded but not delivered. Nothing breaks.

## If something goes wrong

| What you see | Likely cause and fix |
|---|---|
| `Bad Request (400)` on every page | `DJANGO_ALLOWED_HOSTS` does not match the address exactly |
| `Forbidden (403) CSRF verification failed` when signing in | `DJANGO_CSRF_TRUSTED_ORIGINS` must be `https://` plus the address |
| Page has no styling | the build did not run `collectstatic`; check the Logs for errors and that the Docker Command is `sh scripts/render_start.sh` |
| Logs say `password authentication failed` or `could not translate host name` | `DATABASE_URL` was copied wrongly, or Neon pooling is on; copy the direct string again |
| `Application error` after the free service was idle | wait a minute and reload; it was waking up |
| Photo uploaded but not visible | `PHOTO_STORAGE` is not `database`, so photos were written to the temporary disk |
