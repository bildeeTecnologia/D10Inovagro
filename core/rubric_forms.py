import re

from django import forms
from django.utils import timezone

from .models import Rubric
from .payments import DEFAULT_RUBRIC_DEFINITIONS


class RubricForm(forms.ModelForm):
    change_reason = forms.CharField(
        label="Justificativa",
        min_length=5,
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text="Explique o cadastro ou a alteração. A justificativa ficará na auditoria.",
    )

    class Meta:
        model = Rubric
        fields = [
            "code", "name", "category", "active", "cycle_type",
            "effective_from", "effective_to", "description",
        ]
        labels = {
            "code": "Código",
            "name": "Descrição / nome da rubrica",
            "category": "Tipo",
            "active": "Ativa no catálogo",
            "cycle_type": "Ciclo previsto",
            "effective_from": "Início da vigência",
            "effective_to": "Fim da vigência",
            "description": "Orientações de uso",
        }
        help_texts = {
            "code": "Identificador interno único por cliente. Exemplo: FROTA_LIMPEZA.",
            "active": "Situação cadastral; não publica fórmula nem autoriza pagamento.",
            "cycle_type": "Classificação prevista. Não muda o encaminhamento automático dos cálculos existentes.",
            "description": "Registre quando usar, quem aprova e quais definições do DP ainda estão pendentes.",
        }
        widgets = {
            "effective_from": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "effective_to": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, tenant, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        self.instance.tenant = tenant
        self.protected = bool(self.instance.pk) and (
            self.instance.code in {item[0] for item in DEFAULT_RUBRIC_DEFINITIONS}
            or self.instance.payment_entries.exists()
            or self.instance.applications.exists()
        )
        if self.instance.pk:
            self.fields["code"].disabled = True
        else:
            self.initial["active"] = False
            self.initial["cycle_type"] = "none"
            self.initial["effective_from"] = timezone.localdate()
        if self.protected:
            for name in self.Meta.fields:
                if name != "description":
                    self.fields[name].disabled = True

    def clean_code(self):
        code = self.cleaned_data["code"].strip().upper()
        if self.instance.pk:
            return self.instance.code
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9_]*", code):
            raise forms.ValidationError("Use letras sem acento, números e sublinhado, sem espaços.")
        if code in {item[0] for item in DEFAULT_RUBRIC_DEFINITIONS}:
            raise forms.ValidationError("Código reservado à geração de pagamentos do sistema.")
        if Rubric.objects.filter(tenant=self.tenant, code__iexact=code).exists():
            raise forms.ValidationError("Já existe uma rubrica com este código neste cliente.")
        return code

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("effective_from")
        end = cleaned.get("effective_to")
        if start and end and end < start:
            self.add_error("effective_to", "O fim da vigência não pode ser anterior ao início.")
        if cleaned.get("category") == "informative" and cleaned.get("cycle_type") != "none":
            self.add_error("cycle_type", "Rubrica informativa deve usar Sem pagamento / a definir.")
        return cleaned
