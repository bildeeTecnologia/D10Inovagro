from django import forms
from django.db.models import Q

from .models import CollaboratorRubric, Rubric, RubricApplication
from .payments import DEFAULT_RUBRIC_DEFINITIONS


class ApplicationForm(forms.ModelForm):
    reason = forms.CharField(label="Justificativa", min_length=5)

    class Meta:
        model = RubricApplication
        fields = [
            "rubric", "unit", "mode", "amount", "cycle_type", "leader_available",
            "effective_from", "effective_to", "instructions",
        ]
        labels = {
            "rubric": "Rubrica", "unit": "Unidade", "mode": "Modalidade",
            "amount": "Valor fixo (R$)", "cycle_type": "Ciclo efetivo",
            "leader_available": "Disponível para lançamento no campo",
            "effective_from": "Início", "effective_to": "Fim (opcional)",
            "instructions": "Critérios de uso e aprovação",
        }
        widgets = {
            "effective_from": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "effective_to": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "instructions": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, tenant, units, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.tenant = tenant
        self.fields["unit"].queryset = units
        self.fields["rubric"].queryset = Rubric.objects.filter(tenant=tenant, active=True).exclude(
            code__in=[item[0] for item in DEFAULT_RUBRIC_DEFINITIONS],
        ).filter(Q(category="earning") | Q(category="informative"))


class AgreementForm(forms.ModelForm):
    reason = forms.CharField(label="Justificativa", min_length=5)

    class Meta:
        model = CollaboratorRubric
        fields = ["application", "collaborator", "effective_from", "effective_to", "reference", "expected_amount"]
        labels = {
            "application": "Regra aprovada", "collaborator": "Colaborador",
            "effective_from": "Início", "effective_to": "Fim (vazio = indeterminado)",
            "reference": "Referência do acordo/documento (sem dados sensíveis)",
            "expected_amount": "Valor esperado para conferência (opcional)",
        }
        widgets = {
            "effective_from": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "effective_to": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
        }

    def __init__(self, *args, tenant, units, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.tenant = tenant
        self.fields["application"].queryset = RubricApplication.objects.filter(
            tenant=tenant, unit__in=units, status="approved", mode__in=["recurring", "informative"],
        ).select_related("rubric", "unit")
        self.fields["collaborator"].queryset = tenant.collaborators.filter(
            links__unit__in=units,
        ).distinct()


class AgreementEndForm(forms.Form):
    effective_to = forms.DateField(label="Último dia de vigência", widget=forms.DateInput(attrs={"type": "date"}))
    reason = forms.CharField(label="Justificativa", min_length=5)
