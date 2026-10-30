import uuid

from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Tenant(TimeStampedModel):
    name = models.CharField(max_length=160)
    slug = models.SlugField(unique=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Company(TimeStampedModel):
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="companies")
    legal_name = models.CharField(max_length=200)
    cnpj = models.CharField(max_length=18)
    accounting_office = models.CharField(max_length=200, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["legal_name"]
        constraints = [models.UniqueConstraint(fields=["tenant", "cnpj"], name="unique_company_cnpj_per_tenant")]

    def __str__(self):
        return f"{self.legal_name} ({self.cnpj})"


class Unit(TimeStampedModel):
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="units")
    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="units")
    name = models.CharField(max_length=160)
    region = models.CharField(max_length=120, blank=True)
    final_customer = models.CharField(max_length=200, blank=True)
    leaders = models.ManyToManyField(User, blank=True, related_name="field_units")
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["tenant", "company", "name"], name="unique_unit_per_company")]

    def clean(self):
        super().clean()
        if self.tenant_id and self.company_id:
            company_tenant_id = Company.objects.filter(pk=self.company_id).values_list("tenant_id", flat=True).first()
            if company_tenant_id is not None and company_tenant_id != self.tenant_id:
                raise ValidationError({"company": "A empresa da unidade deve pertencer ao mesmo cliente."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class UserScope(TimeStampedModel):
    ROLE_CHOICES = [
        ("dp", "Analista de DP"),
        ("leader", "Líder de unidade"),
        ("management", "Direção"),
        ("finance", "Financeiro"),
        ("accountant", "Contador externo"),
        ("platform", "Administrador da plataforma"),
    ]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="scopes")
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="user_scopes")
    company = models.ForeignKey(Company, null=True, blank=True, on_delete=models.CASCADE)
    unit = models.ForeignKey(Unit, null=True, blank=True, on_delete=models.CASCADE)
    role = models.CharField(max_length=30, choices=ROLE_CHOICES)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "tenant", "company", "unit", "role"], name="unique_user_scope")]

    def __str__(self):
        return f"{self.user} — {self.get_role_display()} — {self.tenant}"


class Competency(TimeStampedModel):
    STATUS_CHOICES = [("open", "Aberta"), ("review", "Em conferência"), ("closed", "Fechada")]
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="competencies")
    year = models.PositiveSmallIntegerField()
    month = models.PositiveSmallIntegerField(validators=[MinValueValidator(1)])
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="open")
    cutoff_date = models.DateField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-year", "-month"]
        constraints = [models.UniqueConstraint(fields=["tenant", "year", "month"], name="unique_competency_per_tenant")]

    def __str__(self):
        return f"{self.month:02d}/{self.year} — {self.get_status_display()}"

    def close(self):
        self.status = "closed"
        self.closed_at = timezone.now()
        self.save(update_fields=["status", "closed_at", "updated_at"])


class PaymentCycle(TimeStampedModel):
    CYCLE_CHOICES = [("monthly", "Folha mensal"), ("day10", "Pagamento do dia 10")]
    STATUS_CHOICES = [("draft", "Rascunho"), ("review", "Em conferência"), ("approved", "Aprovado"), ("closed", "Fechado")]
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="payment_cycles")
    competency = models.ForeignKey(Competency, on_delete=models.PROTECT, related_name="payment_cycles")
    cycle_type = models.CharField(max_length=20, choices=CYCLE_CHOICES)
    payment_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    cutoff_date = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="created_payment_cycles")
    approved_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT, related_name="approved_payment_cycles")
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-competency__year", "-competency__month", "cycle_type"]
        constraints = [models.UniqueConstraint(fields=["competency", "cycle_type"], name="unique_payment_cycle_per_competency")]

    def __str__(self):
        return f"{self.get_cycle_type_display()} — {self.competency}"


class Rubric(TimeStampedModel):
    CATEGORY_CHOICES = [("earning", "Provento"), ("deduction", "Desconto"), ("informative", "Informativa")]
    CYCLE_CHOICES = [("monthly", "Folha mensal"), ("day10", "Pagamento do dia 10"), ("both", "Ambos"), ("none", "Sem pagamento / a definir")]
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="rubrics")
    code = models.CharField(max_length=60)
    name = models.CharField(max_length=180)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    cycle_type = models.CharField(max_length=20, choices=CYCLE_CHOICES)
    active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="created_rubrics")

    class Meta:
        ordering = ["code", "-version"]
        constraints = [models.UniqueConstraint(fields=["tenant", "code", "version"], name="unique_rubric_version_per_tenant")]

    def __str__(self):
        return f"{self.code} v{self.version} — {self.name}"


