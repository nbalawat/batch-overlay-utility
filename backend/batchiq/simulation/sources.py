"""Simulated source repositories: the code behind each job, as a client keeps it.

At a client, a job's definition says *when* it runs; its source (JCL in Endevor,
shell scripts in git, Airflow DAG files, ADF ARM templates and Databricks
notebooks) says *what it actually does*. These renderers turn the ground-truth
``effects`` into realistic source text in each dialect. The overlay's miner
then has to read that text back with regexes, exactly as it would for real.
"""
from __future__ import annotations

import json
from collections import defaultdict

from batchiq.domain.models import JobKind, Vendor
from batchiq.simulation.estate import JobSpec, SchedulerSpec


def _effects(spec: JobSpec) -> list[list[str]]:
    return [e.split(" ", 2) for e in spec.effects]


def _p(path: str, token: str) -> str:
    return path.replace("{date}", token)


# ---------------------------------------------------------------------- Control-M: JCL
def _jcl(spec: JobSpec) -> str:
    member = spec.command.split()[0].lstrip("/")
    out = [f"{spec.command},CLASS=A,MSGCLASS=X,NOTIFY=&SYSUID",
           f"//* {spec.description or spec.name.replace('_', ' ').title()}   OWNER: {spec.owner}",
           "//JOBLIB   DD DSN=PRD.LOADLIB,DISP=SHR",
           f"//STEP010  EXEC PGM={member[:6]}10"]
    step = 20
    for parts in _effects(spec):
        verb = parts[0]
        if verb in ("read", "write") and parts[1] == "file":
            opts = "ORDONLY" if verb == "read" else "OWRONLY,OCREAT"
            dd = "INFILE" if verb == "read" else "OUTFILE"
            out.append(f"//{dd:<8} DD PATH='{_p(parts[2], '&ODATE.')}',PATHOPTS=({opts})")
        elif verb in ("read", "write") and parts[1] == "table":
            stmt = (f"SELECT * FROM {parts[2].upper()} WHERE BUS_DT = :ODATE" if verb == "read"
                    else f"INSERT INTO {parts[2].upper()} SELECT * FROM SESSION.WORK")
            out += [f"//STEP{step:03d}  EXEC PGM=IKJEFT01", "//SYSTSIN  DD *", " DSN SYSTEM(DB2P)",
                    " RUN PROGRAM(DSNTEP2) PLAN(DSNTEP2)", "//SYSIN    DD *", f"  {stmt};", "/*"]
            step += 10
        elif verb == "sftp":
            host, path = parts[2].split(":", 1)
            local = next((e.split(" ", 2)[2] for e in spec.effects if e.startswith("write file")),
                         f"/tmp/{spec.name.lower()}.dat")
            out += [f"//STEP{step:03d}  EXEC PGM=BPXBATCH,",
                    f"//         PARM='SH sftp -b /u/batch/{member.lower()}.sftp batch@{host}'",
                    "//STDIN    DD *", f"{parts[1]} {_p(local, '&ODATE.')} {_p(path, '&ODATE.')}", "/*"]
            step += 10
        elif verb == "mq":
            pgm = "MQPUT" if parts[1] == "put" else "MQGET"
            out.append(f"//STEP{step:03d}  EXEC PGM={pgm},PARM='QMGR=QMPRD QUEUE={parts[2]}'")
            step += 10
        elif verb == "mail":
            addr, subject = parts[1], parts[2] if len(parts) > 2 else spec.name
            out += ["//NOTIFY   EXEC PGM=IEBGENER", "//SYSUT2   DD SYSOUT=(B,SMTP)", "//SYSUT1   DD *",
                    "HELO ZOSPRD01", "MAIL FROM:<batch@bank.example>", f"RCPT TO:<{addr}>", "DATA",
                    f"Subject: {subject}", ".", "/*"]
    out.append("//")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------- AutoSys: shell
