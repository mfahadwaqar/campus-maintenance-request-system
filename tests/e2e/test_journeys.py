"""End-to-end journeys in a real browser (a small set of critical, deterministic journeys).

Rules from lecture 6.2: create test state inside the test, use role and label locators, rely on
auto-waiting assertions instead of sleeps, and keep permission permutations in lower-level tests.
"""

import pytest
from playwright.sync_api import expect

from reports.models import Category, Report, Subcategory

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]


@pytest.fixture(autouse=True)
def reseed_rules():
    """Live-server tests commit for real; the status rules are table data, so restore them."""
    from reports.transitions import seed_allowed_transitions

    seed_allowed_transitions()


def status_pill(page, text):
    """The coloured status label on a ticket page (not the same words inside a dropdown)."""
    return page.locator("span.status").filter(has_text=text).first


# ---------------------------------------------------------------- login
def test_staff_sign_in_and_land_on_the_queue(page, live_server, sign_in, staff):
    sign_in(staff)

    expect(page.get_by_role("heading", name="Maintenance request queue")).to_be_visible()
    expect(page.get_by_role("link", name="New ticket")).to_be_visible()


def test_a_wrong_password_shows_an_error_and_stays_on_the_login_page(page, live_server, resident):
    page.goto(f"{live_server.url}/login/")
    page.get_by_label("Username").fill(resident.username)
    page.get_by_label("Password").fill("not-the-password")
    page.get_by_role("button", name="Log in").click()

    expect(page.get_by_text("was not recognized")).to_be_visible()
    expect(page).to_have_url(f"{live_server.url}/login/")


# ---------------------------------------------------------------- the main journey
def test_resident_submits_a_request_and_sees_it_in_the_list(
    page, live_server, sign_in, resident, building, room, category
):
    sign_in(resident)

    page.get_by_role("link", name="New request").click()
    page.get_by_label("Category", exact=True).select_option(label=category.name)
    page.get_by_label("Building", exact=True).select_option(label=building.name)
    page.get_by_label("Dorm room or Student Village room").fill(room.code)
    page.get_by_label("Title").fill("Leaking tap in A101")
    page.get_by_label("Description").fill("The tap drips all night.")
    page.get_by_label("Requested urgency").select_option(label="High")
    page.get_by_label("I confirm the selected building and room are correct").check()
    page.get_by_role("button", name="Submit request").click()

    expect(page.get_by_role("heading", name="Leaking tap in A101")).to_be_visible()
    assert Report.objects.get().title == "Leaking tap in A101"

    page.get_by_role("link", name="My requests").click()
    expect(page.get_by_role("link", name="Leaking tap in A101")).to_be_visible()


def test_a_repair_goes_from_request_to_reopened_across_three_people(
    page, live_server, sign_in, resident, staff, technician, unit, new_report
):
    report = new_report(title="Broken window latch")

    # --- staff review and assign
    sign_in(staff)
    page.goto(f"{live_server.url}/officer/reports/{report.pk}/")
    page.get_by_label("I confirm the room and building match this request").check()
    page.get_by_role("button", name="Begin review").click()
    page.goto(f"{live_server.url}/officer/reports/{report.pk}/")  # review returns to the queue
    expect(status_pill(page, "Under review")).to_be_visible()
    page.get_by_label("Priority").select_option(label="High")
    page.get_by_role("button", name="Save priority").click()
    page.get_by_role("link", name="Choose unit and technician").click()
    page.get_by_label("Unit").select_option(label=unit.name)
    page.get_by_label("Technician/Contractor").select_option(index=1)  # the only technician in the unit
    page.get_by_role("button", name="Confirm assignment").click()
    expect(status_pill(page, "Assigned")).to_be_visible()

    # --- technician starts and completes
    sign_in(technician)
    page.goto(f"{live_server.url}/technician/reports/{report.pk}/")
    page.get_by_role("button", name="Start work").click()
    expect(status_pill(page, "In progress")).to_be_visible()
    page.get_by_label("Completion notes").fill("Replaced the latch.")
    page.get_by_role("button", name="Mark complete").click()
    page.wait_for_load_state("networkidle")

    # --- resident sees it closed with the reopen window, then reopens
    sign_in(resident)
    page.goto(f"{live_server.url}/reports/{report.pk}/")
    expect(status_pill(page, "Closed")).to_be_visible()
    expect(page.get_by_text("Reopen window open")).to_be_visible()
    expect(page.get_by_text("Replaced the latch.")).to_be_visible()
    page.get_by_label("Reason").fill("The latch has broken again.")
    page.get_by_role("button", name="Reopen request").click()
    expect(status_pill(page, "Assigned")).to_be_visible()

    report.refresh_from_db()
    assert report.status == "ASSIGNED"


# ---------------------------------------------------------------- behaviour only a browser can show
def test_the_subcategory_list_follows_the_chosen_category(page, live_server, sign_in, resident):
    plumbing = Category.objects.create(name="Plumbing E2E")
    electric = Category.objects.create(name="Electrical E2E")
    Subcategory.objects.create(category=plumbing, name="Leaking pipe")
    Subcategory.objects.create(category=electric, name="Broken socket")
    sign_in(resident)
    page.goto(f"{live_server.url}/reports/new/")
    subcategory = page.get_by_label("Subcategory")

    expect(subcategory.locator("option")).to_have_text(["Choose a category first"])

    page.get_by_label("Category", exact=True).select_option(label="Plumbing E2E")
    expect(subcategory.locator("option")).to_have_text(["- Select an option -", "Leaking pipe"])
    subcategory.select_option(label="Leaking pipe")

    page.get_by_label("Category", exact=True).select_option(label="Electrical E2E")
    expect(subcategory.locator("option")).to_have_text(["- Select an option -", "Broken socket"])
    expect(subcategory).to_have_value("")  # the old choice does not survive a category change


def test_a_new_comment_appears_on_the_staff_screen_without_a_refresh(
    page, live_server, sign_in, staff, resident, flow, assigned_report
):
    sign_in(staff)
    page.goto(f"{live_server.url}/officer/reports/{assigned_report.pk}/")
    expect(page.get_by_text("Comments updated at")).to_be_visible(timeout=15_000)

    flow.comment(assigned_report, resident, "The water is getting worse")  # posted by someone else

    expect(page.get_by_text("The water is getting worse")).to_be_visible(timeout=20_000)


def test_checkbox_labels_sit_beside_their_boxes(page, live_server, sign_in, resident):
    sign_in(resident)
    page.goto(f"{live_server.url}/reports/new/")
    wording = "I confirm the selected building and room are correct"

    box = page.get_by_label(wording).bounding_box()
    text = page.get_by_text(wording).bounding_box()

    assert box["x"] < text["x"]
    assert abs((box["y"] + box["height"] / 2) - (text["y"] + text["height"] / 2)) < 12


@pytest.mark.parametrize("path", ["/reports/new/", "/reports/"])
def test_pages_do_not_scroll_sideways_on_a_phone(page, live_server, sign_in, resident, path):
    page.set_viewport_size({"width": 375, "height": 800})
    sign_in(resident)
    page.goto(f"{live_server.url}{path}")

    overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")

    assert overflow <= 1


def test_the_light_theme_is_used_even_when_the_system_prefers_dark(page, live_server, sign_in, resident):
    page.emulate_media(color_scheme="dark")
    sign_in(resident)

    background = page.evaluate("getComputedStyle(document.body).backgroundColor")

    channels = [int(v) for v in background[background.index("(") + 1 : -1].split(",")[:3]]
    assert min(channels) > 200  # a light page
