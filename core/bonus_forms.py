import re
import unicodedata

from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import AuditLog, Rubric, RubricApplication
from .rubric_applications import approve_application


def _slug_code(name):
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^A-Z0-9]+", "_", ascii_name.upper()).strip("_")[:50] or "BONIFICACAO"


class BonusForm(forms.Form):
    """Cria, em uma só etapa, a rubrica e a regra de aplicação de uma bonificação por ocorrência."""
    MODE_CHOICES = [
        ("event", "Uma ocorrência por lançamento (cada lançamento gera um pagamento)"),
        ("cumulative", "Cumulativa (soma cada meta atingida e paga o total do mês)"),
    ]
    CYCLE_CHOICES = [("day10", "Pagamento do dia 10 (mês seguinte)"), ("monthly", "Folha mensal")]

    name = forms.CharField(label="Nome da bonificação", max_length=180)
    mode = forms.ChoiceField(label="Como é lançada", choices=MODE_CHOICES)
    amount = forms.DecimalField(label="Valor por ocorrência (R$)", min_value=0, decimal_places=2, max_digits=12)
    cycle_type = forms.ChoiceField(label="Quando é paga", choices=CYCLE_CHOICES)
    units = forms.ModelMultipleChoiceField(label="Unidades", queryset=None, widget=forms.CheckboxSelectMultiple)
    effective_from = forms.DateField(label="Início", widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}))
    effective_to = forms.DateField(label="Fim (opcional)", required=False, widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}))
    leader_available = forms.BooleanField(label="Liberar para o líder lançar no app", required=False, initial=True)
    instructions = forms.CharField(
        label="Orientação para o líder e para o DP", widget=forms.Textarea(attrs={"rows": 2}),
        help_text="Quando lançar e qual critério o DP usa para aprovar.",
    )
    reason = forms.CharField(label="Justificativa", min_length=5)
    approve_now = forms.BooleanField(
        label="Aprovar agora (sem aprovação a regra fica em rascunho e não gera valores)", required=False, initial=True,
    )

    def __init__(self, *args, tenant, units, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        self.fields["units"].queryset = units
        self.initial.setdefault("effective_from", timezone.localdate())

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount <= 0:
            raise ValidationError("Informe um valor maior que zero.")
        return amount

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if Rubric.objects.filter(tenant=self.tenant, name__iexact=name).exists():
            raise ValidationError("Já existe uma rubrica com este nome. Edite a regra existente ou use outro nome.")
        return name

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("effective_from"), cleaned.get("effective_to")
        if start and end and end < start:
            self.add_error("effective_to", "O fim da vigência não pode ser anterior ao início.")
        return cleaned

    def _unique_code(self, name):
        base = _slug_code(name)
        code, suffix = base, 2
        while Rubric.objects.filter(tenant=self.tenant, code__iexact=code).exists():
            code, suffix = f"{base[:46]}_{suffix}", suffix + 1
        return code

    @transaction.atomic
    def save(self, user, rubric_snapshot):
        data = self.cleaned_data
        rubric = Rubric.objects.create(
            tenant=self.tenant, code=self._unique_code(data["name"]), name=data["name"], category="earning",
            cycle_type=data["cycle_type"], active=True, effective_from=data["effective_from"],
            effective_to=data["effective_to"], description=data["instructions"], created_by=user,
        )
        AuditLog.objects.create(
            tenant=self.tenant, user=user, action="create", entity="rubric", entity_id=str(rubric.pk),
            after=rubric_snapshot(rubric), reason=data["reason"],
        )
        applications = []
        for unit in data["units"]:
            application = RubricApplication(
                tenant=self.tenant, rubric=rubric, unit=unit, mode=data["mode"], amount=data["amount"],
                cycle_type=data["cycle_type"], leader_available=data["leader_available"],
                effective_from=data["effective_from"], effective_to=data["effective_to"],
                instructions=data["instructions"], created_by=user,
            )
            application.full_clean()
            application.save()
            AuditLog.objects.create(
                tenant=self.tenant, user=user, action="create", entity="rubric_application", entity_id=str(application.pk),
                after={
                    key: str(getattr(application, key))
                    for key in ("rubric_id", "unit_id", "mode", "amount", "cycle_type", "leader_available", "effective_from", "effective_to")
                },
                reason=data["reason"],
            )
            if data["approve_now"]:
                approve_application(application, user, data["reason"])
            applications.append(application)
        return rubric, applications
