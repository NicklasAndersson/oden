"""Routing: which branch (gren) a message goes to, and which steps run there.

The first thing that happens to a stored message is the *vägval*: its source —
a Signal group, a direct message, or TAK — is assigned to exactly one branch.
Inside the branch an ordinary chain of pipeline steps runs, first handler wins,
exactly like the single chain did before. A branch marked ``ignore`` has no
steps: its messages are stored (and visible in Flöde) but never written.

Stored as the config key ``routing``::

    {
      "version": 1,
      "branches": [
        {"id": "main", "name": "Huvudgren", "ignore": false,
         "steps": [{"pipeline": "seven_s", "enabled": true, "config": {}}, ...]},
        {"id": "ignore", "name": "Ignorera", "ignore": true, "steps": []}
      ],
      "assign": {"group:Kaffe & logistik": "ignore", "source:tak": "main"},
      "default": "main"
    }

Assignment keys, checked in this order: ``source:tak`` (anything from the TAK
listener), ``group_id:<id>``, ``group:<name>``, ``source:direct`` (no group);
anything unassigned goes to ``default``.

A step's ``config`` overrides that pipeline's global settings for this branch
only (e.g. ``vault_subdir``); pipelines read it through :func:`step_settings`.

Before routing existed there was one chain (``enabled_pipelines``) and a
``group_filter`` step with a black- or whitelist. :func:`derive_from_legacy`
turns that into branches with the same outcome; ``config._migrate_routing``
stores it once, and the legacy keys are left alone for a downgrade.
"""

from __future__ import annotations

import contextvars
import re
from typing import Any

ROUTER = "router"  # pipeline_runs.pipeline_name of the vägval step
FALLBACK = "generic_template"
SIDE_EFFECT = "tak_publish"  # added per branch when TAK publishing is on

# Pipelines a branch can contain (group_filter is replaced by the vägval itself).
STEP_PIPELINES = ("seven_s", "fors", "pedars", "scrim", FALLBACK)

MAIN_ID = "main"
IGNORE_ID = "ignore"

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
# Steps from Rapportformat (report_formats.py): "format:<id>". Checked here by
# shape only; a step whose format was deleted is skipped when the branch runs.
_FORMAT_STEP_RE = re.compile(r"^format:[a-z0-9][a-z0-9_-]{0,39}$")
_DEFAULT_CHAIN = ["seven_s", "fors", "pedars", "scrim", FALLBACK]

_step_config: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar("oden_step_config", default=None)


# ---------------------------------------------------------------------------
# Per-step settings
# ---------------------------------------------------------------------------


def set_step_config(config: dict[str, Any] | None) -> contextvars.Token:
    """Make ``config`` the current step's overrides (the orchestrator does this per step)."""
    return _step_config.set(dict(config or {}))


def reset_step_config(token: contextvars.Token) -> None:
    _step_config.reset(token)


def step_settings(pipeline_name: str, pipeline_settings: Any) -> dict[str, Any]:
    """A pipeline's global settings with the running step's overrides on top."""
    base = pipeline_settings.get(pipeline_name, {}) if isinstance(pipeline_settings, dict) else {}
    base = base if isinstance(base, dict) else {}
    return {**base, **(_step_config.get() or {})}


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


def _slug(name: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower().translate(str.maketrans("åäö", "aao"))).strip("-")[:32] or "gren"
    candidate, n = base, 2
    while candidate in taken:
        candidate, n = f"{base}-{n}", n + 1
    return candidate


def is_step_name(name: Any) -> bool:
    """A built-in step pipeline or a Rapportformat step (``format:<id>``)."""
    return isinstance(name, str) and (name in STEP_PIPELINES or bool(_FORMAT_STEP_RE.match(name)))


def _normalize_step(value: Any) -> dict[str, Any] | None:
    if isinstance(value, str):
        value = {"pipeline": value}
    if not isinstance(value, dict) or not is_step_name(value.get("pipeline")):
        return None
    config = value.get("config") if isinstance(value.get("config"), dict) else {}
    return {"pipeline": value["pipeline"], "enabled": value.get("enabled", True) is not False, "config": config}


