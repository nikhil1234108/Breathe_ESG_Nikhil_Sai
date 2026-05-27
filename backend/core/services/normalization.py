import re
from decimal import Decimal
from django.core.exceptions import ValidationError
from core.models import (
    NormalizedEmissionRecord, RawRecord, UnitConversionMap,
    EmissionFactor, AuditLog, ValidationIssue
)
from core.services.validation import validate_record
from core.services.utils import parse_date, calculate_haversine_distance, get_conversion_factor, set_bypass_signals

def get_emission_factor(activity_type, year):
    """
    Looks up the emission factor. Defaults to the closest year if exact year is missing.
    """
    try:
        ef = EmissionFactor.objects.get(activity_type=activity_type, year=year)
        return ef.factor
    except EmissionFactor.DoesNotExist:
        # Fallback: find any factor for this activity type
        efs = EmissionFactor.objects.filter(activity_type=activity_type).order_by('-year')
        if efs.exists():
            return efs.first().factor
        # Hardcoded fallback values to prevent system crashes on unconfigured EFs
        fallback_factors = {
            'diesel': Decimal('2.684'),        # kg CO2e per Litre (DEFRA standard)
            'petrol': Decimal('2.301'),        # kg CO2e per Litre
            'heating_oil': Decimal('2.540'),    # kg CO2e per Litre
            'electricity': Decimal('0.207'),    # kg CO2e per kWh (grid average)
            'flight_economy': Decimal('0.150'), # kg CO2e per passenger-km
            'flight_business': Decimal('0.440'),# kg CO2e per passenger-km
            'flight_first': Decimal('0.600'),   # kg CO2e per passenger-km
            'hotel_stay': Decimal('10.400'),    # kg CO2e per night (room basis)
            'ground_transport': Decimal('0.170')# kg CO2e per km (average car)
        }
        return fallback_factors.get(activity_type, Decimal('0.0'))

