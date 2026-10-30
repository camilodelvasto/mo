import re
from dataclasses import dataclass


@dataclass
class Field:
    name: str
    type: str
    label: str
    values: list[str] | None = None
    align: str | None = None
    description: str | None = None
    action: str | None = None
    key: str | None = None


def auto_label(name: str) -> str:
    return name.replace("_", " ").title()


def default_align(ftype: str) -> str:
    return "right" if ftype in ("number", "integer") else "left"


def parse_fields(sheet_yaml: dict) -> list[Field]:
    fields = []
    for name, spec in sheet_yaml["fields"].items():
        if isinstance(spec, str):
            ftype, values = _parse_type_string(spec)
            field = Field(
                name=name,
                type=ftype,
                label=auto_label(name),
                values=values,
                align=default_align(ftype),
            )
        else:
            ftype = spec["type"]
            field = Field(
                name=name,
                type=ftype,
                label=spec.get("label", auto_label(name)),
                values=spec.get("values"),
                align=spec.get("align", default_align(ftype)),
                description=spec.get("description"),
                action=spec.get("action"),
                key=spec.get("key"),
            )
        if ftype == "enum" and not field.values:
            raise ValueError(f"Field '{name}' is enum but declares no values")
        fields.append(field)
    return fields


def _parse_type_string(spec: str) -> tuple[str, list[str] | None]:
    if spec.startswith("enum"):
        match = re.search(r"\[(.+)]", spec)
        if match:
            values = [v.strip() for v in match.group(1).split(",")]
            return "enum", values
    return spec, None
