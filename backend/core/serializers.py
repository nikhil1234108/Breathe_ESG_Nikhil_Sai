from rest_framework import serializers
from django.contrib.auth.models import User
from core.models import (
    Company, UserProfile, DataSource, RawUpload, RawRecord,
    NormalizedEmissionRecord, ValidationIssue, ReviewDecision, AuditLog
)

class CompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = '__all__'

class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = ['role', 'company']

class UserSerializer(serializers.ModelSerializer):
    profile = UserProfileSerializer(read_only=True)
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'profile']

class DataSourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = DataSource
        fields = '__all__'

class RawUploadSerializer(serializers.ModelSerializer):
    data_source_name = serializers.CharField(source='data_source.name', read_only=True)
    uploaded_by_username = serializers.CharField(source='uploaded_by.username', read_only=True)
    
    class Meta:
        model = RawUpload
        fields = [
            'id', 'company', 'data_source', 'data_source_name', 
            'upload_type', 'filename', 'status', 'error_message', 
            'uploaded_by_username', 'created_at'
        ]

class RawRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = RawRecord
        fields = '__all__'

class ValidationIssueSerializer(serializers.ModelSerializer):
    class Meta:
        model = ValidationIssue
        fields = ['id', 'issue_type', 'severity', 'message', 'created_at']

class NormalizedEmissionRecordSerializer(serializers.ModelSerializer):
    issues = ValidationIssueSerializer(many=True, read_only=True)
    raw_data = serializers.JSONField(source='raw_record.raw_data', read_only=True)
    approved_by_username = serializers.CharField(source='approved_by.username', read_only=True)
    last_decision_reason = serializers.SerializerMethodField()
    last_decision_by = serializers.SerializerMethodField()
    
    class Meta:
        model = NormalizedEmissionRecord
        fields = [
            'id', 'company', 'raw_record', 'raw_data', 'source_type', 'scope_category',
            'activity_type', 'facility_or_plant', 'transaction_date',
            'billing_period_start', 'billing_period_end',
            'raw_quantity', 'raw_unit', 'normalized_quantity', 'normalized_unit',
            'emission_factor', 'calculated_co2e', 'validation_status', 'review_status',
            'approved_by_username', 'approved_at', 'is_locked', 'issues', 'created_at', 'updated_at',
            'last_decision_reason', 'last_decision_by'
        ]
        read_only_fields = ['id', 'company', 'raw_record', 'calculated_co2e', 'validation_status', 'is_locked', 'created_at', 'updated_at']

    def get_last_decision_reason(self, obj):
        decision = obj.decisions.order_by('-created_at').first()
        return decision.reason if decision else None

    def get_last_decision_by(self, obj):
        decision = obj.decisions.order_by('-created_at').first()
        return decision.decided_by.username if decision and decision.decided_by else None

class ReviewDecisionSerializer(serializers.ModelSerializer):
    decided_by_username = serializers.CharField(source='decided_by.username', read_only=True)

    class Meta:
        model = ReviewDecision
        fields = ['id', 'emission_record', 'decision', 'reason', 'decided_by_username', 'created_at']

class AuditLogSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)

    class Meta:
        model = AuditLog
        fields = ['id', 'company', 'username', 'action', 'target_type', 'target_id', 'changes', 'created_at']
