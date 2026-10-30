from django import forms
from django.core.exceptions import ValidationError

from .models import AdmissionFieldDefinition, AdmissionRequest, Company, Unit
from .roster_importer import digits, valid_cpf


class AdmissionConversionForm(forms.Form):
    full_name = forms.CharField(label="Nome completo conferido", max_length=160)
    cpf = forms.CharField(label="CPF conferido", max_length=14)
    employee_code = forms.CharField(label="Matrícula no vínculo", max_length=80, required=False)
    job_title = forms.CharField(label="Cargo ou função", max_length=160)
    admission_date = forms.DateField(label="Data de admissão", widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}))
    reason = forms.CharField(label="Justificativa da conversão", max_length=1000, widget=forms.Textarea(attrs={"rows": 3}))
    confirmed = forms.BooleanField(label="Conferi a identidade, a empresa, a unidade e os dados do vínculo.")

    def clean_cpf(self):
        cpf = digits(self.cleaned_data["cpf"])
        if len(cpf) != 11 or not valid_cpf(cpf):
            raise ValidationError("Informe um CPF válido com 11 dígitos.")
        return cpf


class AdmissionRequestForm(forms.ModelForm):
    class Meta:
        model = AdmissionRequest
        fields = ["company", "unit", "candidate_name", "candidate_phone", "job_title", "expected_admission_date"]
        labels = {"company": "Empresa/CNPJ", "unit": "Unidade", "candidate_name": "Nome do candidato", "candidate_phone": "Telefone", "job_title": "Cargo ou função", "expected_admission_date": "Data prevista de admissão"}
        widgets = {"expected_admission_date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        if tenant:
            self.fields["company"].queryset = Company.objects.filter(tenant=tenant, active=True)
            self.fields["unit"].queryset = Unit.objects.filter(tenant=tenant, active=True).select_related("company")
        self.fields["company"].empty_label = "Selecione a empresa"
        self.fields["unit"].empty_label = "Selecione a unidade"

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("company") and cleaned.get("unit") and cleaned["unit"].company_id != cleaned["company"].id:
            raise ValidationError("A unidade selecionada não pertence à empresa informada.")
        return cleaned


class AdmissionReviewForm(forms.ModelForm):
    class Meta:
        model = AdmissionRequest
        fields = ["company", "unit", "candidate_name", "candidate_phone", "job_title", "expected_admission_date", "expires_at"]
        labels = {"company": "Empresa/CNPJ", "unit": "Unidade", "candidate_name": "Nome do candidato", "candidate_phone": "Telefone", "job_title": "Cargo ou função", "expected_admission_date": "Data prevista de admissão", "expires_at": "Validade do link"}
        widgets = {"expected_admission_date": forms.DateInput(attrs={"type": "date"}), "expires_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M")}

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        if tenant:
            self.fields["company"].queryset = Company.objects.filter(tenant=tenant, active=True)
            self.fields["unit"].queryset = Unit.objects.filter(tenant=tenant, active=True).select_related("company")

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("company") and cleaned.get("unit") and cleaned["unit"].company_id != cleaned["company"].id:
            raise ValidationError("A unidade selecionada não pertence à empresa informada.")
        return cleaned


class AdmissionAccessForm(forms.Form):
    chave = forms.CharField(label="Chave de acesso", max_length=8, min_length=8, widget=forms.TextInput(attrs={"autocomplete": "one-time-code", "placeholder": "Informe a chave recebida pelo RH"}))


def build_public_form(request, fields, data=None):
    form = forms.Form(data=data)
    for field in fields:
        kwargs = {"label": field.label, "required": field.required, "help_text": field.help_text}
        if field.field_type == "long_text":
            kwargs["widget"] = forms.Textarea(attrs={"rows": 3})
            form.fields[field.code] = forms.CharField(**kwargs)
        elif field.field_type == "date":
            kwargs["widget"] = forms.DateInput(attrs={"type": "date"})
            form.fields[field.code] = forms.DateField(**kwargs)
        elif field.field_type == "email":
            form.fields[field.code] = forms.EmailField(**kwargs)
        elif field.field_type == "phone":
            form.fields[field.code] = forms.CharField(**kwargs)
        elif field.field_type == "boolean":
            form.fields[field.code] = forms.BooleanField(**kwargs)
        elif field.field_type == "choice":
            form.fields[field.code] = forms.ChoiceField(choices=[("", "Selecione")] + [(choice, choice) for choice in field.choices], **kwargs)
        else:
            form.fields[field.code] = forms.CharField(**kwargs)
    return form
