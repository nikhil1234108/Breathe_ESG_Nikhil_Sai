# Engineering Decisions & Assumptions

This document chronicles the assumptions made, scope constraints defined, and trade-offs weighed during the development of this ESG prototype.

## Ingestion Format Choices

### 1. SAP Fuel / Procurement Data
* **Assumed Format**: CSV export using German headers (`Werk`, `Material`, `Menge`, `Einheit`, `Buchungsdatum`, `Kostenstelle`, `Lieferant`).
* **Justification**: Real-world SAP installations (especially in Europe) are heavily configured in German or use German field names in their database tables. Directly supporting these headers demonstrates realistic enterprise data handling, whereas generic English column exports are a simplification.
* **Ingestion Method**: File Upload.

### 2. Utility Electricity Data
* **Assumed Format**: Portal-exported CSV containing `Meter_ID`, `Billing_Period`, `kWh_Consumption`, `Tariff`, `Peak_Demand_kW`.
* **Justification**: Facility managers typically export bills from utility portals (like Vattenfall, PG&E) as CSV. Dealing with non-calendar billing periods (e.g. `2026-03-15 to 2026-04-14`) and overlap errors is a highly realistic validation challenge.
* **Ingestion Method**: File Upload.

### 3. Corporate Travel Data
* **Assumed Format**: JSON payload retrieved from a REST endpoint representing Navan/Concur.
* **Justification**: Travel platforms expose REST APIs rather than file exports. Simulating REST integration by having our Django backend fetch from a mock REST API endpoint highlights clean service integration.
* **Ingestion Method**: Automated HTTP GET sync.

---

## Ignored Complexities & Scope Constraints

1. **PDF/OCR Ingestion**: We intentionally ignored parsing scanned PDF utility bills. Implementing OCR or LLM-based layout extractors is extremely fragile, error-prone, and too broad for a 4-day prototype. We assume facility managers can download portal CSVs.
2. **Real SAP RFC/RFC BAPI Client**: Connecting directly to SAP using RFC calls requires expensive licenses, SAP Java Connector (JCo), or SAP NW RFC SDK. We chose CSV exports, which represent the standard export mechanism used by sustainability teams.
3. **Authentication / SSO**: Standard Django auth was used with mock session bindings rather than integrating Okta/OAuth2, keeping the codebase focused on ingestion and auditing.

---

## PM Questions we would ask in a real-world scenario

1. **How should we handle meter resets and negative readings?** 
   - *Context*: Some utility portal exports list negative numbers if solar feed-in tariff is active or if a meter rolls over. In this prototype, we flag negative values as errors, but we would need to know if net-metering deductions are allowed.
2. **What is the protocol for resolving rejected records?**
   - *Context*: When an analyst rejects a record in this prototype, we flag it as `rejected` and do not lock it. Should this sync back to the source system to prevent re-importing, or is it corrected only inside our platform?
3. **How do we handle multi-tiered facility mapping?**
   - *Context*: Currently we treat `Werk` (plant) and `Meter_ID` as flat strings. In a production system, we would need a hierarchical Facility Registry mapping Meters to Plants, and Plants to Subsidiaries.
