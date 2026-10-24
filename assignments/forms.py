from django import forms
from django.conf import settings
from django.db.models import Count, Exists, OuterRef, Q

from accounts.models import Building, User
from reports.models import Category, Report
from .models import TechnicianSpecialization


class TechnicianChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.get_full_name() or obj.username} (active jobs: {obj.active_job_count})"


class AssignTechnicianForm(forms.Form):
    technician = TechnicianChoiceField(queryset=User.objects.none())
    priority = forms.ChoiceField(
        choices=settings.PRIORITY_CHOICES, required=False
    )
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)

    def __init__(self, *args, report, **kwargs):
        super().__init__(*args, **kwargs)
        matching_specialization = TechnicianSpecialization.objects.filter(
            technician_id=OuterRef("pk"), category=report.category
        )
        self.fields["technician"].queryset = (
            User.objects.filter(role=User.Role.TECHNICIAN, is_active=True)
            .annotate(
                matches_category=Exists(matching_specialization),
                active_job_count=Count(
                    "assignments_received",
                    filter=Q(assignments_received__is_active=True),
                    distinct=True,
                ),
            )
            .order_by("-matches_category", "active_job_count", "username")
        )
        self.fields["technician"].label = "Technician"
        self.fields["priority"].required = (
            report.status == "UNDER_REVIEW"
        )
        self.fields["priority"].label = "Priority"
        self.fields["version"].initial = report.version


class ReviewReportForm(forms.Form):
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)

    def __init__(self, *args, report, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["version"].initial = report.version


class OfficerQueueFilterForm(forms.Form):
    status = forms.ChoiceField(
        choices=(("", "All statuses"), *Report.Status.choices), required=False
    )
    category = forms.ModelChoiceField(
        queryset=Category.objects.none(), required=False, empty_label="All categories"
    )
    building = forms.ModelChoiceField(
        queryset=Building.objects.none(), required=False, empty_label="All buildings"
    )
    priority = forms.ChoiceField(
        choices=(("", "All priorities"), *settings.PRIORITY_CHOICES),
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = Category.objects.order_by("name")
        self.fields["building"].queryset = Building.objects.order_by("zone", "name")


class RejectReportForm(forms.Form):
    reason = forms.CharField(max_length=500, widget=forms.Textarea(attrs={"rows": 3}))
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)

    def __init__(self, *args, report, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["version"].initial = report.version


class DuplicateReportForm(forms.Form):
    master_report = forms.ModelChoiceField(queryset=Report.objects.none())
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)

    def __init__(self, *args, report, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["master_report"].queryset = (
            Report.objects.exclude(pk=report.pk)
            .exclude(status__in=(Report.Status.MERGED, Report.Status.REJECTED))
            .order_by("-created_at")
        )
        self.fields["version"].initial = report.version


class SetPriorityForm(forms.Form):
    priority = forms.ChoiceField(choices=settings.PRIORITY_CHOICES)
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)

    def __init__(self, *args, report, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["version"].initial = report.version
