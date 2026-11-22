"""Small serialisers shared by the view modules."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from batchiq.knowledge.graph import Edge, Node

VENDOR_LABEL = {"control-m": "Control-M", "autosys": "AutoSys", "airflow": "Airflow", "azure-data-factory": "ADF"}


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec="minutes") if dt else None


def node_dict(n: Node) -> dict[str, Any]:
    return {"id": n.id, "type": n.type.value, "label": n.label, "props": n.props}


def edge_dict(e: Edge) -> dict[str, Any]:
    return {"id": e.id, "source": e.source, "target": e.target, "type": e.type.value,
            "provenance": sorted(p.value for p in e.provenance), "confidence": round(e.confidence, 3),
            "refs": e.refs, "props": e.props}


def jsonable(v: Any) -> Any:
    """Make review history and similar dicts JSON-friendly (datetimes to ISO)."""
    if isinstance(v, datetime):
        return iso(v)
    if isinstance(v, dict):
        return {k: jsonable(x) for k, x in v.items()}
    if isinstance(v, list | tuple):
        return [jsonable(x) for x in v]
    return v
