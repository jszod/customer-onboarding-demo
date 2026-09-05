"""Gap computation and edit merging. Pure and deterministic: safe to import
from workflow code (determinism-protection.md lists models as pass-through)."""
from __future__ import annotations

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
    """Resolve a dotted/indexed path against the model. Deterministic."""
    node = app
    for part in path.replace("]", "").split("."):
        if "[" in part:
            name, idx = part.split("[")
            node = getattr(node, name)[int(idx)]
        else:
            node = getattr(node, part)
    return node


def _expand(app: ApplicationFields, path: str) -> list[str]:
    """`beneficial_owners[].dob` -> one path per owner index."""
    if "[]" not in path:
        return [path]
    prefix, suffix = path.split("[]")
    return [f"{prefix}[{i}]{suffix}" for i in range(len(getattr(app, prefix)))]


def missing_required(app: ApplicationFields) -> list[str]:
    out: list[str] = []
    for template in config.REQUIRED_FIELD_PATHS:
        for path in _expand(app, template):
            value = _get(app, path)
            if value is None or value == [] or value == "":
                out.append(path)
    return out


def compute_gaps(app: ApplicationFields) -> list[FieldGap]:
    return [
        FieldGap(field_path=path,
                 reason=f"{path} not found in any supplied document",
                 documents_searched=_sources_for(path))
        for path in missing_required(app)
    ]


def apply_edits(app: ApplicationFields, edits: list[FieldEdit]) -> ApplicationFields:
    """Returns a NEW application. §9.1: never overwrite the AI's output in place."""
    merged = app.model_copy(deep=True)
    for edit in edits:
        parts = edit.field_path.replace("]", "").split(".")
        node = merged
        for part in parts[:-1]:
            if "[" in part:
                name, idx = part.split("[")
                node = getattr(node, name)[int(idx)]
            else:
                node = getattr(node, part)
        setattr(node, parts[-1], edit.value)
    # Re-validate so strings are coerced to dates/Decimals by the schema.
    # `warnings=False`: between the setattr above and this validate, a field
    # declared `date` or `Decimal` deliberately holds the analyst's raw string.
    # Dumping that intermediate state is the mechanism, not a mistake, so the
    # serializer's type warning is noise on every edit merge (§9.1).
    return ApplicationFields.model_validate(merged.model_dump(warnings=False))
