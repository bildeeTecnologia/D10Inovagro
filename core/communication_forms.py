from django import forms

from .models import CommunicationMessage, CommunicationThread


class CommunicationThreadForm(forms.ModelForm):
    class Meta:
        model = CommunicationThread
        fields = ["title", "kind", "priority", "unit", "competency", "assigned_to", "due_at"]
        labels = {
            "title": "Título",
            "kind": "Tipo",
            "priority": "Prioridade",
            "unit": "Unidade",
            "competency": "Competência",
            "assigned_to": "Responsável",
            "due_at": "Prazo",
        }
        widgets = {"due_at": forms.DateTimeInput(attrs={"type": "datetime-local"})}


class CommunicationMessageForm(forms.ModelForm):
    class Meta:
        model = CommunicationMessage
        fields = ["body"]
        labels = {"body": "Mensagem"}
        widgets = {"body": forms.Textarea(attrs={"rows": 3, "placeholder": "Descreva a informação ou providência necessária"})}

    def clean_body(self):
        body = self.cleaned_data["body"].strip()
        if len(body) < 5:
            raise forms.ValidationError("Escreva uma mensagem com pelo menos 5 caracteres.")
        return body
