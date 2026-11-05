from django import forms
from django.core.exceptions import ValidationError

from .models import Competency

MONTH_CHOICES = [
    (1, "Janeiro"), (2, "Fevereiro"), (3, "Março"), (4, "Abril"), (5, "Maio"), (6, "Junho"),
    (7, "Julho"), (8, "Agosto"), (9, "Setembro"), (10, "Outubro"), (11, "Novembro"), (12, "Dezembro"),
]


class CompetencyForm(forms.ModelForm):
    month = forms.TypedChoiceField(label="Mês", choices=MONTH_CHOICES, coerce=int)

    class Meta:
        model = Competency
        fields = ["year", "month", "cutoff_date"]
        labels = {"year": "Ano", "cutoff_date": "Data de corte (opcional)"}
        widgets = {
            "year": forms.NumberInput(attrs={"min": 2020, "max": 2100}),
            "cutoff_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, tenant, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        self.fields["year"].widget.attrs.update(min=2020, max=2100)

    def clean_year(self):
        year = self.cleaned_data["year"]
        if not 2020 <= year <= 2100:
            raise ValidationError("Informe um ano entre 2020 e 2100.")
        return year

    def clean(self):
        cleaned = super().clean()
        year, month = cleaned.get("year"), cleaned.get("month")
        if year and month and Competency.objects.filter(tenant=self.tenant, year=year, month=month).exists():
            raise ValidationError(f"A competência {month:02d}/{year} já existe.")
        return cleaned

    def save(self, commit=True):
        competency = super().save(commit=False)
        competency.tenant = self.tenant
        competency.status = "open"
        competency.closed_at = None
        if commit:
            competency.save()
        return competency
