# Campus Maintenance Request System: Requirements for Development

Course project (AST02.04 Full Stack Application Development, AIT). Build a reliable MVP of one auditable workflow:
**resident submits request → call-center staff reviews and assigns a unit/technician → technician updates progress → system closes completed work → resident verifies or reopens.**
Priorities set by the supervisor: a working end to end workflow, correct database updates, rejected unauthorized operations, and blocked invalid state transitions. Anything under "Out of MVP" must NOT be built.

## 1. Stack and architecture

* Python, Django (current stable), server rendered multi page application (Django templates, forms, sessions).
* PostgreSQL. Django ORM only, no string built SQL.
* Django REST Framework for core resources, using session authentication with CSRF.
* Project split into apps: `accounts` (custom user, roles, permissions), `reports` (reports, photos, comments, status history, verification, search), `assignments` (technician candidates, assignment, reassignment), `notifications` (email events).
* All status changes go through ONE service function (`reports/services.py`), used by both views and API. No view or serializer may set `status` directly.
* Settings split into base, dev, prod. Secrets from environment variables. Docker (Django with Gunicorn, PostgreSQL, Nginx), GitLab CI running tests on every merge request.

## 2. Roles and permissions

Role is stored on the account (`RESIDENT`, `CALL_CENTER_STAFF`, `TECHNICIAN_CONTRACTOR`). It is never chosen at login. Django admin is separate and used only for account and reference data management.

| Action | Resident | Officer | Technician |
|---|---|---|---|
| Create report | Yes | No | No |
| View report | Own only | All | Only reports with their active assignment |
| See room and contact details | Own | Yes | Only for their assigned reports |
| Review, set priority, reject | No | Yes | No |
| Assign or reassign a unit and optional technician | No | Yes | No |
| Start work, complete with notes and optional photo | No | No | Assigned only |
| Verify (optional rating) or reopen (with reason, within three days) | Own only | May reopen | No |
| Comment | Own report | Any report | Assigned report |
| View status history | Own report | All | Assigned report |

Object level checks apply on every page and API action. Unauthorized object access returns 404 (or 403); unauthenticated access redirects to login or returns 401.

## 3. Workflow state machine

Statuses: `SUBMITTED, UNDER_REVIEW, ASSIGNED, IN_PROGRESS, ON_HOLD, COMPLETED, CLOSED, REOPENED, REJECTED`.

| From | To | Actor | Required |
|---|---|---|---|
| (new) | SUBMITTED | Resident | Valid form |
| SUBMITTED | UNDER_REVIEW | Officer | None |
| SUBMITTED | ASSIGNED | Officer | Unit; optional technician |
| UNDER_REVIEW | ASSIGNED | Officer | Unit and priority; optional technician |
| UNDER_REVIEW | REJECTED | Officer | Reason (mandatory) |
| SUBMITTED | REJECTED | Officer | Reason (mandatory) |
| ASSIGNED or IN_PROGRESS | ASSIGNED | Officer | Unit and optional technician |
| ASSIGNED | IN_PROGRESS | Assigned technician | None |
| ASSIGNED or IN_PROGRESS | ON_HOLD | Assigned technician | Reason and expected date |
| ON_HOLD | IN_PROGRESS | Assigned technician | None |
| IN_PROGRESS | COMPLETED | Assigned technician | Completion notes |
| COMPLETED | CLOSED | System | Automatic after completion |
| CLOSED | REOPENED | Requesting resident or officer | Reason, within three days of completion |
| REOPENED | ASSIGNED | Officer | Same or different technician |

Verification is recorded after closure, accepts an optional 1–5 rating and comment, and does not change report status. Any other transition is rejected with a clear error and nothing is saved. Every successful transition writes a StatusHistory row in the same transaction.

## 4. Data model

