from decimal import Decimal
from datetime import date
from django.test import TestCase
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from core.models import (
    Company, DataSource, RawUpload, RawRecord, NormalizedEmissionRecord,
    ValidationIssue, ReviewDecision, UnitConversionMap, EmissionFactor, AuditLog
)
from core.services.normalization import normalize_raw_record, calculate_haversine_distance
from core.services.validation import validate_record

class NormalizationAndValidationTests(TestCase):
    def setUp(self):
        # Create core lookup metadata
        self.company = Company.objects.create(name="Test Company")
        self.user = User.objects.create_user(username="testanalyst", password="password123")
        
        # Create data sources
        self.sap_source = DataSource.objects.create(
            company=self.company, name="SAP Export", source_type="sap_fuel"
        )
        self.utility_source = DataSource.objects.create(
            company=self.company, name="Utility Portal", source_type="utility_electricity"
        )
        self.travel_source = DataSource.objects.create(
            company=self.company, name="Travel API", source_type="corporate_travel"
        )

        # Create unit conversion maps
        UnitConversionMap.objects.create(from_unit="TO", to_unit="L", conversion_factor=Decimal("1000.0"))
        UnitConversionMap.objects.create(from_unit="L", to_unit="L", conversion_factor=Decimal("1.0"))
        UnitConversionMap.objects.create(from_unit="KWH", to_unit="KWH", conversion_factor=Decimal("1.0"))
        UnitConversionMap.objects.create(from_unit="KM", to_unit="KM", conversion_factor=Decimal("1.0"))

        # Create emission factors
        EmissionFactor.objects.create(activity_type="diesel", year=2026, factor=Decimal("2.5"))
        EmissionFactor.objects.create(activity_type="electricity", year=2026, factor=Decimal("0.2"))
        EmissionFactor.objects.create(activity_type="flight_economy", year=2026, factor=Decimal("0.15"))
        EmissionFactor.objects.create(activity_type="hotel_stay", year=2026, factor=Decimal("10.0"))

        # Create base upload
        self.raw_upload_sap = RawUpload.objects.create(
            company=self.company, data_source=self.sap_source, status="completed", uploaded_by=self.user
        )
        self.raw_upload_util = RawUpload.objects.create(
            company=self.company, data_source=self.utility_source, status="completed", uploaded_by=self.user
        )
        self.raw_upload_trv = RawUpload.objects.create(
            company=self.company, data_source=self.travel_source, status="completed", uploaded_by=self.user
        )

    def test_sap_normalization_and_validation(self):
        # 1. Clean SAP Record
        raw_rec_clean = RawRecord.objects.create(
            raw_upload=self.raw_upload_sap,
            row_index=1,
            raw_data={
                "Werk": "Plant-DE",
                "Material": "Diesel Fuel",
                "Menge": "100.00",
                "Einheit": "L",
                "Buchungsdatum": "15.04.2026",
                "Lieferant": "Shell AG"
            }
        )
        norm_rec = normalize_raw_record(raw_rec_clean)
        self.assertEqual(norm_rec.activity_type, "diesel")
        self.assertEqual(norm_rec.normalized_quantity, Decimal("100.00"))
        self.assertEqual(norm_rec.calculated_co2e, Decimal("250.00")) # 100 * 2.5
        self.assertEqual(norm_rec.validation_status, "valid")
        self.assertEqual(norm_rec.issues.count(), 0)

        # 2. Corrupt/Negative SAP Record
        raw_rec_neg = RawRecord.objects.create(
            raw_upload=self.raw_upload_sap,
            row_index=2,
            raw_data={
                "Werk": "Plant-DE",
                "Material": "Diesel Fuel",
                "Menge": "-50.00",
                "Einheit": "L",
                "Buchungsdatum": "16.04.2026",
                "Lieferant": "Shell AG"
            }
        )
        norm_rec_neg = normalize_raw_record(raw_rec_neg)
        self.assertEqual(norm_rec_neg.validation_status, "failed")
        self.assertTrue(norm_rec_neg.issues.filter(issue_type="negative_value").exists())

        # 3. Unit conversion (Tons -> Litres)
        raw_rec_tons = RawRecord.objects.create(
            raw_upload=self.raw_upload_sap,
            row_index=3,
            raw_data={
                "Werk": "Plant-DE",
                "Material": "Diesel Fuel",
                "Menge": "2.5",
                "Einheit": "TO",
                "Buchungsdatum": "17.04.2026",
                "Lieferant": "Shell AG"
            }
        )
        norm_rec_tons = normalize_raw_record(raw_rec_tons)
        self.assertEqual(norm_rec_tons.normalized_quantity, Decimal("2500.0")) # 2.5 * 1000
        self.assertEqual(norm_rec_tons.calculated_co2e, Decimal("6250.0")) # 2500 * 2.5
        self.assertEqual(norm_rec_tons.validation_status, "valid")

    def test_utility_overlapping_billing_cycles(self):
        # Record 1: March billing cycle
        raw_rec1 = RawRecord.objects.create(
            raw_upload=self.raw_upload_util,
            row_index=1,
            raw_data={
                "Meter_ID": "MTR-01",
                "Billing_Period": "2026-03-01 to 2026-03-31",
                "kWh_Consumption": "1000.0"
            }
        )
        norm_rec1 = normalize_raw_record(raw_rec1)
        self.assertEqual(norm_rec1.validation_status, "valid")

        # Record 2: Overlapping billing cycle (March 15 to April 15)
        raw_rec2 = RawRecord.objects.create(
            raw_upload=self.raw_upload_util,
            row_index=2,
            raw_data={
                "Meter_ID": "MTR-01",
                "Billing_Period": "2026-03-15 to 2026-04-15",
                "kWh_Consumption": "1500.0"
            }
        )
        norm_rec2 = normalize_raw_record(raw_rec2)
        self.assertEqual(norm_rec2.validation_status, "failed")
        self.assertTrue(norm_rec2.issues.filter(issue_type="overlapping_period").exists())

    def test_travel_distance_and_haversine(self):
        # Test direct Haversine formula calculation
        # London (LHR) -> New York (JFK) is ~5540 km
        dist = calculate_haversine_distance("LHR", "JFK")
        self.assertAlmostEqual(dist, 5540.17, delta=10.0)

        # Sync travel flight record with empty distance_km
        raw_rec = RawRecord.objects.create(
            raw_upload=self.raw_upload_trv,
            row_index=1,
            raw_data={
                "trip_type": "flight",
                "transaction_date": "2026-04-10",
                "origin_airport": "LHR",
                "destination_airport": "JFK",
                "travel_class": "Economy",
                "distance_km": ""
            }
        )
        norm_rec = normalize_raw_record(raw_rec)
        self.assertEqual(norm_rec.activity_type, "flight_economy")
        self.assertTrue(norm_rec.normalized_quantity > 5000)
        self.assertEqual(norm_rec.validation_status, "valid")

    def test_immutability_locking(self):
        raw_rec = RawRecord.objects.create(
            raw_upload=self.raw_upload_sap,
            row_index=1,
            raw_data={
                "Werk": "Plant-DE",
                "Material": "Diesel Fuel",
                "Menge": "100.00",
                "Einheit": "L",
                "Buchungsdatum": "15.04.2026",
                "Lieferant": "Shell AG"
            }
        )
        norm_rec = normalize_raw_record(raw_rec)
        self.assertFalse(norm_rec.is_locked)
        
        # Approve the record (sets review_status to approved and is_locked to True)
        norm_rec.review_status = "approved"
        norm_rec.save()
        self.assertTrue(norm_rec.is_locked)

        # Attempting to edit a locked record should fail at ORM level
        norm_rec.raw_quantity = Decimal("200.00")
        with self.assertRaises(ValidationError):
            norm_rec.save()

        # Bypassing with force_unlock works (for admins or system edits)
        norm_rec.save(force_unlock=True)
        self.assertEqual(norm_rec.raw_quantity, Decimal("200.00"))

    def test_locked_record_deletion_blocked(self):
        raw_rec = RawRecord.objects.create(
            raw_upload=self.raw_upload_sap,
            row_index=1,
            raw_data={
                "Werk": "Plant-DE",
                "Material": "Diesel Fuel",
                "Menge": "100.00",
                "Einheit": "L",
                "Buchungsdatum": "15.04.2026",
                "Lieferant": "Shell AG"
            }
        )
        norm_rec = normalize_raw_record(raw_rec)
        norm_rec.review_status = "approved"
        norm_rec.save()
        self.assertTrue(norm_rec.is_locked)

        # Deletion should raise ValidationError
        with self.assertRaises(ValidationError):
            norm_rec.delete()

        # Try to delete using queryset mass delete
        with self.assertRaises(ValidationError):
            NormalizedEmissionRecord.objects.filter(id=norm_rec.id).delete()

    def test_missing_and_zero_quantity_validation(self):
        # 1. Missing Menge (quantity) in SAP
        raw_rec_missing = RawRecord.objects.create(
            raw_upload=self.raw_upload_sap,
            row_index=1,
            raw_data={
                "Werk": "Plant-DE",
                "Material": "Diesel Fuel",
                "Menge": "",
                "Einheit": "L",
                "Buchungsdatum": "15.04.2026"
            }
        )
        norm_rec_missing = normalize_raw_record(raw_rec_missing)
        self.assertEqual(norm_rec_missing.validation_status, "failed")
        self.assertTrue(norm_rec_missing.issues.filter(issue_type="missing_quantity").exists())

        # 2. Zero Quantity in SAP
        raw_rec_zero = RawRecord.objects.create(
            raw_upload=self.raw_upload_sap,
            row_index=2,
            raw_data={
                "Werk": "Plant-DE",
                "Material": "Diesel Fuel",
                "Menge": "0.00",
                "Einheit": "L",
                "Buchungsdatum": "15.04.2026"
            }
        )
        norm_rec_zero = normalize_raw_record(raw_rec_zero)
        self.assertEqual(norm_rec_zero.validation_status, "failed")
        self.assertTrue(norm_rec_zero.issues.filter(issue_type="missing_quantity").exists())

    def test_unsupported_unit_conversion(self):
        # Unit "BAGS" does not have any conversion path in UnitConversionMap
        raw_rec_bad_unit = RawRecord.objects.create(
            raw_upload=self.raw_upload_sap,
            row_index=1,
            raw_data={
                "Werk": "Plant-DE",
                "Material": "Diesel Fuel",
                "Menge": "100.0",
                "Einheit": "BAGS",
                "Buchungsdatum": "15.04.2026"
            }
        )
        norm_rec_bad_unit = normalize_raw_record(raw_rec_bad_unit)
        self.assertEqual(norm_rec_bad_unit.validation_status, "failed")
        self.assertTrue(norm_rec_bad_unit.issues.filter(issue_type="unsupported_unit").exists())

    def test_corrupt_date_validation(self):
        raw_rec_bad_date = RawRecord.objects.create(
            raw_upload=self.raw_upload_sap,
            row_index=1,
            raw_data={
                "Werk": "Plant-DE",
                "Material": "Diesel Fuel",
                "Menge": "100.0",
                "Einheit": "L",
                "Buchungsdatum": "NOT-A-DATE"
            }
        )
        norm_rec_bad_date = normalize_raw_record(raw_rec_bad_date)
        self.assertEqual(norm_rec_bad_date.validation_status, "failed")
        self.assertTrue(norm_rec_bad_date.issues.filter(issue_type="invalid_date").exists())

    def test_crud_audit_signals(self):
        # Create an unlocked record manually (without bypass flag)
        rec = NormalizedEmissionRecord.objects.create(
            company=self.company,
            source_type="sap_fuel",
            scope_category=1,
            activity_type="diesel",
            raw_quantity=Decimal("10.0"),
            raw_unit="L",
            normalized_quantity=Decimal("10.0"),
            normalized_unit="L",
            emission_factor=Decimal("2.68"),
            calculated_co2e=Decimal("26.8"),
            transaction_date=date(2026, 4, 15)
        )
        
        # Verify CREATE log was generated by post_save signal
        create_log = AuditLog.objects.filter(target_id=rec.id, action="CREATE")
        self.assertTrue(create_log.exists())
        
        # Modify the record
        rec.raw_quantity = Decimal("15.0")
        rec.save()
        
        # Verify EDIT log was generated
        edit_log = AuditLog.objects.filter(target_id=rec.id, action="EDIT")
        self.assertTrue(edit_log.exists())
        
        # Delete the record (using force_unlock since it is not locked)
        rec_id = rec.id
        rec.delete()
        
        # Verify DELETE log was generated
        delete_log = AuditLog.objects.filter(target_id=rec_id, action="DELETE")
        self.assertTrue(delete_log.exists())

    def test_views_permission_class(self):
        from django.test import Client
        client = Client()
        
        # 1. When DEBUG = False (simulate production settings)
        with self.settings(DEBUG=False):
            res = client.get('/api/data-sources/')
            self.assertEqual(res.status_code, 403)
        
        # 2. When DEBUG = True (simulate local dev settings)
        with self.settings(DEBUG=True):
            res = client.get('/api/data-sources/')
            self.assertEqual(res.status_code, 200)
