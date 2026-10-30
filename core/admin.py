from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied

from .admin_forms import FieldEventAdminForm, UserScopeAdminForm
from .models import CollaboratorRubric, RubricApplication
from .models import AdmissionFieldDefinition, AdmissionFieldValue, AdmissionRequest, AuditLog, CalculationResult, CalculationRule, Collaborator, Company, CommunicationMessage, CommunicationThread, Competency, CompensationVersion, DataQualityIssue, EmploymentLink, FieldEvent, ImportBatch, MonthlyCompensationResult, Notification, PaymentCycle, PaymentEntry, ReportEmission, Rubric, Tenant, Unit, UserScope

class ImmutableWorkflowAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "active")
    search_fields = ("name", "slug")


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("legal_name", "cnpj", "tenant", "active")
    list_filter = ("tenant", "active")
    search_fields = ("legal_name", "cnpj")


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ("name", "company", "region", "active")
    list_filter = ("tenant", "company", "active")
    search_fields = ("name", "region")


@admin.register(UserScope)
class UserScopeAdmin(admin.ModelAdmin):
    form = UserScopeAdminForm
    list_display = ("user", "tenant", "company", "unit", "role")
    list_filter = ("tenant", "role")
    search_fields = ("user__username", "user__email")


class UserScopeInline(admin.TabularInline):
    model = UserScope
    form = UserScopeAdminForm
    extra = 1
    fields = ("tenant", "company", "unit", "role")


admin.site.unregister(User)


@admin.register(User)
class PlatformUserAdmin(BaseUserAdmin):
    inlines = [UserScopeInline]


@admin.register(Competency)
class CompetencyAdmin(admin.ModelAdmin):
    list_display = ("tenant", "year", "month", "status", "cutoff_date")
    list_filter = ("tenant", "status", "year")
    readonly_fields = ("status", "closed_at", "created_at", "updated_at")

    def has_change_permission(self, request, obj=None):
        return obj is None and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        if not change:
            obj.status = "open"
            obj.closed_at = None
        super().save_model(request, obj, form, change)
        if not change:
            AuditLog.objects.create(
                tenant=obj.tenant,
                user=request.user,
                action="create",
                entity="competency",
                entity_id=str(obj.pk),
                after={"year": obj.year, "month": obj.month, "status": "open"},
                reason="Competência criada com status inicial aberto pelo Admin.",
            )


@admin.register(Collaborator)
class CollaboratorAdmin(admin.ModelAdmin):
    list_display = ("name", "employee_code", "tenant", "active")
    list_filter = ("tenant", "active")
    search_fields = ("name", "employee_code")


@admin.register(EmploymentLink)
class EmploymentLinkAdmin(admin.ModelAdmin):
    list_display = ("collaborator", "company", "unit", "job_title", "admission_date", "termination_date")
    list_filter = ("company", "unit")
    search_fields = ("collaborator__name", "job_title")


@admin.register(CompensationVersion)
class CompensationVersionAdmin(admin.ModelAdmin):
    list_display = ("collaborator", "company", "unit", "combined_salary", "clt_salary", "effective_from", "effective_to", "created_by")
    list_filter = ("company", "unit", "effective_from")
    search_fields = ("collaborator__name", "collaborator__employee_code")
    readonly_fields = ("created_at", "updated_at")


