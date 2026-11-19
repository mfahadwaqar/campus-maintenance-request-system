from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError

from accounts.models import Building
from accounts.room_validation import validate_room_location
from .models import Category, Report, Subcategory
from .photo_pipeline import validate_and_reencode_photo


class ReportSubmissionForm(forms.ModelForm):
    requested_urgency = forms.ChoiceField(choices=settings.REQUESTED_URGENCY_CHOICES)
    photo = forms.FileField(required=False)
    room_location = forms.CharField(
        label="Dorm room or Student Village room",
        max_length=100,
        help_text="Use a dorm code such as A101 or a provisional village code such as SV04A1.",
    )
    room_verified = forms.BooleanField(
        required=True,
        label="I confirm the selected building and room are correct",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = Category.objects.filter(is_active=True)
        self.fields["building"].queryset = Building.objects.filter(is_active=True)
        self.fields["subcategory"].queryset = Subcategory.objects.filter(is_active=True)

    def clean(self):
        cleaned_data = super().clean()
        building = cleaned_data.get("building")
        room_location = cleaned_data.get("room_location")
        if building and room_location:
            try:
                cleaned_data["room_location"] = validate_room_location(
                    building, room_location
                )
            except ValidationError as exc:
                self.add_error("room_location", exc)
        subcategory = cleaned_data.get("subcategory")
        category = cleaned_data.get("category")
        if subcategory and category and subcategory.category_id != category.pk:
            self.add_error("subcategory", "Choose a subcategory within the selected category.")
        return cleaned_data

    class Meta:
        model = Report
        fields = (
            "category",
            "subcategory",
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
        required=False,
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


class CompletionForm(forms.Form):
    completion_notes = forms.CharField(
        max_length=2000, widget=forms.Textarea(attrs={"rows": 4})
    )
    photo = forms.FileField(required=False)
    requester_signed_on_site = forms.BooleanField(
        required=False,
        label="Resident signed on paper at the site",
    )
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)

    def __init__(self, *args, report, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["version"].initial = report.version

    def clean_photo(self):
        uploaded_file = self.cleaned_data.get("photo")
        if uploaded_file is None:
            return None
        return validate_and_reencode_photo(uploaded_file)


class HoldForm(forms.Form):
    reason = forms.CharField(max_length=400, widget=forms.Textarea(attrs={"rows": 3}))
    expected_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)

    def __init__(self, *args, report, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["version"].initial = report.version
