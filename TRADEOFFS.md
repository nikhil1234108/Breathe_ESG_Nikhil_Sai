# Trade-Offs & Future Scalability

This document details the features and architectures that were intentionally excluded from this prototype, and details how the platform should be evolved for enterprise-scale workloads.

## Intentionally Excluded Features

### 1. Scanned PDF Parsing & OCR
* **Why Excluded**: Sustainability teams often request PDF bill parsing. However, writing custom PDF layout scrapers (e.g. using PyPDF, pdfplumber) is highly brittle—a minor layout change by the utility company breaks the regex. Introducing LLM-based OCR is slow and expensive for a prototype.
* **Production Alternative**: In production, we would deploy a specialized document intelligence pipeline (e.g., AWS Textract or Google Document AI). The extracted fields would simply be written to the existing `RawRecord` JSON, keeping our validation and normalization service completely decoupled and unchanged.

### 2. Distributed Task Queue (Celery / Redis)
* **Why Excluded**: We process file uploads synchronously in the Django request thread. For sample datasets (under 10,000 rows), this completes in less than 2 seconds, which is acceptable. Adding Celery, Redis, and message brokers increases the deployment complexity and local setup friction without providing immediate value for a prototype.
* **Production Alternative**: For files larger than 50MB (e.g., 500,000 procurement transactions), we would offload the ingestion function to a Celery background worker, updating the `RawUpload` status asynchronously and notifying the analyst via WebSockets.

### 3. Real SAP RFC Middleware
* **Why Excluded**: Real SAP integrations are slow to set up, requiring specialized credentials, VPNs, and SAP Java Connectors (JCo).
* **Production Alternative**: sustainability analysts typically request an automated nightly export of MM (Materials Management) tables into an S3 bucket, from which our ingestion pipeline pulls the CSV files. The CSV parser we built directly models this realistic workflow.

---

## Future Scalability Architecture

If this platform scale grows to ingest 1,000,000+ records daily:

1. **Database Partitioning**: The `NormalizedEmissionRecord` table would be horizontally partitioned by `company_id` and `transaction_date` (monthly or yearly partitions) to keep query times for dashboards fast.
2. **Serverless Ingestion**: We can offload CSV parsing to AWS Lambda or Google Cloud Functions. This ensures our main web server remains responsive while compute-heavy parsing scales elastically.
3. **Audit Log Warm/Cold Storage**: The `AuditLog` table will grow exponentially. In a production environment, logs older than 90 days would be archived to cold storage (e.g. AWS S3 Glacier) to minimize primary database index sizes.