def normalize_routing(value: Any) -> dict[str, Any]:
    """Validate and clean a routing dict. Raises ValueError with a Swedish message."""
    if not isinstance(value, dict):
        raise ValueError("Vägvalet måste vara ett objekt")
    raw_branches = value.get("branches")
    if not isinstance(raw_branches, list) or not raw_branches:
        raise ValueError("Minst en gren krävs")

    branches: list[dict[str, Any]] = []
    ids: set[str] = set()
    for raw in raw_branches:
        if not isinstance(raw, dict):
            raise ValueError("Varje gren måste vara ett objekt")
        name = str(raw.get("name") or "").strip()
        if not name:
            raise ValueError("Varje gren behöver ett namn")
        branch_id = str(raw.get("id") or "").strip() or _slug(name, ids)
        if not _ID_RE.match(branch_id) or branch_id in ids:
            raise ValueError(f"Ogiltigt eller dubblerat gren-id: {branch_id!r}")
        ids.add(branch_id)
        ignore = bool(raw.get("ignore"))
        steps: list[dict[str, Any]] = []
        if not ignore:
            seen: set[str] = set()
            for raw_step in raw.get("steps") or []:
                step = _normalize_step(raw_step)
                if step is None or step["pipeline"] in seen:
                    continue
                seen.add(step["pipeline"])
                steps.append(step)
            # The fallback always ends a non-ignore branch, as it always ended the chain.
            # Switched off, whatever no step takes is only kept in Flöde (status ignored).
            steps = [s for s in steps if s["pipeline"] != FALLBACK] + [
                next(
                    (s for s in steps if s["pipeline"] == FALLBACK),
                    {"pipeline": FALLBACK, "enabled": True, "config": {}},
                )
            ]
        branches.append({"id": branch_id, "name": name[:60], "ignore": ignore, "steps": steps})

    # "Ignorera" is a choice, not a column: there is always one ignore branch
    # to assign sources to, whether or not anything uses it yet.
    if not any(b["ignore"] for b in branches):
        ignore_id = IGNORE_ID if IGNORE_ID not in ids else _slug("Ignorera", ids)
        ids.add(ignore_id)
        branches.append({"id": ignore_id, "name": "Ignorera", "ignore": True, "steps": []})

    default = str(value.get("default") or "")
    if default not in ids:
        raise ValueError("Standardgrenen måste vara en av grenarna")

    assign: dict[str, str] = {}
    raw_assign = value.get("assign") or {}
    if not isinstance(raw_assign, dict):
        raise ValueError("Tilldelningen måste vara ett objekt")
    for key, branch_id in raw_assign.items():
        key = str(key).strip()
        if not key or not re.match(r"^(source:(tak|direct)|group:.+|group_id:.+)$", key):
            raise ValueError(f"Okänd källa: {key!r}")
        if branch_id not in ids:
            raise ValueError(f"Källan {key!r} pekar på en gren som inte finns")
        assign[key] = branch_id

    return {"version": 1, "branches": branches, "assign": assign, "default": default}


def derive_from_legacy(enabled_pipelines: Any, pipeline_settings: Any) -> dict[str, Any]:
    """The routing that behaves exactly like the old single chain + group filter.

    * blacklist: listed groups → Ignorera, everything else → Huvudgren.
    * whitelist: listed groups (and direct messages, which the old filter let
      through because they have no group) → Huvudgren, everything else → Ignorera.
    * no filter (not enabled, or no groups): everything → Huvudgren.

    group_filter used to be a step and could in theory sit after a report step;
    it is always a vägval now, applied before any step.
    """
    chain = [n for n in (enabled_pipelines or _DEFAULT_CHAIN) if isinstance(n, str)]
    steps = [{"pipeline": n, "enabled": True, "config": {}} for n in chain if n in STEP_PIPELINES]
    main = {"id": MAIN_ID, "name": "Huvudgren", "ignore": False, "steps": steps}
    ignore = {"id": IGNORE_ID, "name": "Ignorera", "ignore": True, "steps": []}

    gf = (pipeline_settings or {}).get("group_filter") if isinstance(pipeline_settings, dict) else None
    gf = gf if isinstance(gf, dict) else {}
    groups = [g.strip() for g in gf.get("groups") or [] if isinstance(g, str) and g.strip()]
    filter_on = "group_filter" in chain and bool(groups)

    assign: dict[str, str] = {}
    default = MAIN_ID
    if filter_on and gf.get("mode") == "whitelist":
        assign = {f"group:{g}": MAIN_ID for g in groups}
        assign["source:direct"] = MAIN_ID
        default = IGNORE_ID
    elif filter_on:
        assign = {f"group:{g}": IGNORE_ID for g in groups}

    return normalize_routing({"branches": [main, ignore], "assign": assign, "default": default})