def normalize_raw_record(raw_record: RawRecord) -> NormalizedEmissionRecord:
    """
    Normalizes a RawRecord into a NormalizedEmissionRecord.
    Performs field extraction, date parsing, unit conversion, and emission factor calculations.
    """
    set_bypass_signals(True)
    try:
        upload = raw_record.raw_upload
        company = upload.company
        source_type = upload.data_source.source_type
        data = raw_record.raw_data

        # Initialize variables with defaults
        scope_category = 1
        activity_type = 'unknown'
        facility_or_plant = ''
        transaction_date = None
        billing_period_start = None
        billing_period_end = None
        
        raw_quantity_str = '0'
        raw_unit = 'unknown'
        target_unit = 'unknown'
        
        # 1. Source-Specific Extraction Logic
        if source_type == 'sap_fuel':
            scope_category = 1
            facility_or_plant = data.get('Werk', data.get('Werk_Code', ''))
            raw_quantity_str = data.get('Menge', '0')
            raw_unit = data.get('Einheit', 'L')
            
            # Map material to internal activity type
            material = str(data.get('Material', data.get('Material_Type', ''))).lower().strip()
            if 'diesel' in material:
                activity_type = 'diesel'
                target_unit = 'L'
            elif 'benzin' in material or 'petrol' in material:
                activity_type = 'petrol'
                target_unit = 'L'
            elif 'heiz' in material or 'heating' in material:
                activity_type = 'heating_oil'
                target_unit = 'L'
            else:
                activity_type = 'diesel' # Default fallback
                target_unit = 'L'
                
            # Parse posting date
            posting_date_str = data.get('Buchungsdatum', data.get('Posting_Date', ''))
            transaction_date = parse_date(posting_date_str)
            if not transaction_date:
                # Set to upload date as placeholder, validation will flag this as invalid_date
                transaction_date = upload.created_at.date()

        elif source_type == 'utility_electricity':
            scope_category = 2
            activity_type = 'electricity'
            target_unit = 'kWh'
            facility_or_plant = data.get('Meter_ID', '')
            raw_quantity_str = data.get('kWh_Consumption', '0')
            raw_unit = 'kWh' # Default
            
            # Parse billing period
            # Period is usually a string e.g. "2026-03-15 to 2026-04-14" or "03/15/2026 - 04/14/2026"
            period_str = data.get('Billing_Period', '')
            if period_str:
                parts = re.split(r'\s+(?:to|-)\s+', str(period_str))
                if len(parts) == 2:
                    billing_period_start = parse_date(parts[0])
                    billing_period_end = parse_date(parts[1])
                    transaction_date = billing_period_end
                else:
                    transaction_date = parse_date(period_str)
            
            if not transaction_date:
                transaction_date = upload.created_at.date()

        elif source_type == 'corporate_travel':
            scope_category = 3
            trip_type = str(data.get('trip_type', '')).lower().strip()
            transaction_date_str = data.get('transaction_date', '')
            transaction_date = parse_date(transaction_date_str)
            if not transaction_date:
                transaction_date = upload.created_at.date()
                
            if trip_type == 'flight':
                travel_class = str(data.get('travel_class', 'Economy')).lower().strip()
                if 'business' in travel_class:
                    activity_type = 'flight_business'
                elif 'first' in travel_class:
                    activity_type = 'flight_first'
                else:
                    activity_type = 'flight_economy'
                    
                raw_unit = 'km'
                target_unit = 'km'
                
                origin = data.get('origin_airport', '')
                destination = data.get('destination_airport', '')
                facility_or_plant = f"{origin}->{destination}"
                
                # Fetch distance, calculate if missing
                dist_val = data.get('distance_km')
                if dist_val is not None and str(dist_val).strip() != '' and float(dist_val) > 0:
                    raw_quantity_str = str(dist_val)
                else:
                    # Calculate from airport codes
                    calc_dist = calculate_haversine_distance(origin, destination)
                    raw_quantity_str = str(calc_dist)
                    
            elif trip_type == 'hotel':
                activity_type = 'hotel_stay'
                raw_quantity_str = data.get('nights', '0')
                raw_unit = 'nights'
                target_unit = 'nights'
                facility_or_plant = data.get('hotel_country', '')
                
            elif trip_type == 'ground':
                activity_type = 'ground_transport'
                raw_quantity_str = data.get('distance_km', '0')
                raw_unit = 'km'
                target_unit = 'km'
                facility_or_plant = data.get('ground_type', 'taxi')
                
            else:
                activity_type = 'ground_transport'
                raw_quantity_str = '0'
                raw_unit = 'km'
                target_unit = 'km'

        # Convert string quantity safely to Decimal
        try:
            # Clean number representation (German uses commas for decimals sometimes, e.g. "500,50")
            clean_qty_str = str(raw_quantity_str).replace(',', '.').strip()
            raw_quantity = Decimal(clean_qty_str)
        except Exception:
            raw_quantity = Decimal('0')

        # 2. Unit Conversion
        conv_factor = get_conversion_factor(raw_unit, target_unit)
        if conv_factor is not None:
            normalized_quantity = raw_quantity * conv_factor
        else:
            # Fallback if no conversion path: set factor to 1.0 but validate_record will capture the mismatch
            conv_factor = Decimal('1.0')
            normalized_quantity = raw_quantity
            
        # 3. Emission Factor Lookup & CO2e Calculation
        year = transaction_date.year if transaction_date else upload.created_at.year
        ef_value = get_emission_factor(activity_type, year)
        calculated_co2e = normalized_quantity * ef_value

        # 4. Create and Save the Normalized Record
        # Look for existing record linked to this raw record to support overwriting during reprocessing
        record, created = NormalizedEmissionRecord.objects.get_or_create(
            company=company,
            raw_record=raw_record,
            defaults={
                'source_type': source_type,
                'scope_category': scope_category,
                'activity_type': activity_type,
                'facility_or_plant': facility_or_plant,
                'transaction_date': transaction_date,
                'billing_period_start': billing_period_start,
                'billing_period_end': billing_period_end,
                'raw_quantity': raw_quantity,
                'raw_unit': raw_unit,
                'normalized_quantity': normalized_quantity,
                'normalized_unit': target_unit,
                'emission_factor': ef_value,
                'calculated_co2e': calculated_co2e,
                'validation_status': 'valid',
                'review_status': 'pending',
                'is_locked': False
            }
        )

        if not created:
            # If it already exists and is locked, we CANNOT update it.
            # This prevents accidental overwriting of audit-locked records.
            if record.is_locked:
                return record
                
            # Update existing
            record.source_type = source_type
            record.scope_category = scope_category
            record.activity_type = activity_type
            record.facility_or_plant = facility_or_plant
            record.transaction_date = transaction_date
            record.billing_period_start = billing_period_start
            record.billing_period_end = billing_period_end
            record.raw_quantity = raw_quantity
            record.raw_unit = raw_unit
            record.normalized_quantity = normalized_quantity
            record.normalized_unit = target_unit
            record.emission_factor = ef_value
            record.calculated_co2e = calculated_co2e
            record.save()

        # 5. Trigger Validation Engine
        validate_record(record)
        
        # 6. Audit Log
        AuditLog.objects.create(
            company=company,
            action='NORMALIZE',
            target_type='NormalizedEmissionRecord',
            target_id=record.id,
            changes={
                'action': 'normalize_raw_record',
                'created': created,
                'raw_quantity': str(raw_quantity),
                'raw_unit': raw_unit,
                'normalized_quantity': str(normalized_quantity),
                'normalized_unit': target_unit,
                'calculated_co2e': str(calculated_co2e),
                'validation_status': record.validation_status
            }
        )

        return record
    finally:
        set_bypass_signals(False)