* **User** (custom, extends AbstractUser): `role`, `building` (nullable FK), optional `phone`.
* **Building**: `name`, `zone`. **Category**: `name`.
* **Report**: `resident` (PROTECT), `category` (PROTECT), `building` (PROTECT), `room_location`, `title`, `description`, `requested_urgency` (hint from resident), `priority` (set by officer), `status`, `version` (integer), `created_at`, `updated_at`.
* **Assignment**: `report` (FK, **one to many** so history is kept), `unit`, optional `technician`, `assigned_by`, `assigned_at`, `is_active`, `started_at`, `completed_at`, `ended_at`, `end_reason`. Constraint: a partial unique index allowing **only one active assignment per report** (`UniqueConstraint(fields=["report"], condition=Q(is_active=True))`).
* **Verification**: `report`, `resident`, `outcome` (`VERIFIED` or `REOPENED`), `rating` (1 to 5, check constraint, null when reopened), `comment`, `created_at`. Multiple rows allowed across reopen cycles.
* **Comment**: `report`, `author`, `body`, `kind` (`COMMENT` or `FOLLOW_UP`), `created_at`. Comments are visible to report participants and staff with authorized report access.
* **Photo**: `report`, `uploaded_by`, optional `assignment`, `stage` (`REPORT` or `COMPLETION`), private `file_path`, `content_type`, `size_bytes`.
* **StatusHistory**: `report` (PROTECT), `old_status`, `new_status`, `changed_by`, `note`, `changed_at`. **Append only: never updated, never deleted, never cascaded.**
* **Notification**: `user`, `report`, `message`, `channel`, `status`, `created_at`, `read_at`.
* Database constraints: CHECK on allowed status and rating values, foreign keys everywhere, indexes on `status`, `resident`, `created_at`, and on active assignments by technician.

## 5. Verification and reopening

* Completion records `COMPLETED` and then system `CLOSED` in one transaction. The completion assignment is marked inactive.
* The resident may verify closed work with an optional rating and comment; verification does not change the ticket status.
* The resident or call-center staff may reopen a closed ticket within three days of completion, with a reason. The ticket enters `REOPENED`, notifies call-center staff, and must be reassigned to return to work.
* Reopened tickets retain prior assignment and verification history; follow-up requests are not merged into other tickets.

## 6. Concurrency and integrity (explicitly required)

* Assignment runs in `transaction.atomic()`, locks the report with `select_for_update()`, rechecks that the status still permits assignment (and that the submitted `version` or expected status matches), deactivates the previous active assignment if reassigning, creates the new Assignment, updates status, writes StatusHistory, and increments `version`.
* The second of two simultaneous officers receives a conflict message (HTTP 409 on the API) and nothing is saved.
* The partial unique index is the database level safety net. Catch `IntegrityError` and return the same conflict response.
* Do not hold a lock while an officer deliberates between requests. Lock only at confirmation.
* Apply the same locking pattern to every status transition.

## 7. Functional requirements by role

**Resident:** submit report (category, building, room, title, description, urgency hint, optional photo); list own reports with status; view detail, history and comments; comment; verify with optional rating or reopen with reason within three days; receive updates.

**Call-center staff:** queue of all reports with search and pagination; search by ticket number, student ID, or room; review and confirm room; reject with reason; assign or reassign a maintenance unit and optional technician; handle reopened reports; view full history and comments; enter reports on behalf of residents.

**Technician/contractor:** queue of own active assignments; view job details needed for repair; set IN_PROGRESS or ON_HOLD with reason and expected date; complete with required notes and optional completion photo; comment.

**All:** login and logout, role based dashboards, activity history on every ticket, server side validation of every field.

## 8. REST API (Django REST Framework, JSON, documented with OpenAPI)

| Endpoint | Method | Access |
|---|---|---|
| `/api/reports/` | GET (filtered by role), POST | Authenticated |
| `/api/reports/{id}/` | GET | Object level |
| `/api/reports/{id}/status/` | PATCH | Role gated, via the service function |
| `/api/reports/{id}/assign/` | POST | Officer only |
| `/api/reports/{id}/verify/` | POST | Owning resident |
| `/api/reports/{id}/reopen/` | POST | Owning resident or call-center staff |
| `/api/reports/{id}/comments/` | GET, POST | Object level |
| `/api/reports/{id}/history/` | GET | Object level |
| `/api/reports/{id}/photos/{photo_id}/` | GET | Object level |
| `/api/officer/reports/` | POST | Call-center staff |
| `/api/notifications/` | GET | Own only |
| `/api/buildings/`, `/api/room-locations/`, `/api/categories/`, `/api/units/` | GET | Authenticated |
| `/api/units/results/` | GET | Call-center staff or technician, unit-scoped |

