"""Deterministic parser for the synthetic D&O / Management Liability application.

Fixed-template forms parse far more reliably with rules than with a small LLM,
and this directly answers the case-study prompt about handling uncertain
extractions: every field is either matched exactly or left None (never guessed).
"""
from __future__ import annotations

import re

# Section B coverage line -> column prefix
COVERAGES = {
    "Directors & Officers Liability": "do",
    "Employment Practices Liability": "epl",
    "Fiduciary Liability": "fiduciary",
    "Cyber Liability": "cyber",
    "Commercial Crime": "crime",
}

# "Label <value>" — value is everything after the label
SIMPLE = {
    "Applicant Name": "applicant_name",
    "Mailing Address": "mailing_address",
    "City / State / ZIP": "city_state_zip",
    "Website": "website",
    "Nature of Business": "nature_of_business",
    "Nonprofit Structure": "nonprofit_structure",
    "Scope": "scope",
    "Fiscal Year End": "fiscal_year_end",
    "Total Assets": "total_assets",
    "Total Liabilities": "total_liabilities",
    "Total Contributions": "total_contributions",
    "Total Revenue": "total_revenue",
    "Total Expenses": "total_expenses",
    "Net Assets / Fund Balance": "net_assets_fund_balance",
    "Revenue from Federal Contracts": "revenue_federal_contracts_pct",
    "Revenue from State/Local Contracts": "revenue_state_local_contracts_pct",
    "Full-time Employees": "full_time_employees",
    "Part-time Employees": "part_time_employees",
    "Seasonal / Temporary": "seasonal_temporary",
    "Volunteers": "volunteers",
    "Independent Contractors": "independent_contractors",
    "Total Worldwide Employees": "total_worldwide_employees",
    "Total Employees Last Year": "total_employees_last_year",
    "Workforce Earning Over $100,000": "workforce_over_100k_pct",
    "Workforce Earning Over $250,000": "workforce_over_250k_pct",
    "Current Employee Turnover": "current_employee_turnover_pct",
    "Prior Year Employee Turnover": "prior_year_employee_turnover_pct",
    "PII Records": "pii_records",
    "PHI Records": "phi_records",
    "Financial Account Records": "financial_account_records",
    "Approximate Revenue per Hour": "approximate_revenue_per_hour",
    "Number of Data Centers": "number_of_data_centers",
    "Outage Duration / Details": "outage_duration_details",
}

# "Label Yes: X No:" / "Label Yes: No: X" — value from the X position
YESNO_X = {
    "General Liability Insurance": "general_liability_insurance",
    "Sells/Sponsors Insurance Products": "sells_sponsors_insurance_products",
    "Research / Testing": "research_testing",
    "Certification / Standard Setting": "certification_standard_setting",
    "Creditor Reorganization": "creditor_reorganization",
    "D&O; Coverage Desired": "do_coverage_desired",
    "EPL Coverage Desired": "epl_coverage_desired",
    "Human Resources Department": "hr_department",
    "HR Manual / Written Guidelines": "hr_manual_written_guidelines",
    "Labor Counsel Reviewed Guidelines": "labor_counsel_reviewed_guidelines",
    "Employee Handbook": "employee_handbook",
    "Anti-discrimination / Harassment Policies": "anti_discrimination_harassment_policies",
    "Formal Complaint Process": "formal_complaint_process",
    "Non-retaliation Policy": "non_retaliation_policy",
    "Employment Matters Handled by In-house": "employment_matters_inhouse_counsel",
    "Employment Matters Handled by Outside": "employment_matters_outside_counsel",
    "Fiduciary Coverage Desired": "fiduciary_coverage_desired",
    "Commercial Crime Coverage Desired": "commercial_crime_coverage_desired",
    "Cyber Coverage Desired": "cyber_coverage_desired",
    "Annual Risk Assessment": "annual_risk_assessment",
    "Confidential Data Encrypted": "confidential_data_encrypted",
    "Patch Management Process": "patch_management_process",
    "Formal Information Security Policy": "formal_info_security_policy",
    "Cybersecurity Training": "cybersecurity_training",
    "Business Continuity Plan": "business_continuity_plan",
    "BCP Tested Annually": "bcp_tested_annually",
    "Prior System Outage": "prior_system_outage",
}

# "Label ... No" — plain trailing Yes/No, no X markers
PLAIN_YESNO = {
    "M&A; / Divestment": "ma_divestment",
    "Change in Outside Auditor": "change_in_outside_auditor",
    "Closings / Layoffs / Workforce Reduction": "closings_layoffs_workforce_reduction",
    "Anticipating Material Changes": "anticipating_material_changes",
    "Board / C-Level Changes": "board_clevel_changes",
    "Debt Covenant Breach or Violation": "debt_covenant_breach",
}

ALL_COLUMNS = (
    ["applicant_name", "mailing_address", "city_state_zip", "website",
     "nature_of_business", "date_of_formation", "state_of_formation",
     "nonprofit_structure", "scope", "locations_domestic", "locations_foreign",
     "members", "chapters", "authorized_representative", "authorized_rep_title",
     "phone", "email"]
    + [f"{p}_{s}" for p in COVERAGES.values()
       for s in ("limit_requested", "purchased", "current_carrier",
                 "current_limit", "expiration")]
    + ["carrier_refused_canceled_nonrenewed"]
    + ["subsidiary_name", "subsidiary_structure", "subsidiary_ownership",
       "subsidiary_date", "subsidiary_operations"]
    + list(PLAIN_YESNO.values())
    + list(SIMPLE.values())
    + list(YESNO_X.values())
    + ["declaration_rep_name", "declaration_title", "declaration_date",
       "declaration_applicant"]
)
# de-duplicate while preserving order
ALL_COLUMNS = list(dict.fromkeys(ALL_COLUMNS))


