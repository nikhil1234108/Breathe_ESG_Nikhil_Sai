import math
import re
import threading
from datetime import datetime
from decimal import Decimal
from core.models import UnitConversionMap

# Thread-local storage to temporarily bypass automatic signal-based audit logging
_local = threading.local()

def set_bypass_signals(value: bool):
    _local.bypass_signals = value

def get_bypass_signals() -> bool:
    return getattr(_local, 'bypass_signals', False)

# A static mapping of airport codes to coordinates (lat, lon) for our Haversine distance calculator
AIRPORT_COORDINATES = {
    'JFK': (40.6398, -73.7789),   # New York, USA
    'LAX': (33.9416, -118.4085),  # Los Angeles, USA
    'LHR': (51.4700, -0.4543),    # London, UK
    'MUC': (48.3538, 11.7861),    # Munich, Germany
    'CDG': (49.0097, 2.5479),     # Paris, France
    'DXB': (25.2532, 55.3657),    # Dubai, UAE
    'SIN': (1.3644, 103.9915),    # Singapore
    'NRT': (35.7767, 140.3864),   # Tokyo, Japan
    'SYD': (-33.9461, 151.1772),  # Sydney, Australia
    'DEL': (28.5562, 77.1000),    # Delhi, India
    'FRA': (50.0379, 8.5622),     # Frankfurt, Germany
}

def calculate_haversine_distance(origin, destination):
    """
    Calculates the great-circle distance between two airport codes in kilometers using the Haversine formula.
    Returns 0.0 if any airport code is unknown.
    """
    if origin not in AIRPORT_COORDINATES or destination not in AIRPORT_COORDINATES:
        return 0.0
        
    lat1, lon1 = AIRPORT_COORDINATES[origin]
    lat2, lon2 = AIRPORT_COORDINATES[destination]
    
    # Radius of the Earth in km
    R = 6371.0
    
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    
    a = math.sin(delta_phi / 2.0)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0)**2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    
    distance = R * c
    return round(distance, 2)

def parse_date(date_str):
    """
    Tries to parse mixed date formats (e.g. '25.05.2026', '2026/05/25', '2026-05-25') into a date object.
    Returns None if parsing fails.
    """
    if not date_str:
        return None
        
    date_str = str(date_str).strip()
    
    formats = [
        '%d.%m.%Y',  # German DD.MM.YYYY
        '%Y/%m/%d',  # YYYY/MM/DD
        '%Y-%m-%d',  # Standard ISO
        '%d-%m-%Y',  # DD-MM-YYYY
        '%d/%m/%Y',  # DD/MM/YYYY
        '%Y%m%d',    # SAP flat file YYYYMMDD
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
            
    return None

def get_conversion_factor(from_unit, to_unit):
    """
    Looks up the unit conversion factor. Returns 1.0 if units are the same.
    """
    if not from_unit or not to_unit:
        return None
        
    from_unit = from_unit.strip().upper()
    to_unit = to_unit.strip().upper()
    
    if from_unit == to_unit:
        return Decimal('1.0')
        
    try:
        conv = UnitConversionMap.objects.get(from_unit=from_unit, to_unit=to_unit)
        return conv.conversion_factor
    except UnitConversionMap.DoesNotExist:
        # Check reverse conversion just in case
        try:
            conv = UnitConversionMap.objects.get(from_unit=to_unit, to_unit=from_unit)
            return Decimal('1.0') / conv.conversion_factor
        except UnitConversionMap.DoesNotExist:
            return None