@admin.register(FieldEvent)
class FieldEventAdmin(admin.ModelAdmin):
    form = FieldEventAdminForm
    list_display = ("event_date", "event_type", "collaborator", "unit", "status", "created_by")
    list_filter = ("tenant", "competency", "event_type", "status", "unit")
    search_fields = ("collaborator__name", "reason")
    readonly_fields = ("idempotency_key", "created_at", "updated_at")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        if obj is not None and (obj.status != "pending" or obj.competency.status == "closed"):
            return False
        return super().has_change_permission(request, obj)

    def get_readonly_fields(self, request, obj=None):
        immutable = {"idempotency_key", "created_at", "updated_at", "tenant", "competency", "created_by", "sync_received_at"}
        if obj is not None and (obj.status != "pending" or obj.competency.status == "closed"):
            return tuple(field.name for field in FieldEvent._meta.fields)
        return tuple(immutable)

    def save_model(self, request, obj, form, change):
        if change:
            before = FieldEvent.objects.get(pk=obj.pk)
            _before = {"event_type": before.event_type, "event_date": before.event_date.isoformat(), "quantity": str(before.quantity), "reason": before.reason, "unit_id": before.unit_id, "collaborator_id": before.collaborator_id}
            super().save_model(request, obj, form, change)
            AuditLog.objects.create(
                tenant=obj.tenant,
                user=request.user,
                action="update",
                entity="field_event",
                entity_id=obj.id,
                before=_before,
                after={"event_type": obj.event_type, "event_date": obj.event_date.isoformat(), "quantity": str(obj.quantity), "reason": obj.reason, "unit_id": obj.unit_id, "collaborator_id": obj.collaborator_id},
                reason=form.cleaned_data.get("change_reason", ""),
            )
        else:
            super().save_model(request, obj, form, change)


@admin.register(AuditLog)
class AuditLogAdmin(ImmutableWorkflowAdmin):
    list_display = ("created_at", "action", "entity", "entity_id", "user", "tenant")
    list_filter = ("tenant", "action", "entity")
    search_fields = ("entity", "entity_id", "user__username")
    readonly_fields = [field.name for field in AuditLog._meta.fields]


@admin.register(CalculationRule)
class CalculationRuleAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "version", "event_type", "status", "effective_from", "effective_to", "tenant")
    list_filter = ("tenant", "status", "event_type", "company", "unit")
    search_fields = ("code", "name", "legal_reference")
    readonly_fields = ("created_at", "updated_at", "published_at")


@admin.register(CalculationResult)
class CalculationResultAdmin(ImmutableWorkflowAdmin):
    list_display = ("competency", "collaborator", "event", "rule", "calculated_amount", "created_at")
    list_filter = ("tenant", "competency", "rule")
    search_fields = ("collaborator__name", "rule__code")
    readonly_fields = [field.name for field in CalculationResult._meta.fields]


@admin.register(MonthlyCompensationResult)
class MonthlyCompensationResultAdmin(ImmutableWorkflowAdmin):
    list_display = ("competency", "collaborator", "normal_days", "rain_days", "total_amount", "payment_cycle")
    list_filter = ("tenant", "competency", "payment_cycle")
    search_fields = ("collaborator__name",)
    readonly_fields = [field.name for field in MonthlyCompensationResult._meta.fields]


@admin.register(PaymentCycle)
class PaymentCycleAdmin(ImmutableWorkflowAdmin):
    list_display = ("competency", "cycle_type", "payment_date", "status", "approved_by", "created_by")
    list_filter = ("tenant", "cycle_type", "status")
    readonly_fields = [field.name for field in PaymentCycle._meta.fields]


@admin.register(Rubric)
class RubricAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "category", "cycle_type", "version", "active", "effective_from", "effective_to")
    list_filter = ("tenant", "category", "cycle_type", "active")
    search_fields = ("code", "name")
    readonly_fields = ("created_at", "updated_at")

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.applications.exists():
            return tuple(field.name for field in Rubric._meta.fields)
        return super().get_readonly_fields(request, obj)


@admin.register(RubricApplication, CollaboratorRubric)
class RubricApplicationReadOnlyAdmin(admin.ModelAdmin):
    list_filter = ("tenant", "status")
    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PaymentEntry)
class PaymentEntryAdmin(ImmutableWorkflowAdmin):
    list_display = ("cycle", "collaborator", "rubric", "amount", "status", "unit")
    list_filter = ("tenant", "status", "cycle__cycle_type", "rubric__category")
    search_fields = ("collaborator__name", "rubric__code")
    readonly_fields = [field.name for field in PaymentEntry._meta.fields]


