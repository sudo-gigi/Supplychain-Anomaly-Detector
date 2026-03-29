"""
Supply Chain Cost Anomaly Detector v2
----------------------------------------
Detects three types of anomaly in procurement spend data:
  1. Price spikes     -- unit price significantly above historical average
  2. Budget overruns  -- total spend significantly above budgeted spend
  3. Duplicate invoices -- same supplier, item, date ordered more than once

Outputs:
  - anomalies_found.csv       (machine-readable, for Excel / QuickSight)
  - anomaly_report.pdf        (human-readable, for emailing to clients)

Usage (local):
    pip install pandas reportlab
    python anomaly_detector_v2.py

AWS Lambda usage:
    Uncomment the lambda_handler at the bottom of this file.
"""

import sys
import types

pil_mock = types.ModuleType("PIL")

class FakeImage:
    ANTIALIAS = 1
    LANCZOS = 1
    @staticmethod
    def open(*a, **k): pass
    @staticmethod
    def new(*a, **k): pass

pil_mock.Image = FakeImage
pil_mock._imaging = types.ModuleType("PIL._imaging")
sys.modules["PIL"] = pil_mock
sys.modules["PIL._imaging"] = pil_mock._imaging
sys.modules["PIL.Image"] = types.ModuleType("PIL.Image")
sys.modules["PIL.Image"].Image = FakeImage

import pandas as pd
import boto3, io
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)



# CONFIG

LOCAL_FILE               = "procurement_sample_v2.csv"
CSV_OUTPUT               = "anomalies_found.csv"
PDF_OUTPUT               = "anomaly_report.pdf"
PRICE_SPIKE_THRESHOLD    = 0.20
BUDGET_OVERRUN_THRESHOLD = 0.15
SEVERITY_HIGH_PRICE      = 0.50
SEVERITY_HIGH_BUDGET     = 0.40

# Brand colours
DARK_BLUE   = colors.HexColor("#1B3A5C")
MID_BLUE    = colors.HexColor("#2E6DA4")
LIGHT_BLUE  = colors.HexColor("#EAF3FB")
RED         = colors.HexColor("#C0392B")
AMBER       = colors.HexColor("#D68910")
LIGHT_RED   = colors.HexColor("#FDEDEC")
LIGHT_AMBER = colors.HexColor("#FEF9E7")
LIGHT_GRAY  = colors.HexColor("#F4F6F7")
MID_GRAY    = colors.HexColor("#BDC3C7")
DARK_GRAY   = colors.HexColor("#2C3E50")


# LOAD DATA

def load_data(filepath: str) -> pd.DataFrame:
    df = pd.read_csv(filepath, parse_dates=["Date"])
    df.columns = df.columns.str.strip()
    print(f"Loaded {len(df)} rows from {filepath}\n")
    return df



# ANOMALY DETECTION