def load_routing(config_module: Any) -> dict[str, Any]:
    """The routing in effect: the stored one, else derived from the legacy settings."""
    stored = getattr(config_module, "ROUTING", None)
    if stored:
        try:
            return normalize_routing(stored)
        except ValueError:
            pass
    return derive_from_legacy(
        getattr(config_module, "ENABLED_PIPELINES", None), getattr(config_module, "PIPELINE_SETTINGS", None)
    )


def branch_by_id(routing: dict[str, Any], branch_id: str) -> dict[str, Any] | None:
    return next((b for b in routing["branches"] if b["id"] == branch_id), None)


# ---------------------------------------------------------------------------
# Vägval
# ---------------------------------------------------------------------------


def message_source(msg_data: dict[str, Any]) -> dict[str, str | None]:
    """``{"tak": bool, "group_id", "group_name"}`` of a stored message."""
    envelope = msg_data.get("envelope", {}) if isinstance(msg_data, dict) else {}
    envelope = envelope if isinstance(envelope, dict) else {}
    dm = envelope.get("dataMessage") or {}
    meta = dm.get("groupV2") or dm.get("group") or dm.get("groupInfo") or {}
    return {
        "tak": envelope.get("_source") == "tak",
        "group_id": meta.get("id") or meta.get("groupId"),
        "group_name": meta.get("name") or meta.get("title") or meta.get("groupName"),
    }


def resolve_branch(routing: dict[str, Any], msg_data: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """``(branch, reason)`` for a message. The reason is shown in Flöde."""
    branch, reason, _ = resolve_branch_detail(routing, msg_data)
    return branch, reason


def resolve_branch_detail(routing: dict[str, Any], msg_data: dict[str, Any]) -> tuple[dict[str, Any], str, str | None]:
    """``(branch, reason, assignment key)``; the key is None when the default branch was used."""
    src = message_source(msg_data)
    assign = routing["assign"]
    candidates: list[tuple[str, str]] = []
    if src["tak"]:
        candidates.append(("source:tak", "Källan TAK"))
    if src["group_id"]:
        candidates.append((f"group_id:{src['group_id']}", f"Gruppen ”{src['group_name'] or src['group_id']}”"))
    if src["group_name"]:
        candidates.append((f"group:{src['group_name']}", f"Gruppen ”{src['group_name']}”"))
    if not src["group_id"] and not src["group_name"] and not src["tak"]:
        candidates.append(("source:direct", "Direktmeddelanden"))

    for key, label in candidates:
        branch = branch_by_id(routing, assign.get(key, ""))
        if branch is not None:
            return branch, f"{label} är tilldelad grenen ”{branch['name']}”", key

    branch = branch_by_id(routing, routing["default"]) or routing["branches"][0]
    what = candidates[0][1] if candidates else "Källan"
    return branch, f"{what} har ingen egen gren → standardgrenen ”{branch['name']}”", None


def group_branch(routing: dict[str, Any], group_id: str | None, group_name: str | None) -> tuple[dict[str, Any], bool]:
    """``(branch, assigned)`` for a Signal group — what its messages would get."""
    group = {k: v for k, v in (("id", group_id), ("name", group_name)) if v}
    branch, _, key = resolve_branch_detail(routing, {"envelope": {"dataMessage": {"groupV2": group}}})
    return branch, key is not None


def branch_steps(branch: dict[str, Any], *, publish_to_tak: bool) -> list[dict[str, Any]]:
    """The enabled steps that run in ``branch``, TAK publishing first when it is on."""
    if branch.get("ignore"):
        return []
    steps = [s for s in branch["steps"] if s.get("enabled", True)]
    if publish_to_tak:
        steps = [{"pipeline": SIDE_EFFECT, "enabled": True, "config": {}}, *steps]
    return steps


def assigned_sources(routing: dict[str, Any]) -> dict[str, list[str]]:
    """Branch id → the source keys assigned to it (for the GUI)."""
    result: dict[str, list[str]] = {b["id"]: [] for b in routing["branches"]}
    for key, branch_id in routing["assign"].items():
        result.setdefault(branch_id, []).append(key)
    return result