class Collaborator(TimeStampedModel):
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="collaborators")
    name = models.CharField(max_length=160)
    employee_code = models.CharField(max_length=80, blank=True)
    cpf_fingerprint = models.CharField(max_length=64, blank=True, editable=False)
    cpf_masked = models.CharField(max_length=14, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "employee_code"], condition=~models.Q(employee_code=""), name="unique_employee_code_per_tenant"),
            models.UniqueConstraint(fields=["tenant", "cpf_fingerprint"], condition=~models.Q(cpf_fingerprint=""), name="unique_collaborator_cpf_fingerprint_per_tenant"),
        ]

    def __str__(self):
        return self.name


class EmploymentLink(TimeStampedModel):
    collaborator = models.ForeignKey(Collaborator, on_delete=models.PROTECT, related_name="links")
    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="employment_links")
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="employment_links")
    employee_code = models.CharField(max_length=80, blank=True)
    job_title = models.CharField(max_length=160)
    admission_date = models.DateField()
    termination_date = models.DateField(null=True, blank=True)
    monthly_salary = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    def clean(self):
        super().clean()
        errors = {}
        company = Company.objects.filter(pk=self.company_id).values("tenant_id").first() if self.company_id else None
        unit = Unit.objects.filter(pk=self.unit_id).values("tenant_id", "company_id").first() if self.unit_id else None
        collaborator_tenant_id = (
            Collaborator.objects.filter(pk=self.collaborator_id).values_list("tenant_id", flat=True).first()
            if self.collaborator_id else None
        )
        if company and unit and unit["company_id"] != self.company_id:
            errors["unit"] = "A unidade deve pertencer à empresa do vínculo."
        if company and collaborator_tenant_id is not None and company["tenant_id"] != collaborator_tenant_id:
            errors["collaborator"] = "O colaborador e a empresa devem pertencer ao mesmo cliente."
        if unit and collaborator_tenant_id is not None and unit["tenant_id"] != collaborator_tenant_id:
            errors.setdefault("unit", "O colaborador e a unidade devem pertencer ao mesmo cliente.")
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.collaborator} — {self.job_title}"


class AdmissionFieldDefinition(TimeStampedModel):
    FIELD_TYPES = [("text", "Texto"), ("long_text", "Texto longo"), ("date", "Data"), ("phone", "Telefone"), ("email", "E-mail"), ("boolean", "Sim/Não"), ("choice", "Lista de opções")]
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="admission_fields")
    company = models.ForeignKey(Company, null=True, blank=True, on_delete=models.PROTECT, related_name="admission_fields")
    unit = models.ForeignKey(Unit, null=True, blank=True, on_delete=models.PROTECT, related_name="admission_fields")
    code = models.SlugField(max_length=80)
    label = models.CharField(max_length=160)
    section = models.CharField(max_length=80, default="Dados básicos")
    field_type = models.CharField(max_length=20, choices=FIELD_TYPES, default="text")
    required = models.BooleanField(default=False)
    help_text = models.CharField(max_length=240, blank=True)
    choices = models.JSONField(default=list, blank=True)
    sort_order = models.PositiveIntegerField(default=10)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["section", "sort_order", "label"]
        constraints = [models.UniqueConstraint(fields=["tenant", "code"], name="unique_admission_field_per_tenant")]

    def __str__(self):
        return self.label


