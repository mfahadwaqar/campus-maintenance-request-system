import re
from html import unescape
from pathlib import Path

from django.test import SimpleTestCase

from .content.alternatives import ALTERNATIVES
from .content.mvp import MVP_DECISIONS, VALID_DECISIONS
from .content.personas import PERSONAS
from .content.prototype import PROTOTYPE
from .content.scenarios import SCENARIOS
from .content.study import STUDY


class Ps4PublicPagesTests(SimpleTestCase):
    urls = [
        "/ps4/",
        "/ps4/findings/",
        "/ps4/personas/",
        "/ps4/scenarios/",
        "/ps4/prototype/",
        "/ps4/alternatives/",
        "/ps4/permissions/",
        "/ps4/mvp/",
        "/ps4/summary/",
    ]

    def test_public_pages_return_200(self):
        for url in self.urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_persona_and_scenario_details(self):
        for persona in PERSONAS:
            with self.subTest(persona=persona["slug"]):
                self.assertEqual(
                    self.client.get(f"/ps4/personas/{persona['slug']}/").status_code,
                    200,
                )
        for scenario in SCENARIOS:
            with self.subTest(scenario=scenario["slug"]):
                self.assertEqual(
                    self.client.get(f"/ps4/scenarios/{scenario['slug']}/").status_code,
                    200,
                )
        self.assertEqual(self.client.get("/ps4/personas/not-a-persona/").status_code, 404)
        self.assertEqual(self.client.get("/ps4/scenarios/not-a-scenario/").status_code, 404)

    def test_personas_have_complete_fields_and_traceable_evidence(self):
        required_fields = {
            "slug",
            "name",
            "role",
            "summary",
            "background",
            "short_term_goal",
            "long_term_goal",
            "typical_tasks",
            "frustrations",
            "constraints",
            "expectations",
            "feedback_gaps",
            "evidence",
            "scenario_slugs",
            "interview_note",
        }
        scenario_slugs = {scenario["slug"] for scenario in SCENARIOS}

        for persona in PERSONAS:
            with self.subTest(persona=persona["slug"]):
                self.assertTrue(required_fields.issubset(persona))
                self.assertTrue(persona["scenario_slugs"])
                self.assertTrue(set(persona["scenario_slugs"]).issubset(scenario_slugs))
                for evidence in persona["evidence"]:
                    self.assertTrue(evidence["code"])
                    self.assertIn(evidence["type"], {"observed", "interpretation"})

    def test_persona_pages_render_fields_scenarios_and_navigation_in_order(self):
        for persona in PERSONAS:
            with self.subTest(persona=persona["slug"]):
                response = self.client.get(f"/ps4/personas/{persona['slug']}/")
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, persona["name"])
                self.assertContains(response, "Composite profiles based on interviews.")
                self.assertContains(response, "Back to PS4")

                html = response.content.decode()
                markers = [
                    f"<h1>{persona['name']}</h1>",
                    "<strong>Role:</strong>",
                    "<h2>Summary</h2>",
                    "<h2>Background</h2>",
                    "<h3>Short-term goal</h3>",
                    "<h3>Long-term goal</h3>",
                    "<h2>Typical tasks</h2>",
                    "<h2>Frustrations</h2>",
                    "<h2>Constraints</h2>",
                    "<h2>Expectations of the application</h2>",
                    "<h2>Gaps in the app that the feedback exposed</h2>",
                    "<h2>Evidence</h2>",
                    "<h2>Scenarios</h2>",
                    "<h2>Interview note</h2>",
                    "Back to PS4",
                ]
                positions = [html.index(marker) for marker in markers]
                self.assertEqual(positions, sorted(positions))

                rendered_scenarios = {
                    scenario["slug"]
                    for scenario in response.context["linked_scenarios"]
                }
                self.assertEqual(rendered_scenarios, set(persona["scenario_slugs"]))
                for other_persona in PERSONAS:
                    if other_persona["slug"] != persona["slug"]:
                        self.assertContains(response, other_persona["name"])

    def test_feedback_gaps_are_shown_on_the_relevant_persona_pages(self):
        expected_gaps = {
            "resident": "The closure rule has changed",
            "officer": "The Call Center Staff queue cannot be searched by student ID or room",
            "unit-worker": "Technician/Contractor users cannot put a job on hold",
        }
        for slug, gap_title in expected_gaps.items():
            with self.subTest(persona=slug):
                response = self.client.get(f"/ps4/personas/{slug}/")
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Gaps in the app that the feedback exposed")
                self.assertContains(response, "What the feedback showed")
                self.assertContains(response, "What the app does now")
                self.assertContains(response, gap_title)
    def test_index_lists_four_study_entries_and_all_personas_and_scenarios(self):
        response = self.client.get("/ps4/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(STUDY["interviews"]), 4)
        self.assertEqual(len(response.context["study"]["interviews"]), 4)
        self.assertNotContains(response, "OFAM staff follow-up answer (OFAM-3)")

        for interview in STUDY["interviews"]:
            self.assertContains(response, interview["date"])
            self.assertContains(response, interview["mode"])
            self.assertContains(response, interview["venue"])
            self.assertContains(response, interview["participants"])
        for persona in PERSONAS:
            self.assertContains(response, persona["name"])
        for scenario in SCENARIOS:
            self.assertContains(response, scenario["title"])
        self.assertEqual(
            STUDY["interviews"][2],
            {
                "date": "14 November 2026",
                "mode": "In person",
                "venue": "Student Village SV04",
                "participants": "Student resident (R1)",
                "purpose": "Experience of reporting a fault, following it up, and the outcome.",
            },
        )
        self.assertEqual(
            STUDY["interviews"][3],
            {
                "date": "14 November 2026",
                "mode": "In person",
                "venue": "Student Village SV04",
                "participants": "Student resident (R2)",
                "purpose": "Experience of reporting a gas-related fault that the resident perceived as urgent, and of the ticket notice received by email.",
            },
        )
    def test_pages_and_content_do_not_use_replaced_terms(self):
        urls = [
            "/ps4/",
            "/ps4/personas/",
            "/ps4/scenarios/",
            *(f"/ps4/personas/{persona['slug']}/" for persona in PERSONAS),
            *(f"/ps4/scenarios/{scenario['slug']}/" for scenario in SCENARIOS),
        ]
        restricted_terms = ("mobile" + " app",)
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                body = response.content.decode().lower()
                for term in restricted_terms:
                    self.assertNotIn(term, body)

        ps4_root = Path(__file__).resolve().parent
        repo_root = ps4_root.parent
        files = [
            *(path for path in ps4_root.rglob("*.py") if path.name != "tests.py"),
            *(repo_root.joinpath("templates", "ps4").rglob("*.html")),
            repo_root / "docs" / "ps4" / "Q2_personas_and_scenarios.md",
        ]
        for path in files:
            with self.subTest(file=path):
                content = path.read_text().lower()
                for term in restricted_terms:
                    self.assertNotIn(term, content)

    def test_resident_submission_uses_phone_browser(self):
        scenario = next(item for item in SCENARIOS if item["slug"] == "resident-submits")
        self.assertIn("phone browser", scenario["trigger"])
        self.assertTrue(any("phone browser" in step for step in scenario["steps"]))
        response = self.client.get("/ps4/scenarios/resident-submits/")
        self.assertContains(response, "phone browser")

    def test_gas_fault_scenario_records_serious_same_day_handling(self):
        scenario = next(item for item in SCENARIOS if item["slug"] == "resident-gas-pipe-fault")
        self.assertEqual(scenario["persona"], "resident")
        self.assertEqual(scenario["title"], "G: Resident reports a serious gas-pipe fault in person")
        scenario_text = " ".join(
            [
                scenario["source"],
                scenario["trigger"],
                *scenario["steps"],
                scenario["expected"],
                scenario["exception"],
            ]
        ).lower()
        self.assertNotIn("routine", scenario_text)
        self.assertNotIn("to be confirmed", scenario_text)
        self.assertIn("same action", scenario_text)
        self.assertIn("available technician/contractor", scenario_text)
        self.assertIn("r2", " ".join(scenario["steps"]).lower())
        self.assertIn("ofam-3", " ".join(scenario["steps"]).lower())

        resident_evidence = next(persona for persona in PERSONAS if persona["slug"] == "resident")["evidence"]
        gas_evidence = [
            item
            for item in resident_evidence
            if item["code"] in {"R2", "OFAM-3"}
        ]
        self.assertEqual({item["code"] for item in gas_evidence}, {"R2", "OFAM-3"})
        for evidence in gas_evidence:
            self.assertIn(evidence["type"], {"observed", "interpretation"})

    def test_gas_fault_page_and_report_do_not_call_handling_routine(self):
        resident = next(persona for persona in PERSONAS if persona["slug"] == "resident")
        resident_evidence = " ".join(
            evidence["claim"]
            for evidence in resident["evidence"]
            if evidence["code"] in {"R2", "OFAM-3"}
        )
        resident_text = " ".join(
            [
                resident["frustrations"][-1],
                resident["expectations"][-2],
                resident_evidence,
            ]
        ).lower()
        self.assertNotIn("routine", resident_text)

        resident_response = self.client.get("/ps4/personas/resident/")
        self.assertEqual(resident_response.status_code, 200)
        self.assertNotIn("routine", resident_response.content.decode().lower())

        scenario_response = self.client.get("/ps4/scenarios/resident-gas-pipe-fault/")
        self.assertEqual(scenario_response.status_code, 200)
        self.assertNotIn("routine", scenario_response.content.decode().lower())

        report_path = (
            Path(__file__).resolve().parent.parent
            / "docs"
            / "ps4"
            / "Q2_personas_and_scenarios.md"
        )
        report = report_path.read_text().lower()
        resident_narrative = report.split("### illustrative narrative", 1)[1].split("## call center staff", 1)[0]
        self.assertNotIn("routine", resident_narrative)
        self.assertNotIn("to be confirmed", resident_narrative)

    def test_research_pages_have_no_pending_placeholders_or_tags(self):
        urls = [
            *self.urls,
            *(f"/ps4/personas/{persona['slug']}/" for persona in PERSONAS),
            *(f"/ps4/scenarios/{scenario['slug']}/" for scenario in SCENARIOS),
        ]
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                body = response.content.decode()
                for placeholder in ("[PENDING:", "[Team to test:", "[Title and date"):
                    self.assertNotIn(placeholder, body)
                self.assertNotIn('class="pending"', body)

    def test_q2_report_is_evidence_linked_and_anonymized(self):
        report_path = (
            Path(__file__).resolve().parent.parent
            / "docs"
            / "ps4"
            / "Q2_personas_and_scenarios.md"
        )
        self.assertTrue(report_path.is_file())
        report = report_path.read_text()
        for heading in ("## Resident", "## Call Center Staff", "## Technician/Contractor"):
            self.assertIn(heading, report)
        self.assertEqual(report.count("This narrative is illustrative"), 3)

        narrative_sections = re.findall(
            r"^### Illustrative narrative\s*\n(.*?)(?=^### |^## |\Z)",
            report,
            flags=re.MULTILINE | re.DOTALL,
        )
        self.assertEqual(len(narrative_sections), 3)
        for section in narrative_sections:
            paragraphs = [paragraph for paragraph in section.strip().split("\n\n") if paragraph.strip()]
            for paragraph in paragraphs:
                self.assertRegex(
                    paragraph,
                    r"\[(?:OFAM-1|OFAM-2|OFAM-3|S1|T1|C1|R1|R2)(?:,\s*(?:OFAM-1|OFAM-2|OFAM-3|S1|T1|C1|R1|R2))*\]\.$",
                )
        self.assertIn("R2 noticed cracks in the gas pipe", report)
        self.assertIn("[R2]", report)
        self.assertIn("The call center recognised the seriousness of the fault", report)
        self.assertIn("[OFAM-3]", report)
        self.assertIn(
            "| OFAM-3 | OFAM staff follow-up answer | 11 November 2026; in person, venue not applicable | observed |",
            report,
        )
        scope_note = (
            "Account R2 describes a gas-pipe fault that the resident experienced as serious. "
            "OFAM confirmed that it recognised the seriousness of the fault, sent the available Technician/Contractor immediately, and that Call Center Staff created and assigned the ticket at the same time (OFAM-3). "
            "The project's current workflow allows Call Center Staff to move a new ticket directly to ASSIGNED, so no new workflow state is needed. "
            "The design must support a same-day path, and the report records this as a change to the workflow description."
        )
        self.assertIn(scope_note, report)
        self.assertRegex(scope_note.lower(), r"creat(?:e|ed) and assign(?:ed)")
        self.assertNotIn("to be confirmed", scope_note.lower())

        for persona in PERSONAS:
            for field in (
                "name",
                "role",
                "summary",
                "background",
                "short_term_goal",
                "long_term_goal",
                "typical_tasks",
                "frustrations",
                "constraints",
                "expectations",
            ):
                values = persona[field] if isinstance(persona[field], list) else [persona[field]]
                for value in values:
                    self.assertIn(value, report)
            for evidence in persona["evidence"]:
                self.assertIn(evidence["claim"], report)
                self.assertIn(evidence["code"], report)

        report_lower = report.lower()
        self.assertNotIn("student" + " id", report_lower)
        self.assertNotIn("transcript", report_lower)
        self.assertNotIn("participant key", report_lower)

    def test_scenario_pages_show_the_required_content(self):
        for scenario in SCENARIOS:
            with self.subTest(scenario=scenario["slug"]):
                response = self.client.get(f"/ps4/scenarios/{scenario['slug']}/")
                body = unescape(response.content.decode())
                self.assertIn(scenario["title"], body)
                self.assertIn(scenario["trigger"], body)
                self.assertIn(scenario["expected"], body)
                self.assertIn(scenario["exception"], body)
                self.assertIn(scenario["source"], body)
                self.assertContains(response, "Back to PS4")
                for step in scenario["steps"]:
                    self.assertIn(step, body)

    def test_mvp_decisions_are_valid(self):
        for item in MVP_DECISIONS:
            self.assertIn(item["decision"], VALID_DECISIONS)

    def test_findings_page_retains_its_existing_content(self):
        response = self.client.get("/ps4/findings/")
        self.assertContains(response, "28 October 2026")
        self.assertContains(response, "30 minutes")
        self.assertContains(
            response,
            "Two student residents (R1 and R2) were interviewed on 14 November 2026 at Student Village SV4, Asian Institute of Technology.",
        )
        self.assertContains(
            response,
            "Call Center Staff (S1) and Technician/Contractor (C1, T1) interviews took place in person on 11 November 2026 at OFAM Building, second floor, Room 210, starting at 14:00.",
        )
        self.assertContains(response, "The current workflow closes work on completion and allows reopening through day three.")
        self.assertNotContains(response, "[PENDING: disagreements")

    def test_prototype_page_shows_the_feedback_gaps_and_changes(self):
        response = self.client.get("/ps4/prototype/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Gaps in the app that the feedback exposed")
        for phrase in (
            "Technician/Contractor users cannot put a job on hold",
            "The Call Center Staff queue cannot be searched by student ID or room",
            "The closure rule has changed",
            "The back end supports a hold, but no screen lets the Technician/Contractor record it.",
            "Add a ticket-number search as well",
            "3-day grace period",
            "Block comments once the ticket is closed.",
        ):
            self.assertContains(response, phrase)
        self.assertNotContains(response, "[PENDING:")

    def test_prototype_page_renders_figures_four_through_nine(self):
        response = self.client.get("/ps4/prototype/")
        self.assertEqual(response.status_code, 200)
        for number in range(4, 10):
            image_path = f"ps4/prototype_images/figure-{number}.png"
            self.assertContains(response, f"/static/{image_path}")
            self.assertTrue(
                (Path(__file__).resolve().parent / "static" / image_path).is_file()
            )

    def test_alternatives_page_shows_current_comparison_and_test_placeholders(self):
        response = self.client.get("/ps4/alternatives/")
        self.assertEqual(response.status_code, 200)
        body = unescape(response.content.decode())
        for phrase in (
            "Service window, telephone, email, and walk-in requests",
            "Needs no account.",
            "Fast for serious cases.",
            "Personal contact.",
            "Jira Service Management",
            "MaintainX",
            "FixMyStreet",
            "FIMS.",
            "The comparators are general-purpose service or public reporting platforms.",
            "The comparison supports building a residence-specific application only if the gaps found in interviews are real",
            "Requester walkthroughs for Jira and MaintainX not completed.",
            "The OFAM user guide was not available for review.",
            "The public page asks for a work email",
            "No account needed. The site's FAQ says you can report without registering",
            "Accessed",
            "Figure A1",
            "Figure A6",
            "Bad recaptcha",
            "Sign Up for Free",
            "What our system adds:",
        ):
            self.assertIn(phrase, body)
        self.assertEqual(len(ALTERNATIVES["comparators"]), 3)
        self.assertIn(ALTERNATIVES["access_date_summary"], body)

        def all_strings(value):
            if isinstance(value, dict):
                for nested_value in value.values():
                    yield from all_strings(nested_value)
            elif isinstance(value, list):
                for nested_value in value:
                    yield from all_strings(nested_value)
            elif isinstance(value, str) and value:
                yield value

        for value in all_strings(ALTERNATIVES):
            self.assertIn(value, body)

        for screenshot in ALTERNATIVES["screenshots"]:
            self.assertIn(f"/static/{screenshot['image']}", body)
            image_path = Path(__file__).resolve().parent / "static" / screenshot["image"]
            self.assertTrue(image_path.is_file())

    def test_prototype_page_shows_walkthrough_ratings_and_observations(self):
        response = self.client.get("/ps4/prototype/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "3. Which steps were understandable, confusing, missing or unnecessary",
        )
        for column in ("Step", "Rating", "Who", "Observation", "Design implication"):
            self.assertContains(response, f"<th>{column}</th>")

        self.assertEqual(len(PROTOTYPE["walkthrough_steps"]), 9)
        body = unescape(response.content.decode())
        for item in PROTOTYPE["walkthrough_steps"]:
            for value in item.values():
                self.assertIn(value, body)