def _shell(spec: JobSpec) -> str:
    out = ["#!/bin/ksh", f"# {spec.command.split()[0]}  owner: {spec.owner}  app: {spec.app}",
           "set -euo pipefail", ". /opt/batch/etc/batch_env.sh", 'BUSDATE=${1:-$(date +%Y%m%d)}', ""]
    for parts in _effects(spec):
        verb = parts[0]
        if verb == "read" and parts[1] == "file":
            out += [f"IN_FILE={_p(parts[2], '${BUSDATE}')}",
                    '[ -s "$IN_FILE" ] || { echo "input $IN_FILE missing" >&2; exit 2; }']
        elif verb == "write" and parts[1] == "file":
            out.append(f"OUT_FILE={_p(parts[2], '${BUSDATE}')}")
        elif verb in ("read", "write") and parts[1] == "table":
            sql = (f"SELECT acct_id, amount FROM {parts[2]} WHERE bus_date = TO_DATE('$BUSDATE','YYYYMMDD');"
                   if verb == "read" else f"INSERT INTO {parts[2]} SELECT * FROM stage_{parts[2].split('.')[1]};")
            out += ['sqlplus -s "$DB_USER@$DB_TNS" <<SQL', "WHENEVER SQLERROR EXIT FAILURE", sql, "SQL"]
        elif verb == "sftp":
            host, path = parts[2].split(":", 1)
            has_out = any(e.startswith("write file") for e in spec.effects)
            local = ("$OUT_FILE" if has_out else "/var/batch/out/*") if parts[1] == "put" else "/var/batch/in/"
            remote = _p(path, "${BUSDATE}")
            line = f"put {local} {remote}" if parts[1] == "put" else f"get {remote} {local}"
            out += [f"sftp -b - -o BatchMode=yes batch@{host} <<EOF", line, "EOF"]
        elif verb == "mail":
            addr, subject = parts[1], parts[2] if len(parts) > 2 else spec.name
            out.append(f'echo "{subject} for $BUSDATE" | mailx -s "{subject}" {addr}')
        elif verb == "api":
            out.append(f'curl -sf -X {parts[1]} -H "Authorization: Bearer $API_TOKEN" "{parts[2]}"')
        elif verb == "mq":
            tool = "amqsput" if parts[1] == "put" else "amqsget"
            out.append(f"/opt/mqm/samp/bin/{tool} {parts[2]} QMPAY01")
        elif verb == "secret":
            out.append('DB_PASSWORD="Tr3asury!2024"   # TODO move to vault')
    out += ["", f"{spec.command.split()[0].replace('.sh', '')}.bin " + " ".join(spec.command.split()[1:]),
            'echo "done $BUSDATE"']
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------- Airflow: DAG file
_OP = {JobKind.SENSOR: "FileSensor", JobKind.NOTIFY: "EmailOperator"}


def _task_block(spec: JobSpec) -> list[str]:
    op = _OP.get(spec.kind) or ("SnowflakeOperator" if spec.host.startswith("snowflake")
                                 else "SparkKubernetesOperator" if spec.host.startswith("spark")
                                 else "PythonOperator")
    lines = [f"{spec.name} = {op}(", f'    task_id="{spec.name}",']
    sql: list[str] = []
    for parts in _effects(spec):
        verb = parts[0]
        if verb == "read" and parts[1] == "table":
            sql.append(f"SELECT * FROM {parts[2]} WHERE load_date = '{{{{ ds }}}}'")
        elif verb == "write" and parts[1] == "table":
            sql.append(f"INSERT OVERWRITE INTO {parts[2]} SELECT * FROM {parts[2]}_stage")
        elif verb == "mail":
            lines.append(f'    on_success_callback=lambda ctx: send_email(to=["{parts[1]}"], '
                         f'subject="{parts[2] if len(parts) > 2 else spec.name}"),')
        elif verb == "api":
            lines.append(f'    python_callable=lambda: requests.{parts[1].lower()}("{parts[2]}", timeout=60),')
        elif verb == "event":
            lines.append("    python_callable=lambda: EventGridPublisherClient(EG_ENDPOINT, credential).send(")
            lines.append(f'        [EventGridEvent(subject="{parts[1]}", event_type="refresh", '
                         'data={"ds": "{{ ds }}"}, data_version="1.0")]),')
    if sql:
        lines.append('    sql="""' + ";\n         ".join(sql) + '""",')
    if spec.kind == JobKind.SENSOR:
        lines += ['    mode="poke",', "    poke_interval=60,", "    timeout=60 * 60 * 12,"]
    lines.append(")")
    return lines


def _dag_file(dag: str, specs: list[JobSpec]) -> str:
    out = ['"""' + f"{dag}: owned by {specs[0].owner}" + '"""', "from airflow import DAG",
           "from airflow.sensors.filesystem import FileSensor",
           "from airflow.providers.snowflake.operators.snowflake import SnowflakeOperator",
           "from azure.eventgrid import EventGridEvent, EventGridPublisherClient", "import requests", "",
           f'with DAG("{dag}", catchup=False, tags=["{specs[0].app}"]) as dag:']
    for s in specs:
        out += ["    " + line for line in _task_block(s)] + [""]
    edges = [f"    {p} >> {s.name}" for s in specs for p in s.after]
    return "\n".join(out + edges) + "\n"


