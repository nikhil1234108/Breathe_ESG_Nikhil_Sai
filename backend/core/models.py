import uuid
from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db.models import JSONField

class Company(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "Companies"

    def __str__(self):
        return self.name

class UserProfile(models.Model):
    ROLE_CHOICES = [
        ('analyst', 'Sustainability Analyst'),
        ('auditor', 'ESG Auditor'),
        ('admin', 'Administrator'),
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='users')
    role = models.CharField(max_length=50, choices=ROLE_CHOICES, default='analyst')

    def __str__(self):
        return f"{self.user.username} ({self.role}) @ {self.company.name}"

class DataSource(models.Model):
    SOURCE_TYPE_CHOICES = [
        ('sap_fuel', 'SAP Fuel & Procurement Export'),
        ('utility_electricity', 'Utility Electricity Bill Export'),
        ('corporate_travel', 'Corporate Travel API Sync'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='data_sources')
    name = models.CharField(max_length=255)
    source_type = models.CharField(max_length=50, choices=SOURCE_TYPE_CHOICES)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.get_source_type_display()}) - {self.company.name}"

class RawUpload(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='uploads')
    data_source = models.ForeignKey(DataSource, on_delete=models.CASCADE, related_name='uploads')
    upload_type = models.CharField(max_length=10, choices=[('file', 'File Upload'), ('api', 'API Sync')], default='file')
    filename = models.CharField(max_length=255, blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    error_message = models.TextField(blank=True, null=True)
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='uploads')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Upload {self.id} ({self.status}) - {self.created_at}"

class RawRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    raw_upload = models.ForeignKey(RawUpload, on_delete=models.CASCADE, related_name='raw_records')
    row_index = models.IntegerField()
    raw_data = JSONField() # Stores exact original columns and values
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"RawRecord {self.id} (Upload: {self.raw_upload.id}, Row: {self.row_index})"

class NormalizedEmissionRecord(models.Model):
    VALIDATION_STATUS_CHOICES = [
        ('valid', 'Valid'),
        ('suspicious', 'Suspicious'),
        ('failed', 'Failed'),
    ]
    REVIEW_STATUS_CHOICES = [
        ('pending', 'Pending Review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='normalized_records')
    raw_record = models.ForeignKey(RawRecord, on_delete=models.SET_NULL, null=True, blank=True, related_name='normalized_records')
    source_type = models.CharField(max_length=50, choices=DataSource.SOURCE_TYPE_CHOICES)
    scope_category = models.IntegerField(choices=[(1, 'Scope 1 - Direct'), (2, 'Scope 2 - Indirect'), (3, 'Scope 3 - Value Chain')])
    activity_type = models.CharField(max_length=100) # e.g. diesel, petrol, electricity, flight, hotel, ground_transport
    facility_or_plant = models.CharField(max_length=255, blank=True, null=True) # Werk_Code, Meter_ID, Cost Center, Office
    transaction_date = models.DateField()
    billing_period_start = models.DateField(null=True, blank=True)
    billing_period_end = models.DateField(null=True, blank=True)
    
    raw_quantity = models.DecimalField(max_digits=18, decimal_places=4)
    raw_unit = models.CharField(max_length=50)
    normalized_quantity = models.DecimalField(max_digits=18, decimal_places=4)
    normalized_unit = models.CharField(max_length=50)
    
    emission_factor = models.DecimalField(max_digits=12, decimal_places=6) # kg CO2e per normalized unit
    calculated_co2e = models.DecimalField(max_digits=18, decimal_places=4) # kg CO2e
    
    validation_status = models.CharField(max_length=20, choices=VALIDATION_STATUS_CHOICES, default='valid')
    review_status = models.CharField(max_length=20, choices=REVIEW_STATUS_CHOICES, default='pending')
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_records')
    approved_at = models.DateTimeField(null=True, blank=True)
    is_locked = models.BooleanField(default=False) # Immutable toggle
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        # ORM-level locking check
        if self.pk:
            try:
                original = NormalizedEmissionRecord.objects.get(pk=self.pk)
                if original.is_locked and not kwargs.pop('force_unlock', False):
                    raise ValidationError("This record is approved and locked. It is immutable and cannot be updated.")
            except NormalizedEmissionRecord.DoesNotExist:
                pass
        
        # Enforce lock when status transitions to approved
        if self.review_status == 'approved' and not self.is_locked:
            self.is_locked = True
            
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.is_locked and not kwargs.pop('force_unlock', False):
            raise ValidationError("This record is approved and locked. It is immutable and cannot be deleted.")
        super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.activity_type} - {self.calculated_co2e} kg CO2e ({self.review_status})"

class ValidationIssue(models.Model):
    SEVERITY_CHOICES = [
        ('error', 'Error (Fails Record)'),
        ('warning', 'Warning (Suspicious)'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    emission_record = models.ForeignKey(NormalizedEmissionRecord, on_delete=models.CASCADE, related_name='issues')
    issue_type = models.CharField(max_length=100) # e.g. missing_unit, invalid_date, duplicate, out_of_bounds, negative_value, overlapping_period
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.severity.upper()}: {self.message}"

class ReviewDecision(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    emission_record = models.ForeignKey(NormalizedEmissionRecord, on_delete=models.CASCADE, related_name='decisions')
    decision = models.CharField(max_length=20, choices=[('approved', 'Approved'), ('rejected', 'Rejected')])
    reason = models.TextField(blank=True, null=True) # Reason is critical for rejects or suspicious overrides
    decided_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='decisions')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.decision.upper()} by {self.decided_by.username} on {self.created_at}"

class AuditLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='audit_logs')
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=50) # e.g. UPLOAD, NORMALIZE, VALIDATE, APPROVE, REJECT, EDIT, LOCK
    target_type = models.CharField(max_length=100) # e.g. NormalizedEmissionRecord, RawUpload
    target_id = models.UUIDField()
    changes = JSONField(blank=True, null=True) # Holds before/after state diff
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.action} on {self.target_type} ({self.target_id}) by {self.user.username if self.user else 'System'}"

