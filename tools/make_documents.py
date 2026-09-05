"""Generates the acme-corp sample document set. §5.2, §8.4.

Five text-layer PDFs — not scans; `call_llm` pulls their text with `pypdf`
(§8.3). The set carries every required application field except one:

  * `tax_id` appears in **both** the EIN letter and the W-9, so an illegible
    EIN letter has a correct fallback the agent must reason its way to (§5.2);
  * Marcus Vela's **date of birth is absent from every document** — the
    deliberate gap the escalation beat rests on (§8.4). Ownership declarations
    routinely list names and percentages without dates of birth, so the gap is
    realistic rather than contrived.

Ownership sums to 85% because holders below 25% are not listed on a
beneficial-ownership declaration — which is why the review validator uses
`sum(ownership_pct) <= 100`, not `== 100` (§9.1 rule 5).

Output is committed. `invariant=1` keeps the bytes stable across regenerations
so a rebuild does not show up as a diff.

Run with `make documents`.
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "documents" / "acme-corp"
STYLES = getSampleStyleSheet()


def _write(stem: str, title: str, lines: list[str]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUT / f"{stem}.pdf"),
        pagesize=LETTER,
        title=title,
        author="customer-onboarding-demo",
        invariant=1,
    )
    flow: list = [Paragraph(title, STYLES["Title"]), Spacer(1, 18)]
    for line in lines:
        flow.append(Paragraph(line, STYLES["BodyText"]))
        flow.append(Spacer(1, 6))
    doc.build(flow)


# stem -> (title, body lines). The stems are the DocumentKind values, slugged.
DOCUMENTS: dict[str, tuple[str, list[str]]] = {
    # legal_name, entity_type, formation_date, formation_state, registered_address
    "articles-of-incorporation": ("Certificate of Formation", [
        "State of Delaware — Division of Corporations",
        "Entity Name: <b>Acme Holdings LLC</b>",
        "Entity Type: <b>Limited Liability Company (LLC)</b>",
        "Date of Formation: <b>2019-03-11</b>",
        "State of Formation: <b>Delaware</b>",
        "Registered Office: <b>1209 Orange Street, Wilmington, DE 19801, US</b>",
        "Registered Agent: The Corporation Trust Company",
        "File Number: 7412996",
        "I, the Secretary of State of the State of Delaware, do hereby certify that the "
        "above-named limited liability company was duly formed under the laws of this "
        "State and is in good standing.",
    ]),
    # dba, business_address, industry_code, phone
    "business-license": ("Business Certificate", [
        "City of Boston — Office of the City Clerk",
        "Legal Name: <b>Acme Holdings LLC</b>",
        "Doing Business As: <b>Acme Analytics</b>",
        "Business Address: <b>410 Harbor Street, Suite 900, Boston, MA 02210, US</b>",
        "Primary Activity: Administrative Management and General Management Consulting",
        "NAICS Code: <b>541611</b>",
        "License Number: BOS-2019-88431",
        "Telephone: <b>(617) 555-0142</b>",
        "Issued: 2019-04-02. Valid through: 2027-04-01.",
        "This certificate is issued under Chapter 110, Section 5 of the General Laws "
        "and must be displayed at the place of business.",
    ]),
    # tax_id
    "ein-letter": ("Department of the Treasury — Internal Revenue Service", [
        "Notice of Employer Identification Number Assignment",
        "Date of this notice: 2019-03-18",
        "ACME HOLDINGS LLC",
        "410 HARBOR STREET SUITE 900",
        "BOSTON, MA 02210",
        "Employer Identification Number: <b>88-1234567</b>",
        "Form: SS-4",
        "Thank you for applying for an Employer Identification Number. We assigned you "
        "the EIN shown above. Please keep this notice in your permanent records, and "
        "refer to this number on all federal tax filings and correspondence.",
    ]),
    # tax_id (second source), legal_name confirmation
    "w9": ("Form W-9 — Request for Taxpayer Identification Number and Certification", [
        "1. Name (as shown on your income tax return): <b>Acme Holdings LLC</b>",
        "2. Business name/disregarded entity name, if different from above: "
        "<b>Acme Analytics</b>",
        "3. Federal tax classification: <b>Limited liability company</b> — "
        "tax classification: P (Partnership)",
        "5. Address (number, street, and apt. or suite no.): "
        "<b>410 Harbor Street, Suite 900</b>",
        "6. City, state, and ZIP code: <b>Boston, MA 02210</b>",
        "Part I — Taxpayer Identification Number (TIN)",
        "Employer identification number: <b>88-1234567</b>",
        "Part II — Certification: Under penalties of perjury, I certify that the number "
        "shown on this form is my correct taxpayer identification number.",
        "Signature of U.S. person: <b>Dana Whitfield</b>, Managing Member. Date: 2024-11-08.",
    ]),
    # beneficial_owners[], control_person.
    # The deliberate gap (§8.4): Marcus Vela has no date of birth anywhere.
    "ownership-declaration": ("Beneficial Ownership Certification", [
        "Legal Entity: <b>Acme Holdings LLC</b>",
        "Certification of Beneficial Owners (25% or greater equity interest)",
        "<b>Owner 1</b>",
        "Name: <b>Dana Whitfield</b>",
        "Date of Birth: <b>1978-06-02</b>",
        "Ownership Percentage: <b>55</b>%",
        "Residential Address: <b>88 Beacon Street, Boston, MA 02108, US</b>",
        "Identification: <b>Passport</b>, number <b>X4419223</b>",
        "<b>Owner 2</b>",
        "Name: <b>Marcus Vela</b>",
        "Ownership Percentage: <b>30</b>%",
        "Residential Address: <b>17 Chestnut Lane, Brookline, MA 02445, US</b>",
        "Identification: <b>Passport</b>, number <b>P8830177</b>",
        "<b>Control Person</b>",
        "Name: <b>Dana Whitfield</b>",
        "Title: <b>Managing Member</b>",
        "Date of Birth: <b>1978-06-02</b>",
        "Residential Address: <b>88 Beacon Street, Boston, MA 02108, US</b>",
        "Identification: <b>Passport</b>, number <b>X4419223</b>",
        "This person is an authorized signatory for the account.",
        "Total certified ownership: <b>85</b>% (holders below 25% are not listed)",
        "I certify that the information above is complete and correct to the best of "
        "my knowledge. Signed: Dana Whitfield, Managing Member.",
    ]),
}


def main() -> None:
    for stem, (title, lines) in DOCUMENTS.items():
        _write(stem, title, lines)
        print(f"wrote {OUT / stem}.pdf")


if __name__ == "__main__":
    main()
