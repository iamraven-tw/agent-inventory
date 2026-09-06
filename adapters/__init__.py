"""Adapter registry. Each adapter module exposes a SPEC dict (see base.py)."""
from . import claude_code, codex, antigravity, cursor, openclaw, hermes

ALL = [claude_code.SPEC, codex.SPEC, antigravity.SPEC, cursor.SPEC, openclaw.SPEC, hermes.SPEC]
BY_ID = {spec["id"]: spec for spec in ALL}


def get(ids=None):
    """Return adapter specs in canonical order, optionally filtered by id list."""
    if not ids:
        return list(ALL)
    return [BY_ID[i] for i in ids if i in BY_ID]
