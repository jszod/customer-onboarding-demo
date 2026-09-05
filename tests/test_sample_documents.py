"""The acme-corp sample document set — §5.2, §8.4.

Five text-layer PDFs. The set is complete except one beneficial owner's date
of birth; that single gap is what the extraction agent escalates and what the
analyst fills at the review gate.
"""
import re
from pathlib import Path

import pytest
from pypdf import PdfReader

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS = REPO_ROOT / "documents" / "acme-corp"

# stem -> DocumentKind (python/models/documents.py)
EXPECTED = {"articles-of-incorporation": "articles_of_incorporation",
            "business-license": "business_license",
            "ein-letter": "ein_letter",
            "w9": "w9",
            "ownership-declaration": "ownership_declaration"}


def _text(stem: str) -> str:
    return "\n".join(p.extract_text() for p in PdfReader(DOCS / f"{stem}.pdf").pages)


def test_all_five_documents_exist():
    for stem in EXPECTED:
        assert (DOCS / f"{stem}.pdf").exists(), f"missing {stem}.pdf"


def test_document_stems_match_document_kind():
    """The five stems are exactly the five DocumentKind values, slugged."""
    from python.models.documents import DocumentKind
    from typing import get_args

    assert set(EXPECTED.values()) == set(get_args(DocumentKind))
    for stem, kind in EXPECTED.items():
        assert stem.replace("-", "_") == kind


@pytest.mark.parametrize("stem", list(EXPECTED))
def test_every_document_has_a_text_layer(stem):
    """§8.3 — text-layer PDFs, not scans. Vision is a documented upgrade."""
    assert len(_text(stem).strip()) > 100


def test_tax_id_appears_in_two_documents():
    """§5.2 — this is what gives the loop something genuine to do."""
    assert "88-1234567" in _text("ein-letter")
    assert "88-1234567" in _text("w9")


def test_both_owners_are_named_with_percentages():
    body = _text("ownership-declaration")
    assert "Dana Whitfield" in body and "55" in body
    assert "Marcus Vela" in body and "30" in body


def test_the_deliberate_gap_second_owner_has_no_dob():
    """§8.4 — the whole escalation beat rests on this."""
    body = _text("ownership-declaration")
    assert "1978-06-02" in body, "Dana's DOB should be present"
    everything = "\n".join(_text(s) for s in EXPECTED)
    assert everything.count("Marcus Vela") >= 1
    # Marcus appears, but no date of birth is given for him anywhere. Bound his
    # block by the next section header rather than a character count, so the
    # assertion cannot pass by accident of layout.
    after_marcus = body.split("Marcus Vela", 1)[1]
    assert "Control Person" in after_marcus, "expected a Control Person section after Owner 2"
    marcus_block = after_marcus.split("Control Person", 1)[0]
    assert not any(tok in marcus_block for tok in ("Date of Birth", "DOB", "Born"))
    # And no bare date either — an unlabelled 1981-04-17 would fill the gap too.
    assert not re.search(r"\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}", marcus_block)


def test_no_other_document_supplies_the_missing_dob():
    """The gap must survive the agent reading every document (§8.4)."""
    for stem in EXPECTED:
        if stem == "ownership-declaration":
            continue
        assert "Marcus" not in _text(stem), f"{stem} mentions Marcus; the gap must be unfillable"


def test_ownership_sums_under_100():
    """§9.1 rule 5 — <=, not ==; owners below 25% are not listed."""
    body = _text("ownership-declaration")
    assert "85" in body or ("55" in body and "30" in body)


def test_required_application_fields_are_all_sourced():
    """§8.4 — the set is complete *except* the one dob."""
    everything = "\n".join(_text(s) for s in EXPECTED)
    for token in (
        "Acme Holdings LLC",          # legal_name
        "Acme Analytics",             # dba
        "Limited Liability Company",  # entity_type
        "2019-03-11",                 # formation_date
        "Delaware",                   # formation_state
        "88-1234567",                 # tax_id
        "1209 Orange Street",         # registered_address
        "410 Harbor Street",          # business_address
        "541611",                     # industry_code
        "Dana Whitfield",             # beneficial owner 1 / control person
        "Marcus Vela",                # beneficial owner 2
        "Managing Member",            # control_person.title
        "X4419223",                   # owner 1 id_number
        "P8830177",                   # owner 2 id_number
    ):
        assert token in everything, f"no document carries {token!r}"
