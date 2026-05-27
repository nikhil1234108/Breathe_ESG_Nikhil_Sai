from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import BasePermission
from django.conf import settings
from django.db.models import Sum, Count, Q
from django.db.models.functions import TruncMonth
from django.utils import timezone
from django.contrib.auth.models import User
from core.models import (
    Company, DataSource, RawUpload, NormalizedEmissionRecord,
    ValidationIssue, ReviewDecision, AuditLog
)
from core.serializers import (
    DataSourceSerializer, RawUploadSerializer, NormalizedEmissionRecordSerializer,
    ReviewDecisionSerializer, AuditLogSerializer
)
from core.services.ingestion import ingest_csv_file, sync_travel_api
from core.services.utils import set_bypass_signals

class IsAuthenticatedOrDebugFallback(BasePermission):
    """
    Blocks unauthenticated users in production (settings.DEBUG = False).
    Allows anonymous requests locally (settings.DEBUG = True), falling back to 'analyst' username.
    """
    def has_permission(self, request, view):
        if request.user and request.user.is_authenticated:
            return True
        return settings.DEBUG

class DataSourceViewSet(viewsets.ModelViewSet):
    queryset = DataSource.objects.filter(active=True)
    serializer_class = DataSourceSerializer
    permission_classes = [IsAuthenticatedOrDebugFallback]

    def get_queryset(self):
        # Multi-tenancy filter
        user = self.request.user
        if user.is_authenticated and hasattr(user, 'profile'):
            return self.queryset.filter(company=user.profile.company)
        return self.queryset.all()