class AdmissionRequest(TimeStampedModel):
    STATUS_CHOICES = [("draft", "Rascunho"), ("in_progress", "Em preenchimento"), ("submitted", "Enviado pelo candidato"), ("returned", "Devolvido para correção"), ("approved", "Aprovado"), ("cancelled", "Cancelado"), ("expired", "Expirado")]
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="admission_requests")
    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="admission_requests")
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="admission_requests")
    candidate_name = models.CharField(max_length=160)
    candidate_phone = models.CharField(max_length=30)
    job_title = models.CharField(max_length=160, blank=True)
    expected_admission_date = models.DateField(null=True, blank=True)
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    access_key_hash = models.CharField(max_length=128)
    access_key_hint = models.CharField(max_length=8)
    expires_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT, related_name="reviewed_admissions")
    review_note = models.TextField(blank=True)
    converted_link = models.OneToOneField(EmploymentLink, null=True, blank=True, editable=False, on_delete=models.PROTECT, related_name="source_admission")
    converted_at = models.DateTimeField(null=True, blank=True, editable=False)
    converted_by = models.ForeignKey(User, null=True, blank=True, editable=False, on_delete=models.PROTECT, related_name="converted_admissions")
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="created_admissions")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.candidate_name} — {self.get_status_display()}"


class AdmissionFieldValue(TimeStampedModel):
    request = models.ForeignKey(AdmissionRequest, on_delete=models.CASCADE, related_name="field_values")
    field = models.ForeignKey(AdmissionFieldDefinition, on_delete=models.PROTECT, related_name="values")
    value = models.JSONField(default=dict, blank=True)
    changed_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT, related_name="changed_admission_values")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["request", "field"], name="unique_admission_value")]


class CompensationVersion(TimeStampedModel):
    collaborator = models.ForeignKey(Collaborator, on_delete=models.PROTECT, related_name="compensation_versions")
    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="compensation_versions")
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="compensation_versions")
    combined_salary = models.DecimalField(max_digits=12, decimal_places=2)
    clt_salary = models.DecimalField(max_digits=12, decimal_places=2)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    reason = models.TextField()
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="created_compensation_versions")

    def clean(self):
        super().clean()
        errors = {}
        company = Company.objects.filter(pk=self.company_id).values("tenant_id").first() if self.company_id else None
        unit = Unit.objects.filter(pk=self.unit_id).values("tenant_id", "company_id").first() if self.unit_id else None
        collaborator_tenant_id = (
            Collaborator.objects.filter(pk=self.collaborator_id).values_list("tenant_id", flat=True).first()
            if self.collaborator_id else None
        )
        if company and unit and unit["company_id"] != self.company_id:
            errors["unit"] = "A unidade deve pertencer à empresa da versão salarial."
        if company and collaborator_tenant_id is not None and company["tenant_id"] != collaborator_tenant_id:
            errors["collaborator"] = "O colaborador e a empresa devem pertencer ao mesmo cliente."
        if unit and collaborator_tenant_id is not None and unit["tenant_id"] != collaborator_tenant_id:
            errors.setdefault("unit", "O colaborador e a unidade devem pertencer ao mesmo cliente.")
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    class Meta:
        ordering = ["collaborator__name", "-effective_from", "-created_at"]
        indexes = [models.Index(fields=["collaborator", "unit", "effective_from", "effective_to"])]

    def __str__(self):
        return f"{self.collaborator} — combinado R$ {self.combined_salary} / CLT R$ {self.clt_salary}"


class FieldEvent(TimeStampedModel):
    EVENT_CHOICES = [
        ("additional_12h", "Adicional 12h"),
        ("rain_release", "Dispensa por chuva"),
        ("overtime", "Hora extra"),
        ("daily", "Diária"),
        ("sunday", "Domingo"),
        ("holiday", "Feriado"),
        ("occurrence", "Ocorrência"),
        ("advance", "Adiantamento"),
        ("rubric", "Evento de rubrica configurada"),
    ]
    STATUS_CHOICES = [("draft", "Rascunho"), ("pending", "Pendente"), ("approved", "Aprovado"), ("rejected", "Rejeitado")]
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="events")
    competency = models.ForeignKey(Competency, on_delete=models.PROTECT, related_name="events")
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="events")
    collaborator = models.ForeignKey(Collaborator, on_delete=models.PROTECT, related_name="events")
    event_type = models.CharField(max_length=30, choices=EVENT_CHOICES)
    application = models.ForeignKey("RubricApplication", null=True, blank=True, on_delete=models.PROTECT, related_name="events")
    event_date = models.DateField()
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    idempotency_key = models.UUIDField(unique=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="created_field_events")
    approved_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT, related_name="approved_field_events")
    sync_received_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-event_date", "-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["collaborator", "event_type", "event_date"], condition=~models.Q(event_type="rubric"), name="unique_event_per_collaborator_date_type"),
            models.UniqueConstraint(fields=["collaborator", "application", "event_date"], condition=models.Q(event_type="rubric"), name="unique_rubric_event_per_date"),
            models.CheckConstraint(condition=(models.Q(event_type="rubric", application__isnull=False) | (~models.Q(event_type="rubric") & models.Q(application__isnull=True))), name="event_application_type"),
        ]

    def get_event_type_display(self):
        if self.application_id:
            return self.application.rubric.name
        return dict(self.EVENT_CHOICES).get(self.event_type, self.event_type)

    def __str__(self):
        return f"{self.get_event_type_display()} — {self.collaborator} — {self.event_date:%d/%m/%Y}"


