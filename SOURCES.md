# Data Sources Analysis

This document outlines the real-world research, format assumptions, and scaling limitations of the three enterprise data sources integrated into the Breathe ESG prototype.

---

## 1. SAP Fuel & Procurement Data

### Real-World Research
SAP stores procurement data across core tables like `EKKO` (Purchasing Document Header), `EKPO` (Purchasing Document Item), and financial ledger tables like `BSEG`. When sustainability teams extract procurement files, they export them via standard ALV Grid reports or custom ABAP scripts. 
These files are typically semicolon-separated values (`.csv`) containing technical SAP German field names or German text labels due to German-centric ERP setups.

### Mock Design Decisions
* **Delimiters**: Semicolon (`;`) instead of comma. Semicolon is the default CSV list separator in continental European Windows environments.
* **German Headers**:
  - `Werk` = Plant code (e.g., `1010` - Munich, `1020` - Stuttgart).
  - `Material` = Procurement item description.
  - `Menge` = Quantity (using comma as decimal separator, e.g. `1200,50`).
  - `Einheit` = SAP unit key (e.g., `L` for Litres, `TO` for Metric Tons).
  - `Buchungsdatum` = Posting date (format: `DD.MM.YYYY`).
  - `Kostenstelle` = Cost Center.
  - `Lieferant` = Vendor name.

### What breaks at Enterprise Scale?
* **Decimal Mismatches**: German notation swaps commas and dots (e.g., `1.000,50` vs `1,000.50`). A parser expecting English notation will fail or incorrectly divide the quantity by 1,000.
* **Plant Code Mapping**: Plant codes (`1010`, `1020`) mean nothing without a mapping table to assign physical geographical addresses. Without geographic locations, we cannot apply correct regional grid emission factors.

---

## 2. Utility Electricity Portal Data

### Real-World Research
Utility companies (e.g., Vattenfall, E.ON, PG&E) allow commercial clients to download meter readings via customer portals. The files are usually comma-separated values (`.csv`) containing meter identification numbers, consumption metrics, and billing period intervals.
Crucially, billing periods are rarely aligned with calendar months. A billing cycle might run from the 14th of March to the 13th of April, requiring split allocation across reporting periods.

### Mock Design Decisions
* **Billing Period**: String formats like `YYYY-MM-DD to YYYY-MM-DD`.
* **Meter ID**: Linked to the facility location (e.g. `MTR-HQ-01`).
* **Anomalies modeled**:
  - Overlapping cycles (e.g., double billing or data entry errors).
  - Missing consumption values.
  - Negative values (sometimes caused by net-metering solar feedback, which must be verified).

### What breaks at Enterprise Scale?
* **Solar Feed-in Netting**: If a facility generates solar power, the meter may count backward. We must distinguish gross usage (for Scope 2 calculations) from net usage (for financial billing).
* **Multi-Tenant Metering**: In sub-leased office spaces, multiple tenants share a single meter. Apportioning emissions based on square footage is required but complex.

---

## 3. Corporate Travel API Data

### Real-World Research
Modern corporate travel platforms like Navan, Concur, or TripActions expose REST APIs. Instead of downloading spreadsheets, sustainability platforms sync directly via automated sync triggers. The response contains travel segment types (flights, hotels, ground), transaction dates, travel class, and location codes.
Flight segments often only provide airport codes (e.g., `LHR -> JFK`) rather than passenger mileage, requiring secondary coordinate lookup calculations.

### Mock Design Decisions
* **Airport Coordinate Lookup**: Built-in coordinates for major hubs combined with the Haversine formula (Great-Circle Distance).
* **Class Emissions Multipliers**: Travel class affects carbon footprint (e.g., Business class flight emission factors are ~3x higher than Economy due to cabin space allocation).
* **Anomalies modeled**:
  - Flight distance exceeding physical limit checks.
  - Hotel stays with negative nights.
  - Flights that are too short (warning check).

### What breaks at Enterprise Scale?
* **Connection Routing**: A trip from New York to Singapore might be `JFK -> FRA -> SIN` (multi-segment). Treating it as a single direct flight `JFK -> SIN` yields incorrect distance and bypasses takeoff/landing cycles, which have higher fuel burn rates.
* **Airport Database Maintenance**: There are over 10,000 active commercial airports globally. Maintaining a complete geographic database of coordinates is a major scaling concern.