@admin.register(ImportBatch)
class ImportBatchAdmin(admin.ModelAdmin):
    list_display = ("original_name", "tenant", "sheet_name", "header_row", "status", "sha256", "created_by", "created_at")
    list_filter = ("tenant", "status", "sheet_name")
    search_fields = ("original_name", "sha256")
    readonly_fields = [field.name for field in ImportBatch._meta.fields]


@admin.register(AdmissionFieldDefinition)
class AdmissionFieldDefinitionAdmin(admin.ModelAdmin):
    list_display = ("label", "code", "tenant", "section", "field_type", "required", "active", "sort_order")
    list_filter = ("tenant", "section", "field_type", "required", "active")
    search_fields = ("label", "code")


@admin.register(AdmissionRequest)
class AdmissionRequestAdmin(admin.ModelAdmin):
    list_display = ("candidate_name", "company", "unit", "status", "expires_at", "created_by", "created_at")
    list_filter = ("tenant", "status", "company", "unit")
    search_fields = ("candidate_name", "candidate_phone", "job_title")
    readonly_fields = ("token", "access_key_hash", "access_key_hint", "created_at", "updated_at", "submitted_at", "reviewed_at", "converted_link", "converted_by", "converted_at")

    def has_change_permission(self, request, obj=None):
        if obj is not None and obj.converted_link_id:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.converted_link_id:
            return False
        return super().has_delete_permission(request, obj)

    def delete_queryset(self, request, queryset):
        if queryset.filter(converted_link__isnull=False).exists():
            raise PermissionDenied("Pré-admissões convertidas devem ser preservadas para auditoria.")
        return super().delete_queryset(request, queryset)


@admin.register(AdmissionFieldValue)
class AdmissionFieldValueAdmin(admin.ModelAdmin):
    list_display = ("request", "field", "changed_by", "updated_at")
    list_filter = ("field__tenant", "field__section")
    search_fields = ("request__candidate_name", "field__label")
    readonly_fields = [field.name for field in AdmissionFieldValue._meta.fields]


@admin.register(CommunicationThread)
class CommunicationThreadAdmin(admin.ModelAdmin):
    list_display = ("title", "kind", "status", "priority", "unit", "assigned_to", "due_at", "created_at")
    list_filter = ("tenant", "status", "priority", "kind", "unit")
    search_fields = ("title", "messages__body")
    readonly_fields = ("created_at", "updated_at", "resolved_at", "created_by")


@admin.register(CommunicationMessage)
class CommunicationMessageAdmin(admin.ModelAdmin):
    list_display = ("thread", "author", "internal", "created_at")
    list_filter = ("internal", "thread__tenant")
    search_fields = ("body", "thread__title")
    readonly_fields = ("created_at", "updated_at", "author")


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("title", "recipient", "notification_type", "read_at", "created_at")
    list_filter = ("tenant", "notification_type", "read_at")
    search_fields = ("title", "body", "recipient__username")
    readonly_fields = [field.name for field in Notification._meta.fields]


@admin.register(ReportEmission)
class ReportEmissionAdmin(admin.ModelAdmin):
    list_display = ("report_type", "file_format", "user", "row_count", "file_name", "created_at")
    list_filter = ("tenant", "report_type", "file_format", "created_at")
    search_fields = ("file_name", "user__username")
    readonly_fields = [field.name for field in ReportEmission._meta.fields]


@admin.register(DataQualityIssue)
class DataQualityIssueAdmin(admin.ModelAdmin):
    list_display = ("title", "severity", "status", "unit", "competency", "last_seen_at")
    list_filter = ("tenant", "severity", "status", "issue_type", "unit")
    search_fields = ("title", "description", "fingerprint")
    readonly_fields = [field.name for field in DataQualityIssue._meta.fields]
