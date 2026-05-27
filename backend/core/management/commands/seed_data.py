import os
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from core.models import Company, UserProfile, DataSource, UnitConversionMap, EmissionFactor
from core.services.ingestion import ingest_csv_file, sync_travel_api

class Command(BaseCommand):
    help = "Seeds database with lookup mappings, default company, user accounts, and creates realistic sample files."

    def handle(self, *args, **options):
        self.stdout.write("Seeding data...")

        # 1. Company
        company, _ = Company.objects.get_or_create(name="Acme Industrial Corp")
        self.stdout.write(f"Company: {company.name}")

        # 2. Users & Profiles
        users_to_create = [
            ("analyst", "password123", "analyst"),
            ("auditor", "password123", "auditor"),
            ("admin", "password123", "admin"),
        ]
        
        for username, pwd, role in users_to_create:
            user, created = User.objects.get_or_create(username=username)
            if created:
                user.set_password(pwd)
                user.is_staff = (role == 'admin')
                user.is_superuser = (role == 'admin')
                user.save()
            
            UserProfile.objects.get_or_create(
                user=user,
                defaults={'company': company, 'role': role}
            )
            self.stdout.write(f"User: {username} ({role})")

        # 3. Data Sources
        sources = [
            ("SAP Fuel & Procurement CSV Export", "sap_fuel"),
            ("Utility Electricity CSV Portal Export", "utility_electricity"),
            ("Navan Travel REST API Sync", "corporate_travel"),
        ]
        for name, source_type in sources:
            DataSource.objects.get_or_create(
                company=company,
                source_type=source_type,
                defaults={'name': name, 'active': True}
            )
            self.stdout.write(f"Data Source: {name}")

        # 4. Unit Conversions
        conversions = [
            # Fuel
            ("L", "L", Decimal("1.0")),
            ("LITRES", "L", Decimal("1.0")),
            ("TO", "L", Decimal("1190.0")),    # Metric tons to Litres for fuel
            ("KG", "L", Decimal("1.19")),      # kg to Litres for fuel
            ("M3", "L", Decimal("1000.0")),    # cubic meters to Litres
            # Electricity
            ("KWH", "KWH", Decimal("1.0")),
            ("MWH", "KWH", Decimal("1000.0")),
            # Travel
            ("KM", "KM", Decimal("1.0")),
            ("MILE", "KM", Decimal("1.60934")),
            ("NIGHTS", "NIGHTS", Decimal("1.0")),
        ]
        for from_u, to_u, factor in conversions:
            UnitConversionMap.objects.update_or_create(
                from_unit=from_u,
                to_unit=to_u,
                defaults={'conversion_factor': factor}
            )
        self.stdout.write("Seeded unit conversion mappings.")

        # 5. Emission Factors (DEFRA & EPA 2025/2026 data)
        factors = [
            ("diesel", 2025, Decimal("2.684"), "DEFRA 2025"),
            ("diesel", 2026, Decimal("2.680"), "DEFRA 2026"),
            ("petrol", 2025, Decimal("2.301"), "DEFRA 2025"),
            ("petrol", 2026, Decimal("2.298"), "DEFRA 2026"),
            ("heating_oil", 2025, Decimal("2.540"), "DEFRA 2025"),
            ("heating_oil", 2026, Decimal("2.535"), "DEFRA 2026"),
            ("electricity", 2025, Decimal("0.207"), "EPA eGRID 2025"),
            ("electricity", 2026, Decimal("0.198"), "EPA eGRID 2026"),
            ("flight_economy", 2025, Decimal("0.150"), "DEFRA 2025"),
            ("flight_economy", 2026, Decimal("0.148"), "DEFRA 2026"),
            ("flight_business", 2025, Decimal("0.440"), "DEFRA 2025"),
            ("flight_business", 2026, Decimal("0.435"), "DEFRA 2026"),
            ("flight_first", 2025, Decimal("0.600"), "DEFRA 2025"),
            ("flight_first", 2026, Decimal("0.590"), "DEFRA 2026"),
            ("hotel_stay", 2025, Decimal("10.40"), "DEFRA 2025 (Room Night Average)"),
            ("hotel_stay", 2026, Decimal("10.20"), "DEFRA 2026 (Room Night Average)"),
            ("ground_transport", 2025, Decimal("0.170"), "DEFRA 2025"),
            ("ground_transport", 2026, Decimal("0.165"), "DEFRA 2026"),
        ]
        for act_type, year, factor, ref in factors:
            EmissionFactor.objects.update_or_create(
                activity_type=act_type,
                year=year,
                defaults={'factor': factor, 'source_reference': ref}
            )
        self.stdout.write("Seeded GHG emission factors.")

        # 6. Generate Sample Ingestion Files
        sample_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "sample_data")
        os.makedirs(sample_dir, exist_ok=True)

        # SAP Messy CSV File (Enlarged with high quality realistic test data)
        sap_file = os.path.join(sample_dir, "sap_procurement_germany.csv")
        sap_data = (
            "Werk;Material;Menge;Einheit;Buchungsdatum;Kostenstelle;Lieferant\n"
            # Q1 2026 - Clean
            "1010;Diesel Kraftstoff;1200,50;L;15.01.2026;CC-LOG-01;Aral AG\n"
            "1010;Heizöl;5,00;TO;18.01.2026;CC-FAC-01;Shell Deutschland\n"
            "1020;Diesel Kraftstoff;850,00;L;20.01.2026;CC-LOG-02;Aral AG\n"
            "1010;Benzin;400,00;L;25.01.2026;CC-LOG-01;TotalEnergies\n"
            # Q2 2026 - Clean
            "1010;Diesel Kraftstoff;1400,00;L;15.04.2026;CC-LOG-01;Aral AG\n"
            "1010;Heizöl;4,50;TO;18.04.2026;CC-FAC-01;Shell Deutschland\n"
            "1020;Diesel Kraftstoff;25000,00;L;20.04.2026;CC-LOG-02;Aral AG\n"
            "1010;Benzin;350,00;L;25.04.2026;CC-LOG-01;TotalEnergies\n"
            # Q3 2026 - Clean
            "1010;Diesel Kraftstoff;1150,00;L;15.07.2026;CC-LOG-01;Aral AG\n"
            "1010;Heizöl;6,20;TO;18.07.2026;CC-FAC-01;Shell Deutschland\n"
            "1020;Diesel Kraftstoff;900,00;L;20.07.2026;CC-LOG-02;Aral AG\n"
            "1010;Benzin;480,00;L;25.07.2026;CC-LOG-01;TotalEnergies\n"
            # Q4 2026 - Clean
            "1010;Diesel Kraftstoff;1350,00;L;15.10.2026;CC-LOG-01;Aral AG\n"
            "1010;Heizöl;5,80;TO;18.10.2026;CC-FAC-01;Shell Deutschland\n"
            "1020;Diesel Kraftstoff;920,00;L;20.10.2026;CC-LOG-02;Aral AG\n"
            "1010;Benzin;410,00;L;25.10.2026;CC-LOG-01;TotalEnergies\n"
            # Anomalies for validation testing
            "1020;Diesel Kraftstoff;25000,00;L;20.04.2026;CC-LOG-02;Aral AG\n" # Duplicate row test
            "1010;Diesel Kraftstoff;-200,00;L;26.04.2026;CC-LOG-01;Aral AG\n" # Negative quantity error test
            "1020;Diesel Kraftstoff;500,00;L;INVALID_DATE;CC-LOG-02;Aral AG\n" # Invalid date error test
            "1010;Diesel Kraftstoff;75000,00;L;28.04.2026;CC-LOG-01;Shell Deutschland\n" # Out of bounds threshold warning test (>50,000 L)
            "1010;Diesel Kraftstoff;;L;29.04.2026;CC-LOG-01;Shell Deutschland\n" # Missing quantity error test
            "1010;Diesel Kraftstoff;150,00;BAGS;30.04.2026;CC-LOG-01;TotalEnergies\n" # Unsupported unit conversion test
        )
        with open(sap_file, "w", encoding="utf-8") as f:
            f.write(sap_data)
        self.stdout.write(f"Created sample SAP file at: {sap_file}")

        # Utility CSV File (Enlarged with high quality realistic test data)
        utility_file = os.path.join(sample_dir, "utility_electricity_bills.csv")
        utility_data = (
            "Meter_ID,Billing_Period,kWh_Consumption,Tariff,Peak_Demand_kW\n"
            # Clean records
            "MTR-HQ-01,2026-01-01 to 2026-01-31,22000.0,Commercial-Standard,42.0\n"
            "MTR-HQ-01,2026-02-01 to 2026-02-28,21500.5,Commercial-Standard,41.2\n"
            "MTR-HQ-01,2026-03-01 to 2026-03-31,24500.8,Commercial-Standard,45.2\n"
            "MTR-HQ-01,2026-04-01 to 2026-04-30,27800.5,Commercial-Standard,48.0\n"
            "MTR-HQ-01,2026-05-01 to 2026-05-31,25300.2,Commercial-Standard,46.5\n"
            "MTR-HQ-01,2026-06-01 to 2026-06-30,26800.0,Commercial-Standard,47.8\n"
            "MTR-PLANT-02,2026-01-01 to 2026-01-31,880000.0,Industrial-HighDemand,160.0\n"
            "MTR-PLANT-02,2026-02-01 to 2026-02-28,820000.0,Industrial-HighDemand,155.0\n"
            "MTR-PLANT-02,2026-03-01 to 2026-03-31,950000.0,Industrial-HighDemand,175.0\n"
            # Anomalies for validation testing
            "MTR-HQ-01,2026-04-15 to 2026-05-15,15000.0,Commercial-Standard,35.0\n" # Overlap error test with previous HQ row
            "MTR-PLANT-02,2026-04-01 to 2026-04-30,1200000.0,Industrial-HighDemand,180.0\n" # Out of bounds warning test (>1,000,000)
            "MTR-HQ-01,2026-07-01 to 2026-07-31,-120.0,Commercial-Standard,10.0\n" # Negative error test
            "MTR-HQ-01,2026-08-01 to 2026-08-31,,Commercial-Standard,0.0\n" # Missing value error test
            "MTR-HQ-01,2026-09-01 to 2026-09-01,150.0,Commercial-Standard,5.0\n" # Too short warning
            "MTR-HQ-01,2026-10-31 to 2026-10-01,22000.0,Commercial-Standard,42.0\n" # Date ordering error (Start > End)
            "MTR-HQ-01,2026-11-01 to 2026-11-30,22000.0,Commercial-Standard,42.0\n" # Duplicate test (identical values)
            "MTR-HQ-01,2026-11-01 to 2026-11-30,22000.0,Commercial-Standard,42.0\n" # Duplicate test row
        )
        with open(utility_file, "w", encoding="utf-8") as f:
            f.write(utility_data)
        self.stdout.write(f"Created sample Utility file at: {utility_file}")

        # 7. Automatically Ingest Seeding Data into Database for Test Validation
        from core.models import RawUpload
        if not RawUpload.objects.filter(company=company).exists():
            self.stdout.write("Automatically ingesting generated sample files and travel API data...")
            
            sap_source = DataSource.objects.get(company=company, source_type="sap_fuel")
            with open(sap_file, "rb") as f:
                ingest_csv_file(
                    company=company,
                    data_source=sap_source,
                    file_file=f,
                    filename="sap_procurement_germany.csv",
                    uploaded_by=None
                )
            self.stdout.write("Ingested SAP CSV data.")

            utility_source = DataSource.objects.get(company=company, source_type="utility_electricity")
            with open(utility_file, "rb") as f:
                ingest_csv_file(
                    company=company,
                    data_source=utility_source,
                    file_file=f,
                    filename="utility_electricity_bills.csv",
                    uploaded_by=None
                )
            self.stdout.write("Ingested Utility CSV data.")

            # Synced Corporate Travel API data
            try:
                travel_source = DataSource.objects.get(company=company, source_type="corporate_travel")
                user = User.objects.get(username="analyst")
                sync_travel_api(
                    company=company,
                    data_source=travel_source,
                    uploaded_by=user,
                    sync_url="http://localhost:8000/api/external/travel-data/"
                )
                self.stdout.write("Synced Corporate Travel API data via HTTP GET.")
            except Exception as e:
                self.stdout.write(f"Corporate Travel HTTP sync failed ({e}). Falling back to manual record loading...")
                from core.services.normalization import normalize_raw_record
                from core.models import RawRecord
                user = User.objects.get(username="analyst")
                travel_source = DataSource.objects.get(company=company, source_type="corporate_travel")
                raw_upload = RawUpload.objects.create(
                    company=company,
                    data_source=travel_source,
                    upload_type='api',
                    filename='Sync API Concur',
                    status='processing',
                    uploaded_by=user
                )
                mock_data = [
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
                for idx, item in enumerate(mock_data):
                    raw_rec = RawRecord.objects.create(
                        raw_upload=raw_upload,
                        row_index=idx + 1,
                        raw_data=item
                    )
                    normalize_raw_record(raw_rec)
                raw_upload.status = 'completed'
                raw_upload.save()
                self.stdout.write("Successfully ingested Corporate Travel data manually.")
        else:
            self.stdout.write("Ingestion skipped because RawUpload records already exist.")

        self.stdout.write(self.style.SUCCESS("Database seeding and data ingestion completed successfully!"))