def detect_price_spikes(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["price_pct_above_avg"] = (
        (df["Unit_Price"] - df["Historical_Avg_Unit_Price"])
        / df["Historical_Avg_Unit_Price"]
    )
    spikes = df[df["price_pct_above_avg"] > PRICE_SPIKE_THRESHOLD].copy()
    spikes["anomaly_type"] = "Price spike"
    spikes["detail"] = spikes.apply(
        lambda r: (
            f"Unit price £{r['Unit_Price']:.2f} vs historical avg "
            f"£{r['Historical_Avg_Unit_Price']:.2f} "
            f"(+{r['price_pct_above_avg']*100:.0f}%)"
        ), axis=1,
    )
    spikes["severity"] = spikes["price_pct_above_avg"].apply(
        lambda x: "HIGH" if x >= SEVERITY_HIGH_PRICE else "MEDIUM"
    )
    return spikes[["Date", "Supplier", "Category", "Item", "anomaly_type", "detail", "severity"]]


def detect_budget_overruns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["budget_pct_over"] = (
        (df["Total_Spend"] - df["Budgeted_Spend"]) / df["Budgeted_Spend"]
    )
    overruns = df[df["budget_pct_over"] > BUDGET_OVERRUN_THRESHOLD].copy()
    overruns["anomaly_type"] = "Budget overrun"
    overruns["detail"] = overruns.apply(
        lambda r: (
            f"Total spend £{r['Total_Spend']:.2f} vs budget "
            f"£{r['Budgeted_Spend']:.2f} "
            f"(+{r['budget_pct_over']*100:.0f}%)"
        ), axis=1,
    )
    overruns["severity"] = overruns["budget_pct_over"].apply(
        lambda x: "HIGH" if x >= SEVERITY_HIGH_BUDGET else "MEDIUM"
    )
    return overruns[["Date", "Supplier", "Category", "Item", "anomaly_type", "detail", "severity"]]


def detect_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    dupes = df[
        df.duplicated(subset=["Date", "Supplier", "Item", "Quantity", "Unit_Price"], keep=False)
    ].copy()
    dupes["anomaly_type"] = "Duplicate invoice"
    dupes["detail"] = dupes.apply(
        lambda r: (
            f"Identical order: {r['Quantity']} x {r['Item']} "
            f"@ £{r['Unit_Price']:.2f} from {r['Supplier']} on {r['Date'].date()}"
        ), axis=1,
    )
    dupes["severity"] = "HIGH"
    return dupes[["Date", "Supplier", "Category", "Item", "anomaly_type", "detail", "severity"]]



# SUMMARY STATS

def spend_summary(df: pd.DataFrame) -> dict:
    total_spend  = df["Total_Spend"].sum()
    total_budget = df["Budgeted_Spend"].sum()
    return {
        "total_rows"         : len(df),
        "date_range"         : f"{df['Date'].min().strftime('%d %b %Y')} to {df['Date'].max().strftime('%d %b %Y')}",
        "total_spend"        : total_spend,
        "total_budget"       : total_budget,
        "spend_vs_budget_pct": ((total_spend - total_budget) / total_budget * 100),
        "top_supplier"       : df.groupby("Supplier")["Total_Spend"].sum().idxmax(),
        "top_category"       : df.groupby("Category")["Total_Spend"].sum().idxmax(),
        "supplier_spend"     : df.groupby("Supplier")["Total_Spend"].sum().sort_values(ascending=False),
        "category_spend"     : df.groupby("Category")["Total_Spend"].sum().sort_values(ascending=False),
    }



# PRINT TERMINAL REPORT

def print_report(summary: dict, anomalies: pd.DataFrame):
    divider = "-" * 65
    print(divider)
    print("  SUPPLY CHAIN COST ANOMALY REPORT")
    print(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(divider)
    print("\nSPEND SUMMARY")
    print(f"  Period         : {summary['date_range']}")
    print(f"  Total spend    : £{summary['total_spend']:,.2f}")
    print(f"  Total budget   : £{summary['total_budget']:,.2f}")
    direction = "over" if summary["spend_vs_budget_pct"] > 0 else "under"
    print(f"  vs Budget      : {abs(summary['spend_vs_budget_pct']):.1f}% {direction} budget")
    print(f"  Top supplier   : {summary['top_supplier']}")
    print(f"  Top category   : {summary['top_category']}")
    print(f"\nANOMALIES DETECTED: {len(anomalies)}")
    print(divider)
    if anomalies.empty:
        print("  No anomalies found.")
    else:
        for sev, label in [("HIGH", "HIGH SEVERITY"), ("MEDIUM", "MEDIUM SEVERITY")]:
            subset = anomalies[anomalies["severity"] == sev]
            if not subset.empty:
                print(f"\n  {label} ({len(subset)} found)")
                for _, row in subset.iterrows():
                    print(f"\n  Date     : {row['Date'].date()}")
                    print(f"  Supplier : {row['Supplier']}")
                    print(f"  Item     : {row['Item']} ({row['Category']})")
                    print(f"  Type     : {row['anomaly_type']}")
                    print(f"  Detail   : {row['detail']}")
    print(f"\n{divider}\n  END OF REPORT\n{divider}")



# SAVE CSV

def save_csv(anomalies: pd.DataFrame, path: str = CSV_OUTPUT):
    if not anomalies.empty:
        anomalies.to_csv(path, index=False)
        print(f"\nCSV saved to: {path}")
    else:
        print("\nNo anomalies to save.")


 
# BUILD PDF

def build_pdf(summary: dict, anomalies: pd.DataFrame, path: str = PDF_OUTPUT):

    doc = SimpleDocTemplate(
        path,
        pagesize=A4,
        leftMargin=20*mm, rightMargin=20*mm,
        topMargin=20*mm, bottomMargin=20*mm,
    )

    # Styles 
    base = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "ReportTitle",
        fontName="Helvetica-Bold",
        fontSize=20,
        textColor=DARK_BLUE,
        spaceAfter=6,
        leading=26,
        alignment=TA_LEFT,
    )
    subtitle_style = ParagraphStyle(
        "Subtitle",
        fontName="Helvetica",
        fontSize=10,
        textColor=colors.HexColor("#7F8C8D"),
        spaceBefore=4,
        spaceAfter=12,
    )
    section_style = ParagraphStyle(
        "Section",
        fontName="Helvetica-Bold",
        fontSize=13,
        textColor=DARK_BLUE,
        spaceBefore=14,
        spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "Body",
        fontName="Helvetica",
        fontSize=10,
        textColor=DARK_GRAY,
        spaceAfter=4,
        leading=15,
    )
    severity_high_style = ParagraphStyle(
        "SevHigh",
        fontName="Helvetica-Bold",
        fontSize=10,
        textColor=RED,
        spaceBefore=10,
        spaceAfter=4,
    )
    severity_med_style = ParagraphStyle(
        "SevMed",
        fontName="Helvetica-Bold",
        fontSize=10,
        textColor=AMBER,
        spaceBefore=10,
        spaceAfter=4,
    )
    detail_style = ParagraphStyle(
        "Detail",
        fontName="Helvetica-Oblique",
        fontSize=9,
        textColor=colors.HexColor("#555555"),
        spaceAfter=2,
        leftIndent=8,
    )

    story = []
    generated = datetime.now().strftime("%d %B %Y at %H:%M")

    #  Header 
    story.append(Paragraph("Supply Chain Cost Anomaly Report", title_style))
    story.append(Paragraph(f"Generated: {generated}", subtitle_style))
    story.append(HRFlowable(width="100%", thickness=2, color=MID_BLUE, spaceAfter=10))

    #  Spend Summary Table 
    story.append(Paragraph("Spend Summary", section_style))

    direction = "over budget" if summary["spend_vs_budget_pct"] > 0 else "under budget"
    budget_str = f"{abs(summary['spend_vs_budget_pct']):.1f}% {direction}"

    summary_data = [
        ["Period",        summary["date_range"]],
        ["Total rows",    str(summary["total_rows"])],
        ["Total spend",   f"£{summary['total_spend']:,.2f}"],
        ["Total budget",  f"£{summary['total_budget']:,.2f}"],
        ["vs Budget",     budget_str],
        ["Top supplier",  summary["top_supplier"]],
        ["Top category",  summary["top_category"]],
    ]

    summary_table = Table(summary_data, colWidths=[45*mm, 120*mm])
    summary_table.setStyle(TableStyle([
        ("BACKGROUND",  (0, 0), (0, -1), LIGHT_BLUE),
        ("FONTNAME",    (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME",    (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE",    (0, 0), (-1, -1), 10),
        ("TEXTCOLOR",   (0, 0), (0, -1), DARK_BLUE),
        ("TEXTCOLOR",   (1, 0), (1, -1), DARK_GRAY),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, LIGHT_GRAY]),
        ("BOX",         (0, 0), (-1, -1), 0.5, MID_GRAY),
        ("INNERGRID",   (0, 0), (-1, -1), 0.3, MID_GRAY),
        ("TOPPADDING",  (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(summary_table)

    #  Spend by Supplier Table 
    story.append(Spacer(1, 8))
    story.append(Paragraph("Spend by supplier", section_style))

    supplier_rows = [["Supplier", "Total Spend"]]
    for sup, val in summary["supplier_spend"].items():
        supplier_rows.append([sup, f"£{val:,.2f}"])

    sup_table = Table(supplier_rows, colWidths=[100*mm, 65*mm])
    sup_table.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, 0), DARK_BLUE),
        ("TEXTCOLOR",    (0, 0), (-1, 0), colors.white),
        ("FONTNAME",     (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME",     (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",     (0, 0), (-1, -1), 10),
        ("TEXTCOLOR",    (0, 1), (-1, -1), DARK_GRAY),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, LIGHT_GRAY]),
        ("BOX",          (0, 0), (-1, -1), 0.5, MID_GRAY),
        ("INNERGRID",    (0, 0), (-1, -1), 0.3, MID_GRAY),
        ("TOPPADDING",   (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 6),
        ("LEFTPADDING",  (0, 0), (-1, -1), 10),
    ]))
    story.append(sup_table)

    #  Anomalies Section
    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", thickness=1, color=MID_GRAY, spaceAfter=6))
    story.append(Paragraph(f"Anomalies Detected: {len(anomalies)}", section_style))

    if anomalies.empty:
        story.append(Paragraph("No anomalies found. All spend within thresholds.", body_style))
    else:
        for sev, label, sev_style, bg_color in [
            ("HIGH",   "High severity",   severity_high_style,  LIGHT_RED),
            ("MEDIUM", "Medium severity", severity_med_style,   LIGHT_AMBER),
        ]:
            subset = anomalies[anomalies["severity"] == sev]
            if subset.empty:
                continue

            story.append(Paragraph(f"{label} ({len(subset)} found)", sev_style))

           
            cell_style = ParagraphStyle(
                "Cell", fontName="Helvetica", fontSize=8.5,
                textColor=DARK_GRAY, leading=12,
            )
            cell_bold = ParagraphStyle(
                "CellBold", fontName="Helvetica-Bold", fontSize=8.5,
                textColor=colors.white, leading=12,
            )
           
            col_widths = [25*mm, 35*mm, 32*mm, 28*mm, 50*mm]

            anom_data = [[
                Paragraph("Date",     cell_bold),
                Paragraph("Supplier", cell_bold),
                Paragraph("Item",     cell_bold),
                Paragraph("Type",     cell_bold),
                Paragraph("Detail",   cell_bold),
            ]]
            for _, row in subset.iterrows():
                anom_data.append([
                    Paragraph(row["Date"].strftime("%d %b %Y"), cell_style),
                    Paragraph(row["Supplier"], cell_style),
                    Paragraph(f"{row['Item']} ({row['Category']})", cell_style),
                    Paragraph(row["anomaly_type"], cell_style),
                    Paragraph(row["detail"], cell_style),
                ])

            anom_table = Table(anom_data, colWidths=col_widths, repeatRows=1)
            anom_table.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1, 0), DARK_BLUE),
                ("BACKGROUND",    (0, 1), (-1, -1), bg_color),
                ("BOX",           (0, 0), (-1, -1), 0.5, MID_GRAY),
                ("INNERGRID",     (0, 0), (-1, -1), 0.3, MID_GRAY),
                ("TOPPADDING",    (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING",   (0, 0), (-1, -1), 6),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
                ("VALIGN",        (0, 0), (-1, -1), "TOP"),
            ]))
            story.append(anom_table)
            story.append(Spacer(1, 8))

    #  Footer
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=1, color=MID_GRAY))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        f"Confidential — generated by Supply Chain Cost Anomaly Detector | {generated}",
        ParagraphStyle("Footer", fontName="Helvetica", fontSize=8,
                       textColor=colors.HexColor("#95A5A6"), alignment=TA_CENTER)
    ))

    doc.build(story)
    print(f"PDF saved to: {path}")



