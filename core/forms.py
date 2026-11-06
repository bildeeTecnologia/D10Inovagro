from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q

from .models import EmploymentLink, FieldEvent, RubricApplication


class FieldEventForm(forms.ModelForm):
    class Meta:
        model = FieldEvent
        fields = ["unit", "collaborator", "event_type", "application", "event_date", "quantity", "reason"]
        labels = {
            "unit": "Unidade",
            "collaborator": "Colaborador",
            "event_type": "Tipo de evento",
            "application": "Regra de rubrica (somente Evento de rubrica configurada)",
            "event_date": "Data do evento",
            "quantity": "Quantidade",
            "reason": "Motivo",
        }
        widgets = {
            "event_date": forms.DateInput(attrs={"type": "date"}),
            "reason": forms.Textarea(attrs={"rows": 3, "placeholder": "Informe o motivo do lançamento"}),
            "quantity": forms.NumberInput(attrs={"step": "0.01", "min": "0.01"}),
        }

    def __init__(self, *args, released_types=None, require_leader_available=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.released_types = released_types
        self.require_leader_available = require_leader_available
        self.fields["unit"].empty_label = "Selecione a unidade"
        self.fields["collaborator"].empty_label = "Selecione o colaborador"
        choices = [item for item in FieldEvent.EVENT_CHOICES if released_types is None or item[0] == "rubric" or item[0] in released_types]
        self.fields["event_type"].choices = [("", "Selecione o tipo de evento")] + choices
        self.fields["application"].queryset = RubricApplication.objects.none()
        self.fields["application"].help_text = "Selecione uma regra aprovada da unidade. Eventos fixos aceitam uma ocorrência por data."

    def clean_reason(self):
        reason = self.cleaned_data["reason"].strip()
        if len(reason) < 5:
            raise ValidationError("Informe um motivo com pelo menos 5 caracteres.")
        return reason

    def clean(self):
        cleaned = super().clean()
        unit = cleaned.get("unit")
        collaborator = cleaned.get("collaborator")
        event_date = cleaned.get("event_date")
        application = cleaned.get("application")
        if unit and event_date:
            competency = unit.tenant.competencies.filter(status__in=["open", "review"]).order_by("-year", "-month").first()
            if competency and (event_date.year, event_date.month) != (competency.year, competency.month):
                self.add_error("event_date", "A data deve pertencer à competência aberta; lançamentos atrasados precisam de regularização pelo DP.")
        event_type = cleaned.get("event_type")
        if self.released_types is not None and event_type and event_type != "rubric" and event_type not in self.released_types:
            self.add_error("event_type", "Este tipo de evento não está liberado para lançamento pelos líderes.")
        if cleaned.get("event_type") == "rubric":
            if not application:
                self.add_error("application", "Escolha a regra da rubrica.")
            elif unit and collaborator and event_date and cleaned.get("quantity") is not None:
                from .rubric_applications import validate_event_application
                try:
                    validate_event_application(
                        application, unit.tenant, unit, collaborator, event_date, cleaned["quantity"],
                        require_leader_available=self.require_leader_available,
                    )
                except ValidationError as exc:
                    self.add_error("application", exc)
        elif application:
            self.add_error("application", "Esta regra só se aplica ao tipo Evento de rubrica configurada.")
        if unit and collaborator and event_date and not EmploymentLink.objects.filter(
            collaborator=collaborator,
            unit=unit,
            company=unit.company,
            admission_date__lte=event_date,
        ).filter(Q(termination_date__isnull=True) | Q(termination_date__gte=event_date)).exists():
            self.add_error("collaborator", "O colaborador não possui vínculo ativo com esta unidade na data informada.")
        return cleaned
