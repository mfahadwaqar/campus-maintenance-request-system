# Runs the 20 key tests (one to five per test type) for the demonstration.
# Needs: PostgreSQL running (docker container "cms-pg"), the project .venv, Microsoft Edge for test 20.
# Use:   .\run_key_tests.ps1

$env:DB_ENGINE = "postgres"
$env:POSTGRES_HOST = "localhost"
$env:POSTGRES_PORT = "55432"
$env:POSTGRES_USER = "campus"
$env:POSTGRES_PASSWORD = "ci-test-pw"
$env:POSTGRES_DB = "campus_keytests"
$env:DJANGO_SECRET_KEY = "test-key"

$tests = @(
    # Unit (5): one rule on its own
    "tests/unit/test_service_rules.py::test_reopen_just_inside_the_three_day_window_is_allowed",
    "tests/unit/test_service_rules.py::test_reopen_just_outside_the_window_is_refused_with_its_own_code",
    "tests/unit/test_service_rules.py::test_completion_closes_the_ticket_in_the_same_step_with_two_history_rows",
    "tests/unit/test_service_rules.py::test_a_technician_must_belong_to_the_chosen_unit",
    "tests/unit/test_service_rules.py::test_comment_on_a_closed_ticket_is_refused_and_nothing_is_saved",
    # Integration (3): pages, database and login together
    "tests/integration/test_journey_greybox.py::test_a_ticket_travels_from_submission_to_a_reopened_assignment",
    "tests/integration/test_journey_greybox.py::test_staff_find_tickets_by_room_ticket_number_and_student_id",
    "tests/integration/test_journey_greybox.py::test_an_uploaded_photo_is_stored_and_only_visible_to_the_right_people",
    # Security (4)
    "tests/security/test_security.py::test_a_resident_cannot_use_staff_or_technician_api_actions",
    "tests/security/test_security.py::test_mass_assignment_cannot_set_status_owner_or_ticket_number",
    "tests/security/test_security.py::test_an_unassigned_technician_cannot_read_or_comment",
    "tests/security/test_security.py::test_html_in_a_comment_is_escaped",
    # Performance (1)
    "tests/performance/test_queries.py::test_the_staff_queue_does_not_run_more_queries_for_more_tickets",
    # Reliability (2)
    "tests/reliability/test_failures_and_concurrency.py::test_two_staff_acting_on_the_same_version_one_wins_and_one_gets_a_conflict",
    "tests/reliability/test_failures_and_concurrency.py::test_if_closing_fails_the_completion_is_rolled_back_too",
    # Acceptance, Given / When / Then (2)
    "tests/bdd/test_request_lifecycle.py::test_completing_a_job_closes_the_ticket_without_any_staff_action",
    "tests/bdd/test_request_lifecycle.py::test_a_request_for_a_room_that_does_not_exist_is_refused",
    # Regression (2): defects that were found and fixed
    "tests/regression/test_regressions.py::test_R2_reopening_after_verifying_replaces_the_verification_instead_of_crashing",
    "tests/regression/test_regressions.py::test_R13_a_technician_sees_the_residents_photo_on_the_work_order_page",
    # End to end (1): a real browser, three people
    "tests/e2e/test_journeys.py::test_a_repair_goes_from_request_to_reopened_across_three_people"
)

& .\.venv\Scripts\python.exe -m pytest @tests -v -W ignore --no-header -p no:cacheprovider
