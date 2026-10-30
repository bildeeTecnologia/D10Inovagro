from django import forms

from .models import FieldEvent, UserScope


class UserScopeAdminForm(forms.ModelForm):
    class Meta:
        model = UserScope
        fields = "__all__"

    def clean(self):
        cleaned = super().clean()
        tenant = cleaned.get("tenant")
        company = cleaned.get("company")
        unit = cleaned.get("unit")
        role = cleaned.get("role")
        if role != "platform" and not unit:
            raise forms.ValidationError("Defina pelo menos uma unidade para este acesso. Para liberar várias unidades, cadastre uma linha por unidade.")
        if unit and tenant and unit.tenant_id != tenant.id:
            raise forms.ValidationError("A unidade precisa pertencer ao mesmo cliente do acesso.")
        if unit and company and unit.company_id != company.id:
            raise forms.ValidationError("A unidade precisa pertencer à empresa selecionada.")
        if unit and not company:
            cleaned["company"] = unit.company
        return cleaned


class FieldEventAdminForm(forms.ModelForm):
    change_reason = forms.CharField(
        label="Justificativa da correção",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Obrigatória ao alterar um evento pendente.",
    )

    class Meta:
        model = FieldEvent
        fields = "__all__"

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("event_type") == "rubric" and cleaned.get("application"):
            from .rubric_applications import validate_event_application
            tenant = cleaned.get("tenant") or self.instance.tenant
            if all(cleaned.get(key) is not None for key in ["unit", "collaborator", "event_date", "quantity"]):
                validate_event_application(
                    cleaned["application"], tenant, cleaned["unit"],
                    cleaned["collaborator"], cleaned["event_date"], cleaned["quantity"],
                )
            if self.instance.competency_id and cleaned.get("event_date"):
                event_date = cleaned["event_date"]
                if (event_date.year, event_date.month) != (self.instance.competency.year, self.instance.competency.month):
                    self.add_error("event_date", "Data fora da competência do evento.")
        if self.instance.pk and self.instance.status == "pending" and not cleaned.get("change_reason", "").strip():
            self.add_error("change_reason", "Informe o motivo da correção para preservar a trilha de auditoria.")
        return cleaned
