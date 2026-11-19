from django import forms
from django.conf import settings
from django.db.models import Count, Q

from accounts.models import Building, Unit, User
from reports.models import Category, Report


class TechnicianChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.get_full_name() or obj.username} (active jobs: {obj.active_job_count})"


class AssignTechnicianForm(forms.Form):
    unit = forms.ModelChoiceField(queryset=Unit.objects.none())
    technician = TechnicianChoiceField(queryset=User.objects.none(), required=False)
    priority = forms.ChoiceField(
        choices=settings.PRIORITY_CHOICES, required=False
    )
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)

    def __init__(self, *args, report, **kwargs):
        super().__init__(*args, **kwargs)
        suggested_unit = (
            report.subcategory.default_unit
            if report.subcategory and report.subcategory.default_unit_id
            else report.category.default_unit
        )
        self.fields["unit"].queryset = Unit.objects.filter(is_active=True)
        self.fields["unit"].initial = suggested_unit
        selected_unit_id = (
            self.data.get("unit")
            if self.is_bound
            else getattr(suggested_unit, "pk", None)
        )
        technician_queryset = User.objects.filter(
            role=User.Role.TECHNICIAN_CONTRACTOR,
            is_active=True,
        )
        if selected_unit_id:
            technician_queryset = technician_queryset.filter(unit_id=selected_unit_id)
        self.fields["technician"].queryset = (
            technician_queryset
            .annotate(
                active_job_count=Count(
                    "assignments_received",
                    filter=Q(assignments_received__is_active=True),
                    distinct=True,
                ),
            )
            .order_by("active_job_count", "username")
        )
        self.fields["technician"].label = "Technician/Contractor"
        self.fields["priority"].required = (
            report.status == "UNDER_REVIEW"
        )
        self.fields["priority"].label = "Priority"
        self.fields["version"].initial = report.version

    def clean(self):
        cleaned_data = super().clean()
        unit = cleaned_data.get("unit")
        technician = cleaned_data.get("technician")
        if technician and unit and technician.unit_id != unit.pk:
            self.add_error("technician", "Choose a technician from the selected unit.")
        return cleaned_data


class ReviewReportForm(forms.Form):
    room_verified = forms.BooleanField(
        required=True,
        label="I confirm the room and building match this request",
    )
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)

    def __init__(self, *args, report, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["version"].initial = report.version

class RejectReportForm(forms.Form):
    reason = forms.CharField(max_length=400, widget=forms.Textarea(attrs={"rows": 3}))
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)

    def __init__(self, *args, report, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["version"].initial = report.version


class SetPriorityForm(forms.Form):
    priority = forms.ChoiceField(choices=settings.PRIORITY_CHOICES)
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)

    def __init__(self, *args, report, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["version"].initial = report.version


class CallCenterQueueFilterForm(forms.Form):
    ticket_no = forms.CharField(max_length=30, required=False, label="Ticket number")
    student_id = forms.CharField(max_length=50, required=False, label="Student ID")
    room = forms.CharField(max_length=100, required=False, label="Room")
    status = forms.ChoiceField(
        choices=(("", "All statuses"), *Report.Status.choices),
        required=False,
    )
    priority = forms.ChoiceField(
        choices=(("", "All priorities"), *settings.PRIORITY_CHOICES),
        required=False,
    )
    category = forms.ModelChoiceField(
        queryset=Category.objects.none(),
        required=False,
        empty_label="All categories",
    )
    building = forms.ModelChoiceField(
        queryset=Building.objects.none(),
        required=False,
        empty_label="All buildings",
    )
    follow_up = forms.BooleanField(required=False, label="Resident follow-ups")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = Category.objects.order_by("name")
        self.fields["building"].queryset = Building.objects.order_by("zone", "name")