# MAIN

def run(filepath: str):
    df = load_data(filepath)

    price_spikes    = detect_price_spikes(df)
    budget_overruns = detect_budget_overruns(df)
    duplicates      = detect_duplicates(df)

    all_anomalies = pd.concat(
        [price_spikes, budget_overruns, duplicates], ignore_index=True
    ).sort_values(["severity", "Date"], ascending=[True, True])

    summary = spend_summary(df)

    print_report(summary, all_anomalies)
    save_csv(all_anomalies)
    build_pdf(summary, all_anomalies)


if __name__ == "__main__":
    run(LOCAL_FILE)



# AWS LAMBDA HANDLER 
 
def lambda_handler(event, context):
     s3     = boto3.client("s3")
     bucket = event["Records"][0]["s3"]["bucket"]["name"]
     key    = event["Records"][0]["s3"]["object"]["key"]
     obj    = s3.get_object(Bucket=bucket, Key=key)
     df     = pd.read_csv(io.BytesIO(obj["Body"].read()), parse_dates=["Date"])

     price_spikes    = detect_price_spikes(df)
     budget_overruns = detect_budget_overruns(df)
     duplicates      = detect_duplicates(df)

     all_anomalies = pd.concat(
         [price_spikes, budget_overruns, duplicates], ignore_index=True
     )
     summary = spend_summary(df)
     build_pdf(summary, all_anomalies, "/tmp/anomaly_report.pdf")
     save_csv(all_anomalies, "/tmp/anomalies_found.csv")

     # Upload outputs back to S3
     s3.upload_file("/tmp/anomaly_report.pdf",   bucket, "outputs/anomaly_report.pdf")
     s3.upload_file("/tmp/anomalies_found.csv",  bucket, "outputs/anomalies_found.csv")

     return {"statusCode": 200, "anomalies_found": len(all_anomalies)}
