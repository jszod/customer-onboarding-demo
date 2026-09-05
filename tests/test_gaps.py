from datetime import date
from decimal import Decimal

from python import gaps
from python.models.application import Address, ApplicationFields, BeneficialOwner, ControlPerson
from python.models.review import FieldEdit


def _addr() -> Address:
    return Address(line1="410 Harbor St", line2=None, city="Boston",
                   state="MA", postal_code="02210", country="US")


def _owner(name: str, dob: date | None, pct: str) -> BeneficialOwner:
    return BeneficialOwner(full_name=name, dob=dob, ownership_pct=Decimal(pct),
                           residential_address=_addr(), id_type="passport",
                           id_number="X4419223")


def _complete_except_second_dob() -> ApplicationFields:
    return ApplicationFields(
        legal_name="Acme Holdings LLC", dba=None, entity_type="LLC",
        formation_date=date(2019, 3, 11), formation_state="DE", tax_id="88-1234567",
        registered_address=_addr(), business_address=_addr(), industry_code="541611",
        phone=None, website=None,
        beneficial_owners=[_owner("Dana Whitfield", date(1978, 6, 2), "55"),
                           _owner("Marcus Vela", None, "30")],
        control_person=ControlPerson(full_name="Dana Whitfield", title="Managing Member",
                                     dob=date(1978, 6, 2), residential_address=_addr(),
                                     id_type="passport", id_number="X4419223"),
    )


def test_the_deliberate_gap_is_the_only_gap():
    """§8.4 — the acme-corp set is complete except one owner's dob."""
    found = gaps.compute_gaps(_complete_except_second_dob())
    assert [g.field_path for g in found] == ["beneficial_owners[1].dob"]


def test_optional_fields_are_never_gaps():
    """§5.1 — exactly three fields are optional."""
    app = _complete_except_second_dob()
    app.beneficial_owners[1].dob = date(1985, 1, 1)
    assert gaps.compute_gaps(app) == []


def test_empty_owner_list_is_a_gap():
    app = _complete_except_second_dob()
    app.beneficial_owners = []
    assert "beneficial_owners" in [g.field_path for g in gaps.compute_gaps(app)]


def test_gap_records_documents_searched():
    g = gaps.compute_gaps(_complete_except_second_dob())[0]
    assert "ownership_declaration" in g.documents_searched
    assert g.reason


def test_apply_edits_fills_the_gap_without_mutating_the_original():
    """§9.1 audit rule — never overwrite the AI's output in place."""
    original = _complete_except_second_dob()
    merged = gaps.apply_edits(original, [FieldEdit(field_path="beneficial_owners[1].dob",
                                                   value="1985-01-01")])
    assert merged.beneficial_owners[1].dob == date(1985, 1, 1)
    assert original.beneficial_owners[1].dob is None
    assert gaps.compute_gaps(merged) == []


def test_apply_edits_coerces_to_the_schema_type():
    merged = gaps.apply_edits(_complete_except_second_dob(),
                              [FieldEdit(field_path="beneficial_owners[0].ownership_pct",
                                         value="45.5")])
    assert merged.beneficial_owners[0].ownership_pct == Decimal("45.5")
