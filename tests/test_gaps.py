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


def test_an_absent_control_person_is_described_not_a_crash():
    """The escalation input this module exists to describe. `control_person`
    is optional and REQUIRED_FIELD_PATHS walks through it, so resolving
    `control_person.full_name` against a None parent used to raise."""
    found = gaps.compute_gaps(ApplicationFields())
    paths = [g.field_path for g in found]
    assert "control_person.dob" in paths
    assert "control_person" not in paths, \
        "the container is not fillable -- report the leaves the analyst can type into"
    assert all(g.documents_searched for g in found if g.field_path.startswith("control_person"))


def test_an_absent_owner_list_still_reports_the_container():
    """No owners means no leaves to report, so the container IS the gap."""
    paths = [g.field_path for g in gaps.compute_gaps(ApplicationFields())]
    assert "beneficial_owners" in paths


def test_no_reported_gap_makes_apply_edits_blow_up():
    """The console renders one text box per gap and posts whatever is typed,
    so every path `compute_gaps` emits reaches `apply_edits`. A bad VALUE must
    come back as a domain error the analyst can read; the path itself must
    never take an AttributeError or leak a raw ValidationError."""
    app = ApplicationFields()
    for gap in gaps.compute_gaps(app):
        try:
            gaps.apply_edits(app, [FieldEdit(field_path=gap.field_path,
                                             value="not a valid value")])
        except ValueError:
            pass          # a readable refusal is the acceptable outcome
        except Exception as e:            # noqa: BLE001 - that is the point
            raise AssertionError(
                f"{gap.field_path} raised {type(e).__name__}: {e}") from e


def test_the_escalated_leaf_paths_apply_cleanly():
    """The per-field gaps the agent actually escalates on must merge, given a
    value of the right shape -- this is the Approve button's whole job."""
    app = ApplicationFields()
    merged = gaps.apply_edits(app, [
        FieldEdit(field_path="control_person.full_name", value="Dana Whitfield"),
        FieldEdit(field_path="control_person.dob", value="1978-06-02"),
        FieldEdit(field_path="control_person.id_type", value="passport"),
        FieldEdit(field_path="legal_name", value="Acme Holdings LLC"),
    ])
    assert merged.control_person.full_name == "Dana Whitfield"
    assert merged.control_person.dob == date(1978, 6, 2)
    assert merged.legal_name == "Acme Holdings LLC"
    assert app.control_person is None, "the original must not be mutated (§9.1)"


def test_apply_edits_creates_an_absent_optional_parent():
    """Filling `control_person.dob` when there is no control person at all
    has to build one, or the only reachable path is the container."""
    merged = gaps.apply_edits(
        ApplicationFields(),
        [FieldEdit(field_path="control_person.dob", value="1980-01-01")])
    assert merged.control_person is not None
    assert merged.control_person.dob == date(1980, 1, 1)


def test_apply_edits_refuses_an_index_that_does_not_exist():
    """Appending a list member is not something a dotted path can express."""
    import pytest
    with pytest.raises(ValueError, match="no beneficial_owners\\[1\\]"):
        gaps.apply_edits(
            ApplicationFields(beneficial_owners=[BeneficialOwner()]),
            [FieldEdit(field_path="beneficial_owners[1].dob", value="1980-01-01")])


def test_apply_edits_refuses_a_composite_path_readably():
    """A whole-model path handed a line of text must come back as a domain
    error, not a raw ValidationError escaping into the console."""
    import pytest
    with pytest.raises(ValueError, match="registered_address"):
        gaps.apply_edits(ApplicationFields(),
                         [FieldEdit(field_path="registered_address", value="1 Main St")])