class UnitConversionMap(models.Model):
    from_unit = models.CharField(max_length=50)
    to_unit = models.CharField(max_length=50)
    conversion_factor = models.DecimalField(max_digits=18, decimal_places=8)

    class Meta:
        unique_together = ('from_unit', 'to_unit')

    def __str__(self):
        return f"{self.from_unit} -> {self.to_unit} (x{self.conversion_factor})"

class EmissionFactor(models.Model):
    activity_type = models.CharField(max_length=100) # e.g. diesel, petrol, electricity, flight_economy, flight_business, hotel_stay
    year = models.IntegerField()
    factor = models.DecimalField(max_digits=12, decimal_places=6) # kg CO2e per normalized unit (e.g. per Litre, per kWh, per passenger-km)
    source_reference = models.CharField(max_length=255)

    class Meta:
        unique_together = ('activity_type', 'year')

    def __str__(self):
        return f"{self.activity_type} ({self.year}): {self.factor} kg CO2e ({self.source_reference})"


from django.db.models.signals import pre_delete, post_save, post_delete
from django.dispatch import receiver
from core.services.utils import get_bypass_signals

@receiver(pre_delete, sender=NormalizedEmissionRecord)
def block_locked_record_delete(sender, instance, **kwargs):
    if instance.is_locked and not getattr(instance, '_bypass_delete_lock', False):
        raise ValidationError("Cannot delete record because it is approved and locked.")

@receiver(post_save, sender=NormalizedEmissionRecord)
def log_record_save(sender, instance, created, **kwargs):
    if getattr(instance, '_bypass_audit_signal', False) or get_bypass_signals():
        return
    action = 'CREATE' if created else 'EDIT'
    AuditLog.objects.create(
        company=instance.company,
        user=None,
        action=action,
        target_type='NormalizedEmissionRecord',
        target_id=instance.id,
        changes={
            'activity_type': instance.activity_type,
            'calculated_co2e': str(instance.calculated_co2e),
            'review_status': instance.review_status,
            'validation_status': instance.validation_status
        }
    )

@receiver(post_delete, sender=NormalizedEmissionRecord)
def log_record_delete(sender, instance, **kwargs):
    if getattr(instance, '_bypass_audit_signal', False) or get_bypass_signals():
        return
    AuditLog.objects.create(
        company=instance.company,
        user=None,
        action='DELETE',
        target_type='NormalizedEmissionRecord',
        target_id=instance.id,
        changes={
            'deleted': True,
            'activity_type': instance.activity_type,
            'calculated_co2e': str(instance.calculated_co2e)
        }
    )
