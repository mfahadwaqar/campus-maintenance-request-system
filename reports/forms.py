from django import forms
from django.conf import settings

from .models import Report
from .photo_pipeline import validate_and_reencode_photo


class ReportSubmissionForm(forms.ModelForm):
    requested_urgency = forms.ChoiceField(choices=settings.REQUESTED_URGENCY_CHOICES)
    photo = forms.FileField(required=False)

    class Meta:
        model = Report
        fields = (
            "category",
            "building",
            "room_location",
            "title",
            "description",
            "requested_urgency",
        )
        widgets = {
            "room_location": forms.TextInput(attrs={"autocomplete": "off"}),
            "description": forms.Textarea(attrs={"rows": 5}),
        }

    def clean_photo(self):
        uploaded_file = self.cleaned_data.get("photo")
        if uploaded_file is None:
            return None
        return validate_and_reencode_photo(uploaded_file)


class VerificationForm(forms.Form):
    rating = forms.TypedChoiceField(
        choices=tuple((value, str(value)) for value in range(1, 6)),
        coerce=int,
    )
    comment = forms.CharField(required=False, max_length=2000, widget=forms.Textarea)
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)

    def __init__(self, *args, report, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["version"].initial = report.version


class ReopenReportForm(forms.Form):
    reason = forms.CharField(max_length=1000, widget=forms.Textarea)
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)

    def __init__(self, *args, report, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["version"].initial = report.version


class CommentForm(forms.Form):
    body = forms.CharField(max_length=2000, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, allow_internal=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.allow_internal = allow_internal
        if allow_internal:
            self.fields["is_internal"] = forms.BooleanField(
                required=False, label="Internal (officers and technicians only)"
            )

    def clean_is_internal(self):
        return self.cleaned_data.get("is_internal", False) if self.allow_internal else False


class CompletionForm(forms.Form):
    completion_notes = forms.CharField(
        max_length=2000, widget=forms.Textarea(attrs={"rows": 4})
    )
    photo = forms.FileField(required=False)
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)

    def __init__(self, *args, report, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["version"].initial = report.version

    def clean_photo(self):
        uploaded_file = self.cleaned_data.get("photo")
        if uploaded_file is None:
            return None
        return validate_and_reencode_photo(uploaded_file)
