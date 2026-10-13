"""D3 adapted from DeepTutor tool_arg_guard.py (Apache-2.0).

Changed to project ToolDefinition.parameters JSON Schema; no runtime/registry
imports. Required/blank/default semantics retained; full Pydantic checks follow.
"""

from dataclasses import dataclass

from app.schemas.providers import ToolDefinition


@dataclass(frozen=True)
class RequiredArg:
    name: str
    type: str = ""
    enum: tuple[str, ...] = ()

    def describe(self) -> str:
        parts = [self.type or "value"]
        if self.enum:
            parts.append("one of: " + " | ".join(self.enum))
        return f"{self.name} ({', '.join(parts)})"


def unsatisfied_required_args(definition: ToolDefinition, args: dict):
    raw = definition.parameters
    names, properties = raw.get("required", []), raw.get("properties", {})
    absent, blank = [], []
    for name in names if isinstance(names, list) else []:
        if not isinstance(name, str) or not name:
            continue
        prop = properties.get(name, {})
        if "default" in prop:
            continue
        arg = RequiredArg(
            name, str(prop.get("type", "")), tuple(str(v) for v in prop.get("enum", []))
        )
        if name not in args or args[name] is None:
            absent.append(arg)
        elif isinstance(args[name], str) and not args[name].strip():
            blank.append(arg)
    return absent, blank


def missing_args_message(tool_name: str, absent, blank):
    clauses = []
    if absent:
        clauses.append("Missing required: " + "; ".join(arg.describe() for arg in absent))
    if blank:
        clauses.append("Present but blank: " + "; ".join(arg.describe() for arg in blank))
    return f"{tool_name}: {'; '.join(clauses)}. Call not dispatched; fill the required values."