class AuditLog(models.Model):
    ACTION_CHOICES = [("create", "Criação"), ("update", "Alteração"), ("approve", "Aprovação"), ("close", "Fechamento"), ("export", "Exportação"), ("access", "Acesso")]
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="audit_logs")
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT)
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    entity = models.CharField(max_length=120)
    entity_id = models.CharField(max_length=80)
    before = models.JSONField(default=dict, blank=True)
    after = models.JSONField(default=dict, blank=True)
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_action_display()} — {self.entity}#{self.entity_id}"


class CalculationRule(TimeStampedModel):
    STATUS_CHOICES = [("draft", "Rascunho"), ("review", "Em revisão"), ("published", "Publicada"), ("suspended", "Suspensa")]
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="calculation_rules")
    company = models.ForeignKey(Company, null=True, blank=True, on_delete=models.PROTECT, related_name="calculation_rules")
    unit = models.ForeignKey(Unit, null=True, blank=True, on_delete=models.PROTECT, related_name="calculation_rules")
    code = models.CharField(max_length=80)
    name = models.CharField(max_length=180)
    event_type = models.CharField(max_length=30, choices=[item for item in FieldEvent.EVENT_CHOICES if item[0] != "rubric"])
    version = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    parameters = models.JSONField(default=dict)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    legal_reference = models.CharField(max_length=255, blank=True)
    approval_reason = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="created_calculation_rules")
    approved_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT, related_name="approved_calculation_rules")
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["code", "-version"]
        constraints = [models.UniqueConstraint(fields=["tenant", "code", "version"], name="unique_rule_version_per_tenant")]
        indexes = [models.Index(fields=["tenant", "event_type", "status"]), models.Index(fields=["tenant", "effective_from", "effective_to"])]

    def __str__(self):
        return f"{self.code} v{self.version} — {self.name}"


class CalculationResult(TimeStampedModel):
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="calculation_results")
    competency = models.ForeignKey(Competency, on_delete=models.PROTECT, related_name="calculation_results")
    event = models.OneToOneField(FieldEvent, on_delete=models.PROTECT, related_name="calculation_result")
    collaborator = models.ForeignKey(Collaborator, on_delete=models.PROTECT, related_name="calculation_results")
    rule = models.ForeignKey(CalculationRule, on_delete=models.PROTECT, related_name="calculation_results")
    base_amount = models.DecimalField(max_digits=12, decimal_places=2)
    factor = models.DecimalField(max_digits=8, decimal_places=4)
    calculated_amount = models.DecimalField(max_digits=12, decimal_places=2)
    memory = models.JSONField(default=dict)

    class Meta:
        ordering = ["collaborator__name", "event__event_date"]

    def __str__(self):
        return f"{self.collaborator} — R$ {self.calculated_amount} — {self.rule.code} v{self.rule.version}"


class MonthlyCompensationResult(TimeStampedModel):
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="monthly_compensation_results")
    competency = models.ForeignKey(Competency, on_delete=models.PROTECT, related_name="monthly_compensation_results")
    collaborator = models.ForeignKey(Collaborator, on_delete=models.PROTECT, related_name="monthly_compensation_results")
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="monthly_compensation_results")
    compensation = models.ForeignKey(CompensationVersion, on_delete=models.PROTECT, related_name="monthly_results")
    normal_days = models.PositiveSmallIntegerField()
    rain_days = models.PositiveSmallIntegerField()
    combined_daily = models.DecimalField(max_digits=12, decimal_places=6)
    clt_daily = models.DecimalField(max_digits=12, decimal_places=6)
    normal_amount = models.DecimalField(max_digits=12, decimal_places=2)
    rain_amount = models.DecimalField(max_digits=12, decimal_places=2)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_cycle = models.CharField(max_length=30, default="monthly")
    memory = models.JSONField(default=dict)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["competency", "collaborator", "unit"], name="unique_monthly_compensation_result")]
        ordering = ["collaborator__name", "unit__name"]

    def __str__(self):
        return f"{self.collaborator} — {self.competency} — R$ {self.total_amount}"


