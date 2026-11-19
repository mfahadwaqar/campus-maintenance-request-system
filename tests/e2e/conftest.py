"""Browser (system / end-to-end) tests: Playwright drives a real browser against live_server.

Lecture 6.2: the Django test Client never runs JavaScript or renders CSS; a real browser does.
We use the Microsoft Edge that is already installed (channel "msedge"), so nothing is downloaded.
Test data is created inside each test, never taken from a developer database.
"""

import os

import pytest

# Playwright's sync API runs an event loop; Django's ORM refuses to run inside one unless told.
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

from tests.conftest import PASSWORD

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    # Locally we reuse the installed Microsoft Edge. In CI set E2E_BROWSER_CHANNEL="" to use
    # the Chromium that "playwright install chromium" provides.
    channel = os.environ.get("E2E_BROWSER_CHANNEL", "msedge")
    args = {**browser_type_launch_args, "headless": True}
    if channel:
        args["channel"] = channel
    return args


@pytest.fixture
def sign_in(page, live_server):
    """Return a function that signs a user in through the real login form."""

    def login(user):
        page.context.clear_cookies()
        page.goto(f"{live_server.url}/login/")
        page.get_by_label("Username").fill(user.username)
        page.get_by_label("Password").fill(PASSWORD)
        page.get_by_role("button", name="Log in").click()
        page.wait_for_load_state("networkidle")

    return login