Serializers validate all input. State changing calls use POST or PATCH only, never GET.
The OpenAPI schema and interactive API documentation are available at `/api/schema/`
and `/api/docs/`. API authentication uses the existing Django session; browser clients
must send a CSRF token in `X-CSRFToken` on state-changing requests. Collection endpoints
return paginated results, and stale versioned workflow changes return HTTP 409.

## 9. Security requirements

* Django auth and sessions, password hashing, cookies `Secure`, `HttpOnly`, `SameSite` in production, login rate limiting, generic login errors, login event logging.
* CSRF on all state changes. Template auto escaping on. Never use `|safe` on user text.
* Uploads: allow JPEG and PNG only. Check extension, MIME type, and file signature together. Generate server filenames. Limit size and dimensions (configurable, default 5 MB). Re encode with Pillow to strip EXIF and location data. Store outside executable paths and serve only through an authenticated download view with an authorization check.
* Emails contain only ticket ID, a short event description, and a link. Never room details, contact details, comments, or photos.
* Redact personal data in logs. `DEBUG` off in production, `ALLOWED_HOSTS` restricted, `manage.py check --deploy` must pass, HTTPS only.

## 10. Notifications

Email (Django email backend, console backend in development) sent via `transaction.on_commit` on: report submitted, assigned, held, completed/closed (resident asked to verify), reopened (to call-center staff), and rejected (with reason). Record each in Notification, log failures, never roll back the workflow because email failed. The `/api/notifications/` endpoint returns the authenticated user's notifications and supports incremental polling with `since`.

## 11. Non functional requirements

* Paginated, indexed list queries (use `select_related`). Reasonable load: about 300 residents, 3 to 5 officers, 8 to 12 technicians.
* Backups of database and media documented, with a tested restore.
* Structured logging and a health check endpoint.
* Automated tests with coverage reported in CI. Seed command creating clearly labelled synthetic users, buildings, categories, and reports.

## 12. Acceptance criteria (tests that must exist and pass)

1. **Full workflow:** one test runs submit → review → assign → in progress → complete → verify, checking database rows (Report, Assignment, StatusHistory, Verification, Notification) at every step.
2. **Reopen and reassign:** reopen, then reassign to another technician. The old Assignment remains with `is_active=False`, and the new one is active.
3. **Invalid transitions:** every disallowed pair in section 3, and every correct transition by the wrong role, is rejected and leaves the database unchanged.
4. **Authorization:** two residents cannot see or change each other's reports by changing the URL or API ID. A technician cannot open an unassigned report. A resident cannot call officer endpoints. Unauthenticated requests are rejected. Hidden buttons are not relied on.
5. **Concurrency:** two simultaneous assignment attempts on one report produce exactly one active assignment and one conflict response.
6. **Verification and reopening:** optional rating is accepted after closure; resident or officer reopening requires a reason and is limited to the three-day window.
7. **Input and files:** invalid forms, oversized files, wrong file types, disguised files, and script in descriptions or comments are rejected or rendered as plain text. EXIF is removed from stored images.
8. **CSRF:** state changes without a token fail. No state change accepts GET.
9. **API:** each endpoint tested for success, validation failure, and permission failure.

## 13. Suggested build order (vertical slices)

1. Scaffold, settings, custom user, roles, login, Docker, CI.
2. Reference data, Report submission with photo pipeline.
3. Call-center intake and queue, review, reject, room verification, assignment with locking.
4. Technician queue, progress updates, completion.
5. Resident verify or reopen, StatusHistory views, comments.
6. Email notifications, search, filters, pagination.
7. REST API and OpenAPI docs.
8. Security tests, concurrency tests, deployment checks.

## 14. Out of MVP (do not build)

Ticket merging, satisfaction surveys, weighted technician ranking, automatic or batch assignment, automated duplicate detection, KPI scoring, SLA reporting, AIT single sign on, map based location, real time or push notifications, hash chained audit logs, asset inventory, preventive maintenance. Unit results are limited to completed job counts and average completion time, without targets or scores. Do not add compliance claims or features that are not listed here.

## 15. Assumptions to confirm (keep configurable)

Categories and subcategories preserve existing values and active flags. Dormitory and Student Village locations are seeded as reference data; Student Village room codes use a two-digit village number (for example `SV04A1`). Accounts are created by an administrator (no open registration). Reopened tickets return to call-center staff for reassignment. The reopening window is three days.