def _yesno_from_x(line: str) -> str | None:
    if re.search(r"Yes:\s*X", line):
        return "Yes"
    if re.search(r"No:\s*X", line):
        return "No"
    return None


def parse_do_application(text: str) -> dict:
    out: dict[str, object] = {c: None for c in ALL_COLUMNS}
    section = None
    in_declarations = False

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        if line.startswith("SECTION"):
            section = line
            continue
        if line.startswith("APPLICANT DECLARATIONS"):
            in_declarations = True
            continue

        # --- Section B coverage rows ---
        matched_cov = False
        for name, prefix in COVERAGES.items():
            if line.startswith(name):
                rest = line[len(name):].strip()
                m = re.match(
                    r"^(\$[\d,]+)\s+(Yes|No)"
                    r"(?:\s+(.+?)\s+(\$[\d,]+)\s+([\d/]+))?$",
                    rest,
                )
                if m:
                    out[f"{prefix}_limit_requested"] = m.group(1)
                    out[f"{prefix}_purchased"] = m.group(2)
                    out[f"{prefix}_current_carrier"] = m.group(3)
                    out[f"{prefix}_current_limit"] = m.group(4)
                    out[f"{prefix}_expiration"] = m.group(5)
                    matched_cov = True
                break
        if matched_cov:
            continue

        # --- Section C subsidiary row ---
        if section and "COMPANY INFORMATION" in section:
            m = re.match(
                r"^(.+?)\s+(LLC|Inc\.?|Corp\.?|LP|LLP)\s+(\d+%)\s+"
                r"(\d{2}/\d{2}/\d{4})\s+(.+)$",
                line,
            )
            if m:
                out["subsidiary_name"] = m.group(1)
                out["subsidiary_structure"] = m.group(2)
                out["subsidiary_ownership"] = m.group(3)
                out["subsidiary_date"] = m.group(4)
                out["subsidiary_operations"] = m.group(5)
                continue

        # --- Multi-value special lines ---
        if line.startswith("Date / State of Formation"):
            v = line[len("Date / State of Formation"):].strip()
            parts = [p.strip() for p in v.split("/")]
            if len(parts) >= 4:  # MM / DD / YYYY / ST
                out["date_of_formation"] = "/".join(parts[:3])
                out["state_of_formation"] = parts[3]
            continue
        if line.startswith("Locations"):
            m = re.search(r"Domestic:\s*(\d+).*Foreign:\s*(\d+)", line)
            if m:
                out["locations_domestic"] = m.group(1)
                out["locations_foreign"] = m.group(2)
            continue
        if line.startswith("Members / Chapters"):
            m = re.search(r"(\d+)\s*/\s*(\d+)", line)
            if m:
                out["members"] = m.group(1)
                out["chapters"] = m.group(2)
            continue
        if line.startswith("Authorized Representative") and not in_declarations:
            v = line[len("Authorized Representative"):].strip()
            if " - " in v:
                name, title = v.split(" - ", 1)
                out["authorized_representative"] = name.strip()
                out["authorized_rep_title"] = title.strip()
            else:
                out["authorized_representative"] = v
            continue
        if line.startswith("Phone / Email"):
            v = line[len("Phone / Email"):].strip()
            parts = [p.strip() for p in v.split("/", 1)]
            out["phone"] = parts[0] if parts else None
            out["email"] = parts[1] if len(parts) > 1 else None
            continue
        if line.startswith("Carrier Refused"):
            out["carrier_refused_canceled_nonrenewed"] = line.split()[-1]
            continue

        # --- Declarations block ---
        if in_declarations:
            for label, col in (("Authorized Representative", "declaration_rep_name"),
                               ("Title", "declaration_title"),
                               ("Date", "declaration_date"),
                               ("Applicant", "declaration_applicant")):
                if line.startswith(label):
                    out[col] = line[len(label):].strip()
                    break
            continue

        # --- Yes/No with X markers ---
        done = False
        for label, col in sorted(YESNO_X.items(), key=lambda x: -len(x[0])):
            if line.startswith(label) and ("Yes:" in line or "No:" in line):
                out[col] = _yesno_from_x(line)
                done = True
                break
        if done:
            continue

        # --- Plain trailing Yes/No ---
        for label, col in sorted(PLAIN_YESNO.items(), key=lambda x: -len(x[0])):
            if line.startswith(label):
                out[col] = line.split()[-1]
                done = True
                break
        if done:
            continue

        # --- Simple label -> value ---
        for label, col in sorted(SIMPLE.items(), key=lambda x: -len(x[0])):
            if line.startswith(label):
                out[col] = line[len(label):].strip() or None
                break

    return out


if __name__ == "__main__":
    import json
    import sys

    import pdfplumber

    with pdfplumber.open(sys.argv[1]) as pdf:
        txt = "\n".join((p.extract_text() or "") for p in pdf.pages)
    result = parse_do_application(txt)
    filled = {k: v for k, v in result.items() if v is not None}
    print(f"Filled {len(filled)}/{len(result)} fields\n")
    print(json.dumps(result, indent=2))
