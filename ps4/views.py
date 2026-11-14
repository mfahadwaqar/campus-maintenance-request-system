from django.http import Http404
from django.shortcuts import render

from .content.alternatives import ALTERNATIVES
from .content.findings import FINDINGS
from .content.mvp import MVP_DECISIONS, VALID_DECISIONS
from .content.personas import PERSONAS
from .content.permissions import PERMISSIONS
from .content.prototype import PROTOTYPE
from .content.scenarios import SCENARIOS
from .content.summary import SUMMARY
from .content.study import STUDY


def index(request):
    return render(
        request,
        "ps4/index.html",
        {"study": STUDY, "personas": PERSONAS, "scenarios": SCENARIOS},
    )


def findings(request):
    return render(request, "ps4/findings.html", {"findings": FINDINGS})


def personas(request):
    return render(request, "ps4/personas.html", {"personas": PERSONAS})


def persona_detail(request, slug):
    persona = next((item for item in PERSONAS if item["slug"] == slug), None)
    if persona is None:
        raise Http404
    scenarios_by_slug = {item["slug"]: item for item in SCENARIOS}
    linked_scenarios = [
        scenarios_by_slug[scenario_slug]
        for scenario_slug in persona["scenario_slugs"]
    ]
    return render(
        request,
        "ps4/persona_detail.html",
        {
            "persona": persona,
            "personas": PERSONAS,
            "linked_scenarios": linked_scenarios,
            "study": STUDY,
        },
    )


def scenarios(request):
    return render(request, "ps4/scenarios.html", {"scenarios": SCENARIOS})


def scenario_detail(request, slug):
    scenario = next((item for item in SCENARIOS if item["slug"] == slug), None)
    if scenario is None:
        raise Http404
    return render(
        request,
        "ps4/scenario_detail.html",
        {"scenario": scenario, "study": STUDY},
    )


def prototype(request):
    return render(request, "ps4/prototype.html", {"prototype": PROTOTYPE})


def alternatives(request):
    return render(request, "ps4/alternatives.html", {"alternatives": ALTERNATIVES})


def permissions(request):
    return render(request, "ps4/permissions.html", {"permissions": PERMISSIONS})


def mvp(request):
    return render(request, "ps4/mvp.html", {"decisions": MVP_DECISIONS, "valid_decisions": VALID_DECISIONS})


def summary(request):
    return render(request, "ps4/summary.html", {"summary": SUMMARY})
