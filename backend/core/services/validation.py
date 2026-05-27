from django.db.models import Q
from core.models import NormalizedEmissionRecord, ValidationIssue

def validate_record(record: NormalizedEmissionRecord):
    """
    Runs the validation engine on a NormalizedEmissionRecord.
    Saves any ValidationIssue instances and updates the validation_status on the record.
    """
    # Clear existing issues first (unless locked, but we shouldn't run this on locked records anyway)
    if record.is_locked:
        return
        
    record.issues.all().delete()
    issues_to_create = []

    # 1. Negative or Missing quantity check
    is_qty_missing = False
    if record.raw_record:
        raw_data = record.raw_record.raw_data
        qty_val = None
        if record.source_type == 'sap_fuel':
            qty_val = raw_data.get('Menge')
        elif record.source_type == 'utility_electricity':
            qty_val = raw_data.get('kWh_Consumption')
        elif record.source_type == 'corporate_travel':
            trip_type = str(raw_data.get('trip_type', '')).lower().strip()
            if trip_type == 'flight':
                qty_val = raw_data.get('distance_km')
                # If distance is empty and we can't calculate it from airports, then it's missing
                if (qty_val is None or str(qty_val).strip() == '') and not raw_data.get('origin_airport') and not raw_data.get('destination_airport'):
                    is_qty_missing = True
            elif trip_type == 'hotel':
                qty_val = raw_data.get('nights')
            elif trip_type == 'ground':
                qty_val = raw_data.get('distance_km')
        
        if qty_val is None or str(qty_val).strip() == '':
            is_flight_calculated = (record.source_type == 'corporate_travel' and 
                                    trip_type == 'flight' and 
                                    raw_data.get('origin_airport') and 
                                    raw_data.get('destination_airport'))
            if not is_flight_calculated:
                is_qty_missing = True

    if is_qty_missing or record.raw_quantity == 0:
        issues_to_create.append(ValidationIssue(
            emission_record=record,
            issue_type='missing_quantity',
            severity='error',
            message="Quantity is missing, empty, or zero."
        ))
    elif record.raw_quantity < 0:
        issues_to_create.append(ValidationIssue(
            emission_record=record,
            issue_type='negative_value',
            severity='error',
            message=f"Raw quantity ({record.raw_quantity}) cannot be negative."
        ))

    # 2. Missing raw unit check or Unsupported conversion
    if not record.raw_unit or str(record.raw_unit).strip() == '':
        issues_to_create.append(ValidationIssue(
            emission_record=record,
            issue_type='missing_unit',
            severity='error',
            message="Source unit is missing or empty."
        ))
    else:
        from core.services.utils import get_conversion_factor
        target_unit = record.normalized_unit
        conv_factor = get_conversion_factor(record.raw_unit, target_unit)
        if conv_factor is None:
            issues_to_create.append(ValidationIssue(
                emission_record=record,
                issue_type='unsupported_unit',
                severity='error',
                message=f"Unsupported unit conversion: no path from '{record.raw_unit}' to '{target_unit}' in UnitConversionMap."
            ))

    # 3. Original date corruption check and Date ordering check
    is_date_corrupt = False
    if record.raw_record:
        from core.services.utils import parse_date
        raw_data = record.raw_record.raw_data
        
        if record.source_type == 'sap_fuel':
            date_str = raw_data.get('Buchungsdatum', raw_data.get('Posting_Date', ''))
            if not parse_date(date_str):
                is_date_corrupt = True
        elif record.source_type == 'utility_electricity':
            period_str = raw_data.get('Billing_Period', '')
            if period_str:
                import re
                parts = re.split(r'\s+(?:to|-)\s+', str(period_str))
                if len(parts) == 2:
                    if not parse_date(parts[0]) or not parse_date(parts[1]):
                        is_date_corrupt = True
                else:
                    if not parse_date(period_str):
                        is_date_corrupt = True
            else:
                is_date_corrupt = True
        elif record.source_type == 'corporate_travel':
            date_str = raw_data.get('transaction_date', '')
            if not parse_date(date_str):
                is_date_corrupt = True

    if is_date_corrupt:
        issues_to_create.append(ValidationIssue(
            emission_record=record,
            issue_type='invalid_date',
            severity='error',
            message="The transaction date or billing period is missing or formatted incorrectly in the source record."
        ))

    if record.billing_period_start and record.billing_period_end:
        if record.billing_period_start > record.billing_period_end:
            issues_to_create.append(ValidationIssue(
                emission_record=record,
                issue_type='invalid_date',
                severity='error',
                message=f"Billing period start date ({record.billing_period_start}) cannot be after end date ({record.billing_period_end})."
            ))
        
        # Unusually long billing period warning
        delta_days = (record.billing_period_end - record.billing_period_start).days
        if delta_days > 100:
            issues_to_create.append(ValidationIssue(
                emission_record=record,
                issue_type='out_of_bounds',
                severity='warning',
                message=f"Billing period is unusually long ({delta_days} days). Typical utility periods are 28-35 days."
            ))

    # 4. Out of bounds checks
    if record.source_type == 'sap_fuel':
        # Diesel quantity check
        if record.activity_type == 'diesel' and record.normalized_quantity > 50000:
            issues_to_create.append(ValidationIssue(
                emission_record=record,
                issue_type='out_of_bounds',
                severity='warning',
                message=f"Fuel quantity ({record.normalized_quantity} L) exceeds typical batch refueling threshold of 50,000 L."
            ))
    
    elif record.source_type == 'utility_electricity':
        # Electricity quantity check
        if record.normalized_quantity > 1000000:
            issues_to_create.append(ValidationIssue(
                emission_record=record,
                issue_type='out_of_bounds',
                severity='warning',
                message=f"Electricity consumption ({record.normalized_quantity} kWh) exceeds building threshold of 1,000,000 kWh per cycle."
            ))
            
    elif record.source_type == 'corporate_travel':
        # Flight distance check
        if record.activity_type.startswith('flight') and record.normalized_quantity > 20000:
            issues_to_create.append(ValidationIssue(
                emission_record=record,
                issue_type='out_of_bounds',
                severity='error',
                message=f"Flight distance ({record.normalized_quantity} km) exceeds Earth's circumference distance limits (> 20,000 km)."
            ))
        elif record.activity_type.startswith('flight') and record.normalized_quantity < 50:
            issues_to_create.append(ValidationIssue(
                emission_record=record,
                issue_type='out_of_bounds',
                severity='warning',
                message=f"Flight distance is unusually short ({record.normalized_quantity} km). Check if this was ground transport instead."
            ))

    # 5. Duplicate transaction detection
    # Duplicate defined as: same company, same source_type, same activity_type, same transaction_date, same raw_quantity, same facility_or_plant
    duplicate_query = NormalizedEmissionRecord.objects.filter(
        company=record.company,
        source_type=record.source_type,
        activity_type=record.activity_type,
        transaction_date=record.transaction_date,
        raw_quantity=record.raw_quantity,
        facility_or_plant=record.facility_or_plant
    ).exclude(id=record.id)

    if duplicate_query.exists():
        issues_to_create.append(ValidationIssue(
            emission_record=record,
            issue_type='duplicate',
            severity='warning',
            message=f"Possible duplicate record. An identical emission record of {record.raw_quantity} {record.raw_unit} on {record.transaction_date} already exists."
        ))

    # 6. Overlapping billing cycles check (for Utility Electricity)
    if record.source_type == 'utility_electricity' and record.billing_period_start and record.billing_period_end and record.facility_or_plant:
        overlapping_query = NormalizedEmissionRecord.objects.filter(
            company=record.company,
            source_type='utility_electricity',
            facility_or_plant=record.facility_or_plant,
            billing_period_start__isnull=False,
            billing_period_end__isnull=False
        ).filter(
            # Overlap logic: StartA < EndB AND EndA > StartB
            billing_period_start__lt=record.billing_period_end,
            billing_period_end__gt=record.billing_period_start
        ).exclude(id=record.id)

        if overlapping_query.exists():
            overlap_details = ", ".join([f"{o.billing_period_start} to {o.billing_period_end}" for o in overlapping_query[:2]])
            issues_to_create.append(ValidationIssue(
                emission_record=record,
                issue_type='overlapping_period',
                severity='error',
                message=f"Billing period overlaps with existing record(s) for meter '{record.facility_or_plant}' ({overlap_details})."
            ))

    # Save all issues in database
    if issues_to_create:
        ValidationIssue.objects.bulk_create(issues_to_create)
        
        # Decide overall status: If there's any error, status is 'failed'. Otherwise, 'suspicious'.
        has_error = any(issue.severity == 'error' for issue in issues_to_create)
        record.validation_status = 'failed' if has_error else 'suspicious'
    else:
        record.validation_status = 'valid'

    # Save the updated validation status
    record.save()
