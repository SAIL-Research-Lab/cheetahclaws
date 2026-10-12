"""Skill tool: lets the model invoke skills by name via tool call."""
from __future__ import annotations

from cheetahclaws.tool_registry import ToolDef, register_tool
from .loader import find_skill, load_skills, substitute_arguments


_SKILL_SCHEMA = {
    "name": "Skill",
    "description": (
        "Invoke a named skill (reusable prompt template). "
        "Use SkillList to see available skills and their triggers."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Skill name (e.g. 'commit', 'review')",
            },
            "args": {
                "type": "string",
                "description": "Arguments to pass to the skill (replaces $ARGUMENTS)",
                "default": "",
            },
        },
        "required": ["name"],
    },
}

_SKILL_LIST_SCHEMA = {
    "name": "SkillList",
    "description": "List all available skills with their names, triggers, and descriptions.",
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}


_JSON_TYPE_NAMES = {
    dict: "object", list: "array", bool: "boolean",
    int: "number", float: "number", type(None): "null",
}

_USAGE_EXAMPLE = 'Example: {"name": "commit", "args": "fix login bug"}'


def _json_type(value) -> str:
    return _JSON_TYPE_NAMES.get(type(value), type(value).__name__)


def _coerce_args(raw) -> str | None:
    """Normalize the `args` param to a string, or None if it can't be.

    Weak models on OpenAI-compatible providers often ignore the declared
    string type and wrap the value (`{"args": "..."}`), split it into a list,
    or send null. Accept the unambiguous shapes rather than failing the call.
    """
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict) and len(raw) == 1:
        (value,) = raw.values()
        return value if isinstance(value, str) else None
    if isinstance(raw, list) and all(isinstance(v, str) for v in raw):
        return " ".join(raw)
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return str(raw)
    return None


def _skill_tool(params: dict, config: dict) -> str:
    """Execute a skill by name and return its output."""
    skill_name = params.get("name", "")
    if not isinstance(skill_name, str):
        return (
            f'Error: Skill "name" must be a string (got {_json_type(skill_name)}). '
            f"{_USAGE_EXAMPLE}"
        )
    skill_name = skill_name.strip()

    raw_args = params.get("args", "")
    args = _coerce_args(raw_args)
    if args is None:
        got = _json_type(raw_args)
        if isinstance(raw_args, dict) and raw_args:
            # Name the keys: a model that sent {"corpus": …, "k": …} can see
            # which of its own fields to fold into the one string.
            got += f" with keys {sorted(map(str, raw_args))}"
        return (
            f'Error: Skill "args" must be a string (got {got}). '
            f"{_USAGE_EXAMPLE}"
        )

    # Look up by name first, then by trigger
    skill = None
    for s in load_skills():
        if s.name == skill_name:
            skill = s
            break
    if skill is None:
        skill = find_skill(skill_name)
    if skill is None:
        names = [s.name for s in load_skills()]
        return f"Error: skill '{skill_name}' not found. Available: {', '.join(names)}"

    rendered = substitute_arguments(skill.prompt, args, skill.arguments)
    message = f"[Skill: {skill.name}]\n\n{rendered}"

    # Run inline via agent and collect text output
    from cheetahclaws import agent as _agent
    from cheetahclaws.providers import TextChunk
    system_prompt = config.get("_system_prompt", "")

    # Streamed text is only the fallback (see _final_answer). ThinkingChunk
    # also carries `.text`, so match the type: reasoning must not be returned.
    streamed: list[str] = []
    sub_state = _agent.AgentState()
    sub_config = {**config, "_depth": config.get("_depth", 0) + 1}
    try:
        for event in _agent.run(message, sub_state, sub_config, system_prompt):
            if isinstance(event, TextChunk):
                streamed.append(event.text)
    except Exception as e:
        return f"Skill execution error: {e}"

    return (
        _final_answer(sub_state.messages)
        or "".join(streamed).strip()
        or "(skill completed with no text output)"
    )


def _final_answer(messages: list) -> str:
    """Text of the sub-run's last assistant turn, or "" if it has none.

    The parent asked for the skill's answer, not a transcript: the narration
    before each tool call and the agent's own status lines ("[Retry 1/3 …]")
    are noise there, and they push the answer itself past the tool output cap.
    A run that died before completing a turn (API failure) leaves no assistant
    message, so the caller falls back to whatever was streamed.
    """
    for msg in reversed(messages):
        if msg.get("role") == "assistant":
            content = msg.get("content")
            return content.strip() if isinstance(content, str) else ""
    return ""


def _skill_list_tool(params: dict, config: dict) -> str:
    skills = load_skills()
    if not skills:
        return "No skills available."
    lines = ["Available skills:\n"]
    for s in skills:
        triggers = ", ".join(s.triggers)
        hint = f"  args: {s.argument_hint}" if s.argument_hint else ""
        when = f"\n    when: {s.when_to_use}" if s.when_to_use else ""
        lines.append(f"- **{s.name}** [{triggers}]{hint}\n  {s.description}{when}")
    return "\n".join(lines)


def _register() -> None:
    register_tool(ToolDef(
        name="Skill",
        schema=_SKILL_SCHEMA,
        func=_skill_tool,
        read_only=False,
        concurrent_safe=False,
    ))
    register_tool(ToolDef(
        name="SkillList",
        schema=_SKILL_LIST_SCHEMA,
        func=_skill_list_tool,
        read_only=True,
        concurrent_safe=True,
    ))


_register()
