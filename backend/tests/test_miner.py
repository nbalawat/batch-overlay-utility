"""Source mining over hand-written code in each dialect (independent of the simulator's renderer)."""
from __future__ import annotations

from batchiq.discovery.miner import SourceMiner
from batchiq.discovery.sources import EmptySourceRepository, SourceRef
from batchiq.domain.models import Job, Vendor


class DictRepo:
    def __init__(self, files: dict[str, tuple[str, str]]) -> None:
        self.files = files

    def describe(self) -> dict[str, str]:
        return {"location": "test", "mode": "dict"}

    def list(self) -> list[str]:
        return list(self.files)

    def get(self, path: str) -> tuple[str, str] | None:
        return self.files.get(path)


def _job(vendor: Vendor = Vendor.AUTOSYS) -> Job:
    return Job(id="s::J", scheduler_id="s", vendor=vendor, native_id="J", name="J", container="C")


def _rel(facts) -> set[tuple[str, str]]:
    return {(f.relation, f.key) for f in facts}


KSH = """#!/bin/ksh
IN_FILE=/xfer/pay/settlement_${BUSDATE}.dat
OUT_FILE=/out/ach/nacha_${BUSDATE}.ach
DB_PASSWORD="Sup3rS3cret"
sqlplus -s batch/$DB_PASS <<EOF
  INSERT INTO pay.ach_batches SELECT * FROM pay.settlement_stage;
  SELECT count(*) FROM pay.ach_limits;
EOF
sftp -b - achuser@ach.fedline.frb.example <<EOT
  put $OUT_FILE /inbound/nacha_${BUSDATE}.ach
EOT
mailx -s "ACH sent" pay-ops@bank.example < /dev/null
curl -s -X POST -H "Content-Type: application/json" "https://notify.bank.example/api/v1/events"
amqsput PAY.ACH.OUT QM1
"""


def test_shell_script_facts_and_locations():
    facts = SourceMiner().mine(_job(), [SourceRef("/apps/pay/ach.sh")], DictRepo({"/apps/pay/ach.sh": ("ksh", KSH)}))
    r = _rel(facts)
    assert ("reads", "file:settlement_{date}.dat") in r
    assert ("writes", "file:nacha_{date}.ach") in r
    assert ("writes", "data:pay.ach_batches") in r
    assert ("reads", "data:pay.ach_limits") in r
    assert not any(k.endswith("settlement_stage") for _, k in r), "staging tables are noise"
    assert ("transfers_to", "endpoint:ach.fedline.frb.example") in r
    assert ("notifies", "mail:pay-ops@bank.example") in r
    assert ("calls", "endpoint:notify.bank.example") in r
    assert ("publishes", "queue:pay.ach.out") in r
    secret = next(f for f in facts if f.object_type == "secret")
    assert secret.line == 4 and secret.path == "/apps/pay/ach.sh" and "DB_PASSWORD" in secret.snippet
    ext = next(f for f in facts if f.key == "endpoint:ach.fedline.frb.example")
    assert ext.detail["internal"] == "false"
    assert next(f for f in facts if f.key == "endpoint:notify.bank.example").detail["internal"] == "true"


JCL = """//GLEXTR   JOB (ACCT),'GL EXTRACT'
//STEP1    EXEC PGM=GLX100
//IN       DD PATH='/xfer/core/txn_posted_&ODATE..dat',PATHOPTS=(ORDONLY)
//OUT      DD PATH='/xfer/gl/gl_extract_&ODATE..dat',PATHOPTS=(OWRONLY,OCREAT)
//STEP2    EXEC PGM=MQPUT,PARM='QMGR=QMP1 QUEUE=GL.EXTRACT.DONE'
"""


def test_jcl_paths_and_mq():
    facts = SourceMiner().mine(_job(Vendor.CONTROL_M), [SourceRef("PRD.JCLLIB(GLEXTR)")],
                               DictRepo({"PRD.JCLLIB(GLEXTR)": ("jcl", JCL)}))
    assert _rel(facts) >= {("reads", "file:txn_posted_{date}.dat"), ("writes", "file:gl_extract_{date}.dat"),
                           ("publishes", "queue:gl.extract.done")}


DAG = '''from pyspark.sql import functions as F
from airflow import DAG

build = SnowflakeOperator(
    task_id="build",
    sql="INSERT INTO risk.features SELECT * FROM core.transactions",
)

notify = PythonOperator(
    task_id="notify",
    python_callable=lambda: send_email(to=["risk@bank.example"], subject="Scores ready"),
)
'''


def test_airflow_sections_keep_facts_per_task():
    repo = DictRepo({"/opt/airflow/dags/risk.py": ("python", DAG)})
    build = SourceMiner().mine(_job(Vendor.AIRFLOW), [SourceRef("/opt/airflow/dags/risk.py", "build")], repo)
    notify = SourceMiner().mine(_job(Vendor.AIRFLOW), [SourceRef("/opt/airflow/dags/risk.py", "notify")], repo)
    assert _rel(build) == {("writes", "data:risk.features"), ("reads", "data:core.transactions")}
    assert _rel(notify) == {("notifies", "mail:risk@bank.example")}
    assert build[0].line >= 4, "line numbers are relative to the file, not the section"


PIPELINE = """{"name": "pl_c360", "properties": {"activities": [
  {"name": "merge", "type": "DatabricksNotebook", "typeProperties": {"notebookPath": "/Repos/c360/merge"}},
  {"name": "push", "type": "Copy", "typeProperties": {"sink": {"type": "DelimitedTextSink",
     "storeSettings": {"type": "SftpWriteSettings"}}, "host": "sftp.partner.example", "folderPath": "/in/c360"}}
]}}"""
NOTEBOOK = 'df = spark.table("c360.customer_raw")\ndf.write.saveAsTable("c360.customer_profile")\n'


def test_adf_follows_notebooks_and_finds_sftp_sink():
    repo = DictRepo({"pipeline/pl_c360.json": ("json", PIPELINE), "/Repos/c360/merge": ("python", NOTEBOOK)})
    facts = SourceMiner().mine(_job(Vendor.ADF), [SourceRef("pipeline/pl_c360.json")], repo)
    assert _rel(facts) >= {("reads", "data:c360.customer_raw"), ("writes", "data:c360.customer_profile"),
                           ("transfers_to", "endpoint:sftp.partner.example")}
    sink = next(f for f in facts if f.relation == "transfers_to")
    assert sink.detail["path"] == "/in/c360"


def test_no_code_connected_means_no_facts():
    assert SourceMiner().mine(_job(), [SourceRef("/x.sh")], EmptySourceRepository()) == []


def test_facts_are_deduplicated_per_relation_and_key():
    text = "IN_FILE=/a/b_${BUSDATE}.dat\nIN_FILE2=/a/b_${BUSDATE}.dat\n"
    facts = SourceMiner().mine(_job(), [SourceRef("/x.sh")], DictRepo({"/x.sh": ("ksh", text)}))
    assert len(facts) == 1 and facts[0].line == 1
