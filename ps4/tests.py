from django.test import SimpleTestCase

from .content.mvp import MVP_DECISIONS, VALID_DECISIONS


class Ps4PublicPagesTests(SimpleTestCase):
    urls = [
        "/ps4/", "/ps4/findings/", "/ps4/personas/", "/ps4/scenarios/",
        "/ps4/prototype/", "/ps4/alternatives/", "/ps4/permissions/",
        "/ps4/mvp/", "/ps4/summary/",
    ]

    def test_public_pages_return_200(self):
        for url in self.urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)

    def test_persona_and_scenario_details(self):
        self.assertEqual(self.client.get("/ps4/personas/resident/").status_code, 200)
        self.assertEqual(self.client.get("/ps4/scenarios/resident-submits/").status_code, 200)
        self.assertEqual(self.client.get("/ps4/personas/not-a-persona/").status_code, 404)
        self.assertEqual(self.client.get("/ps4/scenarios/not-a-scenario/").status_code, 404)

    def test_mvp_decisions_are_valid(self):
        for item in MVP_DECISIONS:
            self.assertIn(item["decision"], VALID_DECISIONS)

    def test_pending_markers_and_required_content(self):
        response = self.client.get("/ps4/findings/")
        self.assertContains(response, "28 October 2026")
        self.assertContains(response, "[PENDING:")
