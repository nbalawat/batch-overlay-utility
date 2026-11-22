"""Canonicalisation of artifact references across scheduler dialects.

Each scheduler writes dates and paths differently (%%ODATE in Control-M,
{{ ds_nodash }} in Airflow, $$(BUSDATE) in AutoSys, blob prefixes in ADF).
Canonical keys collapse those differences so producers and consumers can be
matched by the correlation engine.
"""
from __future__ import annotations

import re

from batchiq.domain.models import Artifact, ArtifactType

_DATE_TOKENS = re.compile(
    r"(%%ODATE|&ODATE\.?|\{\{\s*ds_nodash\s*\}\}|\{\{\s*ds\s*\}\}|\$\$\(BUSDATE\)|\$\{BUSDATE\}|\$BUSDATE|\d{8})"
)


def _norm_date(s: str) -> str:
    return _DATE_TOKENS.sub("{date}", s)


def file_artifact(raw: str, *, prefix: bool = False) -> Artifact:
    base = raw.rstrip("/").rsplit("/", 1)[-1]
    return Artifact(type=ArtifactType.FILE, raw=raw, canonical=f"file:{_norm_date(base)}",
                    match="prefix" if prefix else "exact")


def dataset_artifact(uri: str) -> Artifact:
    # warehouse://finance/gl_mart -> data:finance.gl_mart
    path = uri.split("://", 1)[-1].strip("/").replace("/", ".")
    return Artifact(type=ArtifactType.DATASET, raw=uri, canonical=f"data:{path.lower()}")


def table_artifact(schema: str, table: str) -> Artifact:
    return Artifact(type=ArtifactType.TABLE, raw=f"{schema}.{table}",
                    canonical=f"data:{schema.lower()}.{table.lower()}")


_PATH = re.compile(r"(/[\w.\-/%$(){}]+\.(?:dat|csv|ach|txt|xml))")


def paths_in(text: str) -> list[str]:
    return _PATH.findall(text or "")


def data_artifact(name: str) -> Artifact:
    """A table referenced in code (SQL, Spark): schema.table."""
    schema, _, table = name.partition(".")
    return table_artifact(schema, table)