# ---------------------------------------------------------------------- ADF: pipeline JSON + notebooks
def _adf_pipeline(name: str, specs: list[JobSpec]) -> tuple[str, dict[str, str]]:
    notebooks: dict[str, str] = {}
    acts = []
    for s in specs:
        act: dict = {"name": s.name, "type": {JobKind.TRANSFER: "Copy", JobKind.TRANSFORM: "DatabricksNotebook"}
                     .get(s.kind, "WebActivity" if any(e.startswith("api") for e in s.effects) else "Script")}
        tp: dict = {}
        for parts in _effects(s):
            if parts[0] == "sftp":
                host, path = parts[2].split(":", 1)
                tp["sink"] = {"type": "SftpWriteSettings", "linkedService": {"type": "Sftp", "host": host},
                              "folderPath": path}
            elif parts[0] == "api":
                tp.update({"method": parts[1], "url": parts[2]})
            elif parts[0] == "read" and parts[1] == "table" and s.kind == JobKind.TRANSFER:
                tp["source"] = {"type": "SqlServerSource", "sqlReaderQuery": f"SELECT * FROM {parts[2]}"}
            elif parts[0] == "write" and parts[1] == "table" and s.kind not in (JobKind.TRANSFORM,):
                tp.setdefault("scripts", []).append(
                    {"type": "NonQuery", "text": f"MERGE INTO {parts[2]} t USING {parts[2]}_stage s ON t.id = s.id"})
        if act["type"] == "DatabricksNotebook":
            path = f"/Repos/{s.app}/{s.name}.py"
            tp["notebookPath"] = path
            body = [f"# Databricks notebook source: {s.name}", "from pyspark.sql import functions as F"]
            for parts in _effects(s):
                if parts[0] == "read" and parts[1] == "table":
                    body.append(f'df_in = spark.table("{parts[2]}")')
                elif parts[0] == "write" and parts[1] == "table":
                    body.append(f'df_out.write.mode("overwrite").saveAsTable("{parts[2]}")')
            notebooks[path] = "\n".join(body) + "\n"
        act["typeProperties"] = tp
        acts.append(act)
    doc = {"name": name, "type": "Microsoft.DataFactory/factories/pipelines",
           "properties": {"activities": acts}}
    return json.dumps(doc, indent=2), notebooks


# ---------------------------------------------------------------------- repository
class SimulatedSourceRepository:
    """Read-only access to a scheduler's job source code (a git or Endevor export)."""

    def __init__(self, scheduler: SchedulerSpec, specs: list[JobSpec]) -> None:
        self.scheduler = scheduler
        self.files: dict[str, tuple[str, str]] = {}   # path -> (language, text)
        v = scheduler.vendor
        if v == Vendor.CONTROL_M:
            for s in specs:
                member = s.command.split()[0].lstrip("/")
                self.files[f"PRD.JCLLIB({member})"] = ("jcl", _jcl(s))
        elif v == Vendor.AUTOSYS:
            for s in specs:
                self.files[s.command.split()[0]] = ("sh", _shell(s))
        elif v == Vendor.AIRFLOW:
            dags: dict[str, list[JobSpec]] = defaultdict(list)
            for s in specs:
                dags[s.container].append(s)
            for dag, ss in dags.items():
                self.files[f"/opt/airflow/dags/{dag}.py"] = ("python", _dag_file(dag, ss))
        elif v == Vendor.ADF:
            pipes: dict[str, list[JobSpec]] = defaultdict(list)
            for s in specs:
                pipes[s.container].append(s)
            for name, ss in pipes.items():
                doc, notebooks = _adf_pipeline(name, ss)
                self.files[f"pipeline/{name}.json"] = ("json", doc)
                for path, text in notebooks.items():
                    self.files[path] = ("python", text)

    def describe(self) -> dict[str, str]:
        return {"scheduler_id": self.scheduler.id, "location": self.scheduler.source_repo, "mode": "simulated"}

    def list(self) -> list[str]:
        return sorted(self.files)

    def get(self, path: str) -> tuple[str, str] | None:
        return self.files.get(path)
