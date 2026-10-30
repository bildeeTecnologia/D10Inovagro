from django import forms


class ImportWorkbookForm(forms.Form):
    file = forms.FileField(label="Arquivo XLSX ou PDF", help_text="A prévia não grava nem confirma dados financeiros.")
    sheet_name = forms.CharField(label="Aba (somente XLSX)", required=False, help_text="Opcional. Para XLSX, se vazio, será usada a primeira aba.")

    def clean_file(self):
        uploaded = self.cleaned_data["file"]
        if not uploaded.name.lower().endswith((".xlsx", ".pdf")):
            raise forms.ValidationError("Envie um arquivo XLSX ou PDF.")
        if uploaded.size > 15 * 1024 * 1024:
            raise forms.ValidationError("O arquivo não pode ultrapassar 15 MB.")
        return uploaded

    def clean(self):
        cleaned = super().clean()
        uploaded = cleaned.get("file")
        sheet_name = cleaned.get("sheet_name")
        if uploaded and uploaded.name.lower().endswith(".pdf") and sheet_name:
            self.add_error("sheet_name", "A seleção de aba só se aplica a arquivos XLSX.")
        return cleaned


class RosterImportForm(forms.Form):
    file = forms.FileField(label="Arquivo XLSX", help_text="A prévia não grava cadastros. A confirmação é uma ação separada.")

    def clean_file(self):
        uploaded = self.cleaned_data["file"]
        if not uploaded.name.lower().endswith(".xlsx"):
            raise forms.ValidationError("Envie um arquivo XLSX.")
        if uploaded.size > 15 * 1024 * 1024:
            raise forms.ValidationError("O arquivo não pode ultrapassar 15 MB.")
        return uploaded
