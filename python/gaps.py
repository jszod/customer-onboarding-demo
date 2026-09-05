"""Gap computation and edit merging. Pure and deterministic: safe to import
from workflow code (determinism-protection.md lists models as pass-through)."""
from __future__ import annotations

from typing import get_args

from pydantic import BaseModel, ValidationError

from python import config
from python.models.application import ApplicationFields
from python.models.extraction import FieldGap
from python.models.review import FieldEdit


def _sources_for(path: str) -> list[str]:
    base = path.split("[")[0].split(".")[0]
    if base in ("beneficial_owners", "control_person"):
        return list(config._OWNERSHIP_SOURCES)
    return list(config.FIELD_SOURCES.get(path, ()))


def _get(app: ApplicationFields, path: str):
    """Resolve a dotted/indexed path against the model. Deterministic.

    An absent parent yields None rather than raising: `control_person` is
    optional and `REQUIRED_FIELD_PATHS` walks THROUGH it, so an application
    that named no control person at all -- the escalation case this module
    exists to describe -- would otherwise take an attribute error on None.
    """
    node = app
    for part in path.replace("]", "").split("."):
        if node is None:
            return None
        if "[" in part:
            name, idx = part.split("[")
            seq = getattr(node, name) or []
            if int(idx) >= len(seq):
                return None
            node = seq[int(idx)]
        else:
            node = getattr(node, part)
    return node


def _expand(app: ApplicationFields, path: str) -> list[str]:
    """`beneficial_owners[].dob` -> one path per owner index."""
    if "[]" not in path:
        return [path]
    prefix, suffix = path.split("[]")
    return [f"{prefix}[{i}]{suffix}"
            for i in range(len(getattr(app, prefix) or []))]


def missing_required(app: ApplicationFields) -> list[str]:
    out: list[str] = []
    for template in config.REQUIRED_FIELD_PATHS:
        for path in _expand(app, template):
            value = _get(app, path)
            if value is None or value == [] or value == "":
                out.append(path)
    # A missing `control_person` makes every `control_person.*` leaf missing
    # too, and reporting both gives the analyst a row they cannot fill: the
    # console renders one text box per gap, and no string builds a
    # ControlPerson. Keep the leaves -- those are fillable, and applying one
    # creates the parent -- and drop the container that contains them.
    # `beneficial_owners` with no owners has no leaves, so it survives, which
    # is right: "there are no owners" is the gap.
    return [p for p in out
            if not any(q != p and (q.startswith(f"{p}.") or q.startswith(f"{p}["))
                       for q in out)]


def compute_gaps(app: ApplicationFields) -> list[FieldGap]:
    return [
        FieldGap(field_path=path,
                 reason=f"{path} not found in any supplied document",
                 documents_searched=_sources_for(path))
        for path in missing_required(app)
    ]


def _model_type_of(parent_cls: type[BaseModel], field: str) -> type[BaseModel] | None:
    """The model class behind an optional model field: `ControlPerson | None`
    -> `ControlPerson`. None when the field is not a model."""
    annotation = parent_cls.model_fields[field].annotation
    for candidate in get_args(annotation) or (annotation,):
        if isinstance(candidate, type) and issubclass(candidate, BaseModel):
            return candidate
    return None


def apply_edits(app: ApplicationFields, edits: list[FieldEdit]) -> ApplicationFields:
    """Returns a NEW application. §9.1: never overwrite the AI's output in place.

    Every path `compute_gaps` can report has to be applicable here, or the
    analyst is shown a gap the Approve button cannot close. Two of them used
    to raise: a leaf under an absent optional parent, and a whole-model path
    like `registered_address` handed a plain string.
    """
    merged = app.model_copy(deep=True)
    for edit in edits:
        parts = edit.field_path.replace("]", "").split(".")
        node = merged
        for part in parts[:-1]:
            if "[" in part:
                name, idx = part.split("[")
                seq = getattr(node, name) or []
                if int(idx) >= len(seq):
                    # Nothing to append TO: growing a list from a dotted path
                    # is not something an edit can express (§18).
                    raise ValueError(
                        f"{edit.field_path}: there is no {name}[{idx}] to edit")
                node = seq[int(idx)]
            else:
                child = getattr(node, part)
                if child is None:
                    # The absent parent IS the gap. Build it so the leaf edit
                    # has somewhere to land -- otherwise the only reachable
                    # path is the container, which no text box can fill.
                    model_cls = _model_type_of(type(node), part)
                    if model_cls is None:
                        raise ValueError(
                            f"{edit.field_path}: {part} is empty and is not "
                            f"something an edit can create")
                    child = model_cls()
                    setattr(node, part, child)
                node = child
        setattr(node, parts[-1], edit.value)
    # Re-validate so strings are coerced to dates/Decimals by the schema.
    # `warnings=False`: between the setattr above and this validate, a field
    # declared `date` or `Decimal` deliberately holds the analyst's raw string.
    # Dumping that intermediate state is the mechanism, not a mistake, so the
    # serializer's type warning is noise on every edit merge (§9.1).
    try:
        return ApplicationFields.model_validate(merged.model_dump(warnings=False))
    except ValidationError as e:
        # Reached by editing a composite path -- `registered_address` wants an
        # object, not a line of text. A validator raising ValueError refuses
        # the update with a message the analyst can read; letting the raw
        # ValidationError out surfaces as a 500 on the console instead.
        edited = ", ".join(edit.field_path for edit in edits) or "no fields"
        raise ValueError(f"the edits ({edited}) do not produce a valid "
                         f"application: {e}") from e