class PaymentEntry(TimeStampedModel):
    STATUS_CHOICES = [("draft", "Rascunho"), ("review", "Em conferência"), ("approved", "Aprovado"), ("exported", "Exportado")]
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="payment_entries")
    cycle = models.ForeignKey(PaymentCycle, on_delete=models.PROTECT, related_name="entries")
    collaborator = models.ForeignKey(Collaborator, on_delete=models.PROTECT, related_name="payment_entries")
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="payment_entries")
    rubric = models.ForeignKey(Rubric, on_delete=models.PROTECT, related_name="payment_entries")
    source_event = models.ForeignKey(FieldEvent, null=True, blank=True, on_delete=models.PROTECT, related_name="payment_entries")
    source_agreement = models.ForeignKey("CollaboratorRubric", null=True, blank=True, on_delete=models.PROTECT, related_name="payment_entries")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    memory = models.JSONField(default=dict)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="created_payment_entries")

    class Meta:
        ordering = ["collaborator__name", "rubric__code"]
        constraints = [
            models.UniqueConstraint(fields=["cycle", "collaborator", "unit", "rubric", "source_event"], name="unique_payment_entry_source"),
            models.UniqueConstraint(fields=["cycle", "source_agreement"], condition=models.Q(source_agreement__isnull=False), name="unique_agreement_payment_cycle"),
            models.CheckConstraint(condition=~(models.Q(source_event__isnull=False) & models.Q(source_agreement__isnull=False)), name="single_payment_origin"),
        ]

    def __str__(self):
        return f"{self.collaborator} — {self.rubric.code} — R$ {self.amount}"


class RubricApplication(TimeStampedModel):
    MODE_CHOICES = [("recurring", "Valor mensal fixo"), ("event", "Valor fixo por ocorrência"), ("informative", "Somente conferência")]
    STATUS_CHOICES = [("draft", "Rascunho"), ("approved", "Aprovada")]
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="rubric_applications")
    rubric = models.ForeignKey(Rubric, on_delete=models.PROTECT, related_name="applications")
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="rubric_applications")
    mode = models.CharField(max_length=20, choices=MODE_CHOICES)
    amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    cycle_type = models.CharField(max_length=20, choices=[("monthly", "Mensal"), ("day10", "Dia 10 do mês seguinte"), ("none", "Sem pagamento")])
    leader_available = models.BooleanField(default=False)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    instructions = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    approved_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT, related_name="+")

    def __str__(self):
        return f"{self.rubric.code} — {self.unit.name} — {self.get_mode_display()}"

    def clean(self):
        super().clean()
        if self.rubric_id and self.unit_id:
            if self.rubric.tenant_id != self.tenant_id or self.unit.tenant_id != self.tenant_id:
                raise ValidationError("Rubrica e unidade devem pertencer ao mesmo cliente.")
            if self.effective_from and self.effective_from < self.rubric.effective_from:
                raise ValidationError("A regra não pode iniciar antes da vigência da rubrica.")
            if self.rubric.effective_to and (not self.effective_to or self.effective_to > self.rubric.effective_to):
                raise ValidationError("A regra deve terminar dentro da vigência da rubrica.")
            if self.mode == "informative":
                if self.rubric.category != "informative" or self.cycle_type != "none" or self.amount is not None:
                    raise ValidationError("Conferência exige rubrica informativa, sem valor de pagamento e ciclo sem pagamento.")
            elif self.mode in {"recurring", "event"}:
                if self.rubric.category != "earning":
                    raise ValidationError("Nesta etapa, geração financeira aceita somente proventos. Descontos exigem fluxo próprio.")
                if self.cycle_type not in {"monthly", "day10"} or self.amount is None or self.amount <= 0:
                    raise ValidationError("Informe valor fixo positivo e ciclo mensal ou dia 10.")
                if self.rubric.cycle_type not in {"both", self.cycle_type}:
                    raise ValidationError("O ciclo da regra deve ser compatível com o cadastro da rubrica.")
            if self.leader_available and self.mode != "event":
                raise ValidationError("Somente regras por ocorrência podem aparecer no painel do líder.")
            from .payments import DEFAULT_RUBRIC_DEFINITIONS
            if self.rubric.code in {item[0] for item in DEFAULT_RUBRIC_DEFINITIONS}:
                raise ValidationError("Rubrica padrão já possui fluxo próprio; não pode receber outra geração automática.")
        if self.effective_from and self.effective_to and self.effective_to < self.effective_from:
            raise ValidationError("Fim da vigência anterior ao início.")


