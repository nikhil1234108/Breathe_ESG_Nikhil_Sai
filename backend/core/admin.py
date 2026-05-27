from django.contrib import admin
from .models import (
    Company, UserProfile, DataSource, RawUpload, RawRecord,
    NormalizedEmissionRecord, ValidationIssue, ReviewDecision,
    AuditLog, UnitConversionMap, EmissionFactor
)

@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ('name', 'created_at')

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'company', 'role')

@admin.register(DataSource)
class DataSourceAdmin(admin.ModelAdmin):
    list_display = ('name', 'source_type', 'company', 'active')

@admin.register(RawUpload)
class RawUploadAdmin(admin.ModelAdmin):
    list_display = ('id', 'data_source', 'status', 'created_at')

@admin.register(RawRecord)
class RawRecordAdmin(admin.ModelAdmin):
    list_display = ('id', 'raw_upload', 'row_index')

@admin.register(NormalizedEmissionRecord)
class NormalizedEmissionRecordAdmin(admin.ModelAdmin):
    list_display = ('activity_type', 'calculated_co2e', 'review_status', 'is_locked', 'transaction_date')
    list_filter = ('source_type', 'scope_category', 'validation_status', 'review_status', 'is_locked')

@admin.register(ValidationIssue)
class ValidationIssueAdmin(admin.ModelAdmin):
    list_display = ('emission_record', 'issue_type', 'severity', 'message')

@admin.register(ReviewDecision)
class ReviewDecisionAdmin(admin.ModelAdmin):
    list_display = ('emission_record', 'decision', 'decided_by', 'created_at')

@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('action', 'target_type', 'target_id', 'user', 'created_at')

@admin.register(UnitConversionMap)
class UnitConversionMapAdmin(admin.ModelAdmin):
    list_display = ('from_unit', 'to_unit', 'conversion_factor')

@admin.register(EmissionFactor)
class EmissionFactorAdmin(admin.ModelAdmin):
    list_display = ('activity_type', 'year', 'factor', 'source_reference')
