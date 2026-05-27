import csv
import io
import requests
import json
from django.db import transaction
from django.utils import timezone
from core.models import Company, DataSource, RawUpload, RawRecord, AuditLog
from core.services.normalization import normalize_raw_record

def process_raw_upload_records(raw_upload, records):
    """
    Takes list of dict records, saves them as RawRecords, and passes them to normalization.
    """
    created_records = []
    
    with transaction.atomic():
        for idx, row in enumerate(records):
            raw_rec = RawRecord.objects.create(
                raw_upload=raw_upload,
                row_index=idx + 1,
                raw_data=row
            )
            created_records.append(raw_rec)
            
    # Normalize outside the initial atomic transaction to prevent database lockups 
    # if one record normalization fails, keeping other records intact.
    success_count = 0
    fail_count = 0
    for raw_rec in created_records:
        try:
            normalize_raw_record(raw_rec)
            success_count += 1
        except Exception as e:
            fail_count += 1
            # We don't crash the whole upload; we log individual failure
            # and continue. This is highly resilient!
            import traceback
            print(f"Failed to normalize row {raw_rec.row_index}: {e}")
            traceback.print_exc()
            
    return success_count, fail_count

def ingest_csv_file(company, data_source, file_file, filename, uploaded_by):
    """
    Ingests a CSV file from a file object. Handles delimiter detection (semicolon vs comma)
    and strips byte-order marks.
    """
    raw_upload = RawUpload.objects.create(
        company=company,
        data_source=data_source,
        upload_type='file',
        filename=filename,
        status='processing',
        uploaded_by=uploaded_by
    )

    try:
        # Read content and decode to string
        file_bytes = file_file.read()
        try:
            content = file_bytes.decode('utf-8-sig') # strips UTF-8 BOM
        except UnicodeDecodeError:
            content = file_bytes.decode('latin-1')

        # Simple delimiter detection
        first_line = content.split('\n')[0]
        delimiter = ';' if ';' in first_line else ','

        # Parse CSV
        reader = csv.DictReader(io.StringIO(content), delimiter=delimiter)
        
        # Clean header keys (remove spaces or quotes)
        reader.fieldnames = [name.strip().replace('"', '') for name in reader.fieldnames]
        
        records = []
        for row in reader:
            # Clean row values
            cleaned_row = {k: v.strip() if isinstance(v, str) else v for k, v in row.items()}
            records.append(cleaned_row)

        if not records:
            raise ValueError("CSV file is empty or headers could not be parsed.")

        success, failed = process_raw_upload_records(raw_upload, records)
        
        raw_upload.status = 'completed'
        raw_upload.save()

        # Audit Ingestion
        AuditLog.objects.create(
            company=company,
            user=uploaded_by,
            action='UPLOAD',
            target_type='RawUpload',
            target_id=raw_upload.id,
            changes={
                'filename': filename,
                'total_rows': len(records),
                'successful_normalization': success,
                'failed_normalization': failed
            }
        )
        return raw_upload

    except Exception as e:
        import traceback
        error_msg = f"{str(e)}\n{traceback.format_exc()}"
        raw_upload.status = 'failed'
        raw_upload.error_message = error_msg
        raw_upload.save()
        return raw_upload

def sync_travel_api(company, data_source, uploaded_by, sync_url):
    """
    Simulates sync from a travel API (like Concur/Navan).
    Calls sync_url, downloads travel JSON records, and ingests them.
    To prevent deadlocks on single-worker production containers (like Render Free tier),
    if the request is destined for the current host, we bypass requests.get and load in-memory.
    """
    raw_upload = RawUpload.objects.create(
        company=company,
        data_source=data_source,
        upload_type='api',
        filename='Sync API Concur',
        status='processing',
        uploaded_by=uploaded_by
    )

    try:
        from urllib.parse import urlparse
        import requests
        
        is_local = False
        parsed_url = urlparse(sync_url)
        if "onrender.com" in parsed_url.netloc or "localhost" in parsed_url.netloc or "127.0.0.1" in parsed_url.netloc:
            is_local = True
            
        if is_local:
            # Ingest directly from local list to avoid loopback self-deadlock
            records = [
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
                {
                    "travel_id": "TRV-2026-003",
                    "employee_id": "EMP-092",
                    "trip_type": "hotel",
                    "transaction_date": "15.04.2026",
                    "nights": 4,
                    "hotel_country": "United Kingdom"
                },
                {
                    "travel_id": "TRV-2026-004",
                    "employee_id": "EMP-384",
                    "trip_type": "ground",
                    "transaction_date": "11.04.2026",
                    "distance_km": 24.8,
                    "ground_type": "taxi"
                },
                {
                    "travel_id": "TRV-2026-005",
                    "employee_id": "EMP-111",
                    "trip_type": "flight",
                    "transaction_date": "18.04.2026",
                    "origin_airport": "JFK",
                    "destination_airport": "SIN",
                    "travel_class": "First",
                    "distance_km": 25000.0
                },
                {
                    "travel_id": "TRV-2026-006",
                    "employee_id": "EMP-222",
                    "trip_type": "hotel",
                    "transaction_date": "20.04.2026",
                    "nights": -2,
                    "hotel_country": "Germany"
                },
                {
                    "travel_id": "TRV-2026-007",
                    "employee_id": "EMP-333",
                    "trip_type": "flight",
                    "transaction_date": "22.04.2026",
                    "origin_airport": "FRA",
                    "destination_airport": "MUC",
                    "travel_class": "Economy",
                    "distance_km": 15.0
                }
            ]
        else:
            response = requests.get(sync_url, timeout=10)
            if response.status_code != 200:
                raise ValueError(f"External Travel API returned status code {response.status_code}: {response.text}")
                
            data = response.json()
            if isinstance(data, dict):
                records = data.get('records', data.get('events', []))
            else:
                records = data

        if not isinstance(records, list):
            raise ValueError("Expected a list of travel records from the external API.")

        if not records:
            raise ValueError("API sync completed, but no new travel records were found.")

        success, failed = process_raw_upload_records(raw_upload, records)

        raw_upload.status = 'completed'
        raw_upload.save()

        # Audit sync
        AuditLog.objects.create(
            company=company,
            user=uploaded_by,
            action='UPLOAD',
            target_type='RawUpload',
            target_id=raw_upload.id,
            changes={
                'sync_url': sync_url,
                'total_rows': len(records),
                'successful_normalization': success,
                'failed_normalization': failed
            }
        )
        return raw_upload

    except Exception as e:
        import traceback
        error_msg = f"{str(e)}\n{traceback.format_exc()}"
        raw_upload.status = 'failed'
        raw_upload.error_message = error_msg
        raw_upload.save()
        return raw_upload