class CollaboratorRubric(TimeStampedModel):
    STATUS_CHOICES = [("draft", "Rascunho"), ("approved", "Aprovado")]
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="collaborator_rubrics")
    application = models.ForeignKey(RubricApplication, on_delete=models.PROTECT, related_name="agreements")
    collaborator = models.ForeignKey(Collaborator, on_delete=models.PROTECT, related_name="rubric_agreements")
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    reference = models.CharField(max_length=240, blank=True)
    expected_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    approved_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT, related_name="+")

    def __str__(self):
        return f"{self.collaborator} — {self.application.rubric.code}"

    def clean(self):
        super().clean()
        if self.application_id and self.collaborator_id:
            app = self.application
            if app.tenant_id != self.tenant_id or self.collaborator.tenant_id != self.tenant_id:
                raise ValidationError("Regra e colaborador devem pertencer ao mesmo cliente.")
            if app.mode not in {"recurring", "informative"}:
                raise ValidationError("Vínculos recorrentes aceitam apenas regra mensal fixa ou informativa.")
            if app.status != "approved":
                raise ValidationError("A regra precisa estar aprovada antes de vincular colaboradores.")
            if self.effective_from and self.effective_from < app.effective_from:
                raise ValidationError("O vínculo inicia antes da regra.")
            if app.effective_to and (not self.effective_to or self.effective_to > app.effective_to):
                raise ValidationError("O vínculo deve terminar dentro da vigência da regra.")
            if self.expected_amount is not None and (app.mode != "informative" or self.expected_amount < 0):
                raise ValidationError("Valor esperado é opcional, não negativo e exclusivo da conferência.")
        if self.effective_from and self.effective_to and self.effective_to < self.effective_from:
            raise ValidationError("Fim da vigência anterior ao início.")


class ImportBatch(TimeStampedModel):
    STATUS_CHOICES = [("preview", "Prévia"), ("confirmed", "Confirmado"), ("rejected", "Rejeitado")]
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="import_batches")
    company = models.ForeignKey(Company, null=True, blank=True, on_delete=models.PROTECT, related_name="import_batches")
    competency = models.ForeignKey(Competency, null=True, blank=True, on_delete=models.PROTECT, related_name="import_batches")
    original_name = models.CharField(max_length=255)
    file = models.FileField(upload_to="imports/%Y/%m/")
    sha256 = models.CharField(max_length=64)
    sheet_name = models.CharField(max_length=160, blank=True)
    header_row = models.PositiveIntegerField(null=True, blank=True)
    detected = models.JSONField(default=dict)
    preview = models.JSONField(default=list)
    validation_rows = models.JSONField(default=list)
    errors = models.JSONField(default=list)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="preview")
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="created_import_batches")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.original_name} — {self.get_status_display()}"


class RosterImportBatch(TimeStampedModel):
    STATUS_CHOICES = [("preview", "Prévia"), ("confirmed", "Confirmado"), ("rejected", "Rejeitado")]
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="roster_import_batches")
    original_name = models.CharField(max_length=255)
    sha256 = models.CharField(max_length=64)
    sheet_name = models.CharField(max_length=160, blank=True)
    row_count = models.PositiveIntegerField(default=0)
    detected = models.JSONField(default=dict)
    validation_rows = models.JSONField(default=list)
    preview = models.JSONField(default=list)
    errors = models.JSONField(default=list)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="preview")
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="created_roster_import_batches")
    confirmed_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT, related_name="confirmed_roster_import_batches")
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Carga cadastral {self.original_name} — {self.get_status_display()}"


