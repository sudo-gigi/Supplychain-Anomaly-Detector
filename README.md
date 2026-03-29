# Supply Chain Cost Anomaly Detector

An AWS-powered tool that automatically detects cost anomalies in procurement spend data, flagging price spikes, budget overruns, duplicate invoices and delivers a professional PDF report without any manual intervention.

---

## The Problem

Procurement and supply chain teams manage hundreds of supplier transactions every month. Hidden within that data are costly anomalies, suppliers quietly charging above agreed rates, invoices being submitted twice, budgets being exceeded without anyone noticing. Most SMEs have no automated way to catch these issues, and by the time they're spotted manually the damage is already done.

---

## The Solution

Upload a CSV of procurement spend data to an S3 bucket. Within seconds, this tool automatically:

- Detects price spikes where unit price exceeds historical average by more than 20%
- Flags budget overruns where total spend exceeds approved budget by more than 15%
- Identifies duplicate invoices same supplier, item, quantity and date
- Scores every anomaly as HIGH or MEDIUM severity
- Generates a professional PDF report ready to send to a finance director or client
- Saves a machine-readable CSV for further analysis in Excel or QuickSight

No manual steps. No code to run. Just upload the file and the report appears.

---

## Architecture

```
User uploads CSV
      │
      ▼
  AWS S3 (inputs/)
      │
      │ triggers automatically
      ▼
  AWS Lambda
  (Python 3.11)
      │
      ├──► anomaly_report.pdf  ──► AWS S3 (outputs/)
      └──► anomalies_found.csv ──► AWS S3 (outputs/)
```

### AWS Services Used
- **S3** - stores input CSVs and output reports
- **Lambda** - runs the anomaly detection logic serverlessly
- **IAM** - manages permissions between services

### Python Libraries
- **Pandas** - data ingestion, cleaning and anomaly detection logic
- **ReportLab** - generates the professional PDF report

---

## Anomaly Detection Logic

| Anomaly Type | Detection Method | Default Threshold |
|---|---|---|
| Price spike | Unit price vs historical average | > 20% above average |
| Budget overrun | Total spend vs budgeted spend | > 15% above budget |
| Duplicate invoice | Exact match on date, supplier, item, quantity, price | Any duplicate |

Severity scoring:
- **HIGH** - price spike ≥ 50% above average, or budget overrun ≥ 40%, or any duplicate invoice
- **MEDIUM** - price spike 20–49% above average, or budget overrun 15–39%

All thresholds are configurable at the top of `lambda_function.py`.

---

## Sample Output

The tool produces a structured PDF report containing:

- Spend summary: total spend vs budget, date range, top supplier and category
- Spend breakdown by supplier
- HIGH severity anomalies (red)
- MEDIUM severity anomalies (amber)
- Timestamped confidential footer

A sample report generated from the included test dataset is available in this repository: `anomaly_report.pdf`

---

## Input CSV Format

Your CSV must contain these columns:

| Column | Description | Example |
|---|---|---|
| Date | Transaction date | 2024-03-22 |
| Supplier | Supplier name | Delta Freight |
| Category | Spend category | Fuel |
| Item | Item description | Forklift Fuel |
| Quantity | Units ordered | 85 |
| Unit_Price | Price per unit (£) | 3.40 |
| Historical_Avg_Unit_Price | Normal price per unit (£) | 1.95 |
| Total_Spend | Quantity × Unit_Price (£) | 289.00 |
| Budgeted_Spend | Approved spend for this order (£) | 170.00 |

A sample dataset with realistic data and seeded anomalies is included: `procurement_sample_v2.csv`

---

## Deployment

### Prerequisites
- AWS account (free tier is sufficient)
- Python 3.11

### Steps

1. Create an S3 bucket with two folders: `inputs/` and `outputs/`
2. Deploy `lambda_function.py` as a Lambda function (Python 3.11, 512MB memory, 5 minute timeout)
3. Add the `AWSSDKPandas-Python311` managed layer for Pandas
4. Build and add a ReportLab Lambda layer using AWS CloudShell:
```bash
mkdir -p /tmp/python
pip install reportlab pillow --target /tmp/python --quiet
cd /tmp && zip -r reportlab-layer.zip python/
aws s3 cp /tmp/reportlab-layer.zip s3://YOUR-BUCKET-NAME/reportlab-layer.zip
```
5. Set the S3 trigger: event type `PUT`, prefix `inputs/`, suffix `.csv`
6. Attach `AmazonS3FullAccess` policy to the Lambda execution role

### Test
Upload `procurement_sample_v2.csv` to your `inputs/` folder. After ~20 seconds, `anomaly_report.pdf` and `anomalies_found.csv` will appear in `outputs/`.

---

## Future Roadmap

- [ ] SES email delivery - automatically email the report when anomalies are found
- [ ] QuickSight dashboard - live spend visualisation
- [ ] Supplier Risk Dashboard - score suppliers on financial, geopolitical and compliance risk
- [ ] Multi-currency support
- [ ] Slack/Teams notification integration

---

## Licence

MIT - free to use and adapt.