class RawUploadViewSet(viewsets.ModelViewSet):
    queryset = RawUpload.objects.all().order_by('-created_at')
    serializer_class = RawUploadSerializer
    permission_classes = [IsAuthenticatedOrDebugFallback]

    def get_queryset(self):
        # Multi-tenancy filter
        user = self.request.user
        if user.is_authenticated and hasattr(user, 'profile'):
            return self.queryset.filter(company=user.profile.company)
        return self.queryset.all()

    @action(detail=False, methods=['post'], url_path='upload-file')
    def upload_file(self, request):
        """
        Ingests a uploaded CSV file (SAP or Utility)
        """
        file_obj = request.FILES.get('file')
        data_source_id = request.data.get('data_source_id')
        
        if not file_obj:
            return Response({"error": "No file uploaded"}, status=status.HTTP_400_BAD_REQUEST)
        if not data_source_id:
            return Response({"error": "Missing data_source_id"}, status=status.HTTP_400_BAD_REQUEST)

        # Get default company & user profiles (mocking session auth for ease of assignment test)
        user = request.user if request.user.is_authenticated else User.objects.get(username='analyst')
        company = user.profile.company if hasattr(user, 'profile') else Company.objects.first()

        try:
            data_source = DataSource.objects.get(id=data_source_id, company=company)
        except DataSource.DoesNotExist:
            return Response({"error": "Data source not found or access denied"}, status=status.HTTP_404_NOT_FOUND)

        raw_upload = ingest_csv_file(
            company=company,
            data_source=data_source,
            file_file=file_obj,
            filename=file_obj.name,
            uploaded_by=user
        )

        return Response(RawUploadSerializer(raw_upload).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'], url_path='sync-api')
    def sync_api(self, request):
        """
        Syncs corporate travel data from mock Navan/Concur API
        """
        data_source_id = request.data.get('data_source_id')
        if not data_source_id:
            return Response({"error": "Missing data_source_id"}, status=status.HTTP_400_BAD_REQUEST)

        user = request.user if request.user.is_authenticated else User.objects.get(username='analyst')
        company = user.profile.company if hasattr(user, 'profile') else Company.objects.first()

        try:
            data_source = DataSource.objects.get(id=data_source_id, company=company)
        except DataSource.DoesNotExist:
            return Response({"error": "Data source not found or access denied"}, status=status.HTTP_404_NOT_FOUND)

        # Dynamic sync URL based on current host
        host = request.get_host()
        protocol = 'https' if request.is_secure() else 'http'
        sync_url = f"{protocol}://{host}/api/external/travel-data/"

        raw_upload = sync_travel_api(
            company=company,
            data_source=data_source,
            uploaded_by=user,
            sync_url=sync_url
        )

        return Response(RawUploadSerializer(raw_upload).data, status=status.HTTP_200_OK)

class NormalizedEmissionRecordViewSet(viewsets.ModelViewSet):
    queryset = NormalizedEmissionRecord.objects.all().order_by('-created_at')
    serializer_class = NormalizedEmissionRecordSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ['facility_or_plant', 'activity_type', 'raw_unit']
    permission_classes = [IsAuthenticatedOrDebugFallback]

    def get_queryset(self):
        user = self.request.user
        company = user.profile.company if (user.is_authenticated and hasattr(user, 'profile')) else Company.objects.first()
        
        queryset = self.queryset.filter(company=company)
        
        # Custom query filters
        val_status = self.request.query_params.get('validation_status')
        rev_status = self.request.query_params.get('review_status')
        source_t = self.request.query_params.get('source_type')
        scope_cat = self.request.query_params.get('scope_category')
        
        if val_status:
            queryset = queryset.filter(validation_status=val_status)
        if rev_status:
            queryset = queryset.filter(review_status=rev_status)
        if source_t:
            queryset = queryset.filter(source_type=source_t)
        if scope_cat:
            queryset = queryset.filter(scope_category=scope_cat)
            
        return queryset

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        """
        Approves a normalized record. Locks it from future edits.
        """
        record = self.get_object()
        
        if record.is_locked:
            return Response({"error": "Record is already approved and locked"}, status=status.HTTP_400_BAD_REQUEST)
            
        # Reject approvals if there are validation ERRORS (warnings/suspicious can be overridden)
        if record.validation_status == 'failed':
            return Response({
                "error": "Cannot approve record with blocking validation errors. Clean the raw data first."
            }, status=status.HTTP_400_BAD_REQUEST)

        reason = request.data.get('reason', '').strip()
        
        # Enforce justification for all approvals
        if not reason:
            return Response({
                "error": "A justification override reason is required to approve this record."
            }, status=status.HTTP_400_BAD_REQUEST)

        user = request.user if request.user.is_authenticated else User.objects.get(username='analyst')

        # Atomic transaction to ensure audit integrity
        from django.db import transaction
        set_bypass_signals(True)
        try:
            with transaction.atomic():
                record.review_status = 'approved'
                record.approved_by = user
                record.approved_at = timezone.now()
                record.is_locked = True
                record.save()

                ReviewDecision.objects.create(
                    emission_record=record,
                    decision='approved',
                    reason=reason,
                    decided_by=user
                )

                AuditLog.objects.create(
                    company=record.company,
                    user=user,
                    action='APPROVE',
                    target_type='NormalizedEmissionRecord',
                    target_id=record.id,
                    changes={'status': 'approved', 'reason': reason}
                )
        finally:
            set_bypass_signals(False)

        return Response(NormalizedEmissionRecordSerializer(record).data)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        """
        Rejects a record. Requires a reason, does NOT lock it so it can be re-processed.
        """
        record = self.get_object()
        
        if record.is_locked:
            return Response({"error": "Cannot reject a locked audit record"}, status=status.HTTP_400_BAD_REQUEST)

        reason = request.data.get('reason', '').strip()
        if not reason:
            return Response({"error": "A justification reason is required to reject a record."}, status=status.HTTP_400_BAD_REQUEST)

        user = request.user if request.user.is_authenticated else User.objects.get(username='analyst')

        from django.db import transaction
        set_bypass_signals(True)
        try:
            with transaction.atomic():
                record.review_status = 'rejected'
                record.save()

                ReviewDecision.objects.create(
                    emission_record=record,
                    decision='rejected',
                    reason=reason,
                    decided_by=user
                )

                AuditLog.objects.create(
                    company=record.company,
                    user=user,
                    action='REJECT',
                    target_type='NormalizedEmissionRecord',
                    target_id=record.id,
                    changes={'status': 'rejected', 'reason': reason}
                )
        finally:
            set_bypass_signals(False)

        return Response(NormalizedEmissionRecordSerializer(record).data)

    @action(detail=False, methods=['post'], url_path='bulk-approve')
    def bulk_approve(self, request):
        """
        Bulk approves selected pending records
        """
        record_ids = request.data.get('record_ids', [])
        if not record_ids:
            return Response({"error": "No records specified"}, status=status.HTTP_400_BAD_REQUEST)

        user = request.user if request.user.is_authenticated else User.objects.get(username='analyst')
        company = user.profile.company if hasattr(user, 'profile') else Company.objects.first()

        records = NormalizedEmissionRecord.objects.filter(
            id__in=record_ids, company=company, is_locked=False
        ).exclude(validation_status='failed')

        reason = request.data.get('reason', '').strip()

        # Enforce justification for all bulk approvals
        if not reason:
            return Response({
                "error": "A justification override reason is required to bulk approve records."
            }, status=status.HTTP_400_BAD_REQUEST)

        bulk_reason = reason

        count = 0
        from django.db import transaction
        set_bypass_signals(True)
        try:
            with transaction.atomic():
                for record in records:
                    record.review_status = 'approved'
                    record.approved_by = user
                    record.approved_at = timezone.now()
                    record.is_locked = True
                    record.save()

                    ReviewDecision.objects.create(
                        emission_record=record,
                        decision='approved',
                        reason=bulk_reason,
                        decided_by=user
                    )

                    AuditLog.objects.create(
                        company=company,
                        user=user,
                        action='APPROVE',
                        target_type='NormalizedEmissionRecord',
                        target_id=record.id,
                        changes={'status': 'approved', 'reason': bulk_reason}
                    )
                    count += 1
        finally:
            set_bypass_signals(False)

        return Response({"approved_count": count}, status=status.HTTP_200_OK)

class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AuditLog.objects.all().order_by('-created_at')
    serializer_class = AuditLogSerializer
    permission_classes = [IsAuthenticatedOrDebugFallback]

    def get_queryset(self):
        user = self.request.user
        if user.is_authenticated and hasattr(user, 'profile'):
            return self.queryset.filter(company=user.profile.company)
        return self.queryset.all()

class DashboardMetricsView(APIView):
    """
    Exposes analytical metrics for the ESG review screen.
    """
    permission_classes = [IsAuthenticatedOrDebugFallback]
    def get(self, request):
        user = request.user
        company = user.profile.company if (user.is_authenticated and hasattr(user, 'profile')) else Company.objects.first()

        records = NormalizedEmissionRecord.objects.filter(company=company)
        approved_records = records.filter(review_status='approved')

        # Total emissions
        total_co2e = approved_records.aggregate(total=Sum('calculated_co2e'))['total'] or 0.0
        
        # Emissions by scope
        scope_emissions = approved_records.values('scope_category').annotate(total=Sum('calculated_co2e'))
        scope_data = {1: 0.0, 2: 0.0, 3: 0.0}
        for item in scope_emissions:
            scope_data[item['scope_category']] = float(item['total'])

        # Queue counts
        counts = records.aggregate(
            total=Count('id'),
            pending=Count('id', filter=Q(review_status='pending')),
            approved=Count('id', filter=Q(review_status='approved')),
            rejected=Count('id', filter=Q(review_status='rejected')),
            failed=Count('id', filter=Q(validation_status='failed')),
            suspicious=Count('id', filter=Q(validation_status='suspicious'))
        )

        # Emissions over time (truncated monthly)
        monthly_emissions = approved_records.annotate(
            month=TruncMonth('transaction_date')
        ).values('month').annotate(
            total=Sum('calculated_co2e')
        ).order_by('month')

        monthly_data = []
        for item in monthly_emissions:
            if item['month']:
                monthly_data.append({
                    'month': item['month'].strftime('%Y-%m'),
                    'co2e': float(item['total'])
                })

        # Count of issues by type
        issues_summary = ValidationIssue.objects.filter(
            emission_record__company=company
        ).values('issue_type', 'severity').annotate(count=Count('id')).order_by('-count')

        return Response({
            'total_co2e': float(total_co2e),
            'scope_1': scope_data[1],
            'scope_2': scope_data[2],
            'scope_3': scope_data[3],
            'counts': counts,
            'monthly_emissions': monthly_data,
            'issues_summary': list(issues_summary)
        }, status=status.HTTP_200_OK)

class MockTravelAPIView(APIView):
    """
    Mock endpoint representing the Navan/Concur Corporate Travel platform REST API.
    Exposes simulated business travel data with anomalies for ingestion testing.
    """
    permission_classes = []
    authentication_classes = []

    def get(self, request):
        mock_data = [
            # 1. Standard flight, missing distance (will trigger Haversine lookup LHR -> JFK)
            {
                "travel_id": "TRV-2026-001",
                "employee_id": "EMP-384",
                "trip_type": "flight",
                "transaction_date": "10.04.2026",
                "origin_airport": "LHR",
                "destination_airport": "JFK",
                "travel_class": "Economy",
                "distance_km": None
            },
            # 2. Business class flight with provided distance
            {
                "travel_id": "TRV-2026-002",
                "employee_id": "EMP-092",
                "trip_type": "flight",
                "transaction_date": "12.04.2026",
                "origin_airport": "MUC",
                "destination_airport": "LHR",
                "travel_class": "Business",
                "distance_km": 941.5
            },
            # 3. Standard hotel stay
            {
                "travel_id": "TRV-2026-003",
                "employee_id": "EMP-092",
                "trip_type": "hotel",
                "transaction_date": "15.04.2026",
                "nights": 4,
                "hotel_country": "United Kingdom"
            },
            # 4. Standard ground transport
            {
                "travel_id": "TRV-2026-004",
                "employee_id": "EMP-384",
                "trip_type": "ground",
                "transaction_date": "11.04.2026",
                "distance_km": 24.8,
                "ground_type": "taxi"
            },
            # 5. Invalid Travel: Flight distance exceeding physical limits (warning/error test)
            {
                "travel_id": "TRV-2026-005",
                "employee_id": "EMP-111",
                "trip_type": "flight",
                "transaction_date": "18.04.2026",
                "origin_airport": "JFK",
                "destination_airport": "SIN",
                "travel_class": "First",
                "distance_km": 25000.0  # earth limit is ~20000 max
            },
            # 6. Invalid Travel: Hotel stay with negative nights (error test)
            {
                "travel_id": "TRV-2026-006",
                "employee_id": "EMP-222",
                "trip_type": "hotel",
                "transaction_date": "20.04.2026",
                "nights": -2,
                "hotel_country": "Germany"
            },
            # 7. Travel: Short flight warning
            {
                "travel_id": "TRV-2026-007",
                "employee_id": "EMP-333",
                "trip_type": "flight",
                "transaction_date": "22.04.2026",
                "origin_airport": "FRA",
                "destination_airport": "MUC",  # ~300km, but let's mock it very short 15km
                "travel_class": "Economy",
                "distance_km": 15.0
            }
        ]
        return Response(mock_data, status=status.HTTP_200_OK)