class CommunicationThread(TimeStampedModel):
    STATUS_CHOICES = [("open", "Aberta"), ("analysis", "Em análise"), ("waiting", "Aguardando informação"), ("resolved", "Resolvida"), ("closed", "Encerrada")]
    PRIORITY_CHOICES = [("low", "Baixa"), ("normal", "Normal"), ("high", "Alta"), ("critical", "Crítica")]
    KIND_CHOICES = [("question", "Dúvida"), ("issue", "Pendência"), ("notice", "Aviso"), ("request", "Solicitação")]
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="communication_threads")
    unit = models.ForeignKey(Unit, null=True, blank=True, on_delete=models.PROTECT, related_name="communication_threads")
    competency = models.ForeignKey(Competency, null=True, blank=True, on_delete=models.PROTECT, related_name="communication_threads")
    event = models.ForeignKey(FieldEvent, null=True, blank=True, on_delete=models.PROTECT, related_name="communication_threads")
    title = models.CharField(max_length=220)
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default="issue")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="open")
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default="normal")
    due_at = models.DateTimeField(null=True, blank=True)
    assigned_to = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT, related_name="assigned_threads")
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="created_threads")
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["status", "-priority", "due_at", "-created_at"]
        indexes = [models.Index(fields=["tenant", "status", "priority"]), models.Index(fields=["tenant", "unit", "due_at"])]

    def __str__(self):
        return self.title


class CommunicationMessage(TimeStampedModel):
    thread = models.ForeignKey(CommunicationThread, on_delete=models.PROTECT, related_name="messages")
    author = models.ForeignKey(User, on_delete=models.PROTECT, related_name="communication_messages")
    body = models.TextField()
    internal = models.BooleanField(default=False)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.author} — {self.created_at:%d/%m/%Y %H:%M}"


class Notification(TimeStampedModel):
    TYPE_CHOICES = [("thread", "Pendência"), ("event", "Evento"), ("system", "Sistema")]
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="notifications")
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    thread = models.ForeignKey(CommunicationThread, null=True, blank=True, on_delete=models.PROTECT, related_name="notifications")
    event = models.ForeignKey(FieldEvent, null=True, blank=True, on_delete=models.PROTECT, related_name="notifications")
    notification_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default="thread")
    title = models.CharField(max_length=220)
    body = models.CharField(max_length=500)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["read_at", "-created_at"]
        indexes = [models.Index(fields=["recipient", "read_at", "created_at"])]

    def __str__(self):
        return self.title


class ReportEmission(TimeStampedModel):
    FORMAT_CHOICES = [("xlsx", "Excel XLSX"), ("pdf", "PDF")]
    REPORT_CHOICES = [("cost", "Custo por unidade"), ("events", "Eventos detalhados")]
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="report_emissions")
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="report_emissions")
    report_type = models.CharField(max_length=30, choices=REPORT_CHOICES)
    file_format = models.CharField(max_length=10, choices=FORMAT_CHOICES)
    filters = models.JSONField(default=dict)
    row_count = models.PositiveIntegerField(default=0)
    file_name = models.CharField(max_length=220)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_report_type_display()} — {self.get_file_format_display()} — {self.created_at:%d/%m/%Y %H:%M}"


class DataQualityIssue(TimeStampedModel):
    SEVERITY_CHOICES = [("info", "Informativa"), ("warning", "Atenção"), ("critical", "Crítica")]
    STATUS_CHOICES = [("open", "Aberta"), ("resolved", "Resolvida")]
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="quality_issues")
    unit = models.ForeignKey(Unit, null=True, blank=True, on_delete=models.PROTECT, related_name="quality_issues")
    competency = models.ForeignKey(Competency, null=True, blank=True, on_delete=models.PROTECT, related_name="quality_issues")
    event = models.ForeignKey(FieldEvent, null=True, blank=True, on_delete=models.PROTECT, related_name="quality_issues")
    issue_type = models.CharField(max_length=50)
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default="warning")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="open")
    title = models.CharField(max_length=220)
    description = models.TextField()
    fingerprint = models.CharField(max_length=180)
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["status", "-severity", "-last_seen_at"]
        constraints = [models.UniqueConstraint(fields=["tenant", "fingerprint"], name="unique_quality_issue_fingerprint")]

    def __str__(self):
        return self.title
