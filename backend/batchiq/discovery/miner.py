"""Source miner: reads job code and extracts what the job really does.

Scheduler definitions say when a job runs. Its code says what it touches. The
miner applies a catalogue of small, auditable regex rules (one per idiom: a JCL
PATH DD, a shell IN_FILE, SQL FROM/INSERT, Spark saveAsTable, sftp put/get,
mailx, curl, MQ, Event Grid, hard-coded passwords) and records each hit with
the file, line and snippet it came from. Nothing here is a guess dressed up as a
fact: every mined fact can be opened at the line that produced it.

Adding an idiom means adding one `MiningRule`.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from urllib.parse import urlparse

from batchiq.core.artifacts import data_artifact, file_artifact
from batchiq.discovery.sources import SourceRef, SourceRepository
from batchiq.domain.models import Job

INTERNAL_DOMAIN = ".bank.example"   # hosts under the client's own domain are internal


@dataclass
class MinedFact:
    job_id: str
    relation: str          # reads | writes | transfers_to | fetches_from | notifies | calls | publishes | exposes
    object_type: str       # file | dataset | queue | endpoint | communication | event | secret
    key: str               # canonical key, shared with definitions where possible (file:..., data:...)
    label: str
    path: str
    line: int
    rule: str
    snippet: str
    detail: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class MiningRule:
    id: str
    description: str
    pattern: re.Pattern[str]
    build: Callable[[re.Match[str]], tuple[str, str, str, str, dict[str, str]] | None]
    # build -> (relation, object_type, key, label, detail) or None to skip the hit


def _file(rel: str) -> Callable[[re.Match[str]], tuple]:
    def b(m: re.Match[str]) -> tuple:
        raw = m.group(1).strip("'\"")
        a = file_artifact(raw)
        return rel, "file", a.canonical, a.canonical.split(":", 1)[1], {"raw": raw}
    return b


_SKIP_TABLE = re.compile(r"(_stage$|^stage_|^session\.|^sysibm\.|^dual$)", re.I)


def _table(rel: str) -> Callable[[re.Match[str]], tuple | None]:
    def b(m: re.Match[str]) -> tuple | None:
        name = m.group(1).lower()
        if _SKIP_TABLE.search(name) or _SKIP_TABLE.search(name.split(".")[-1]):
            return None
        a = data_artifact(name)
        return rel, "dataset", a.canonical, name, {}
    return b


def _endpoint(host: str) -> tuple[str, str, dict[str, str]]:
    host = host.lower()
    return f"endpoint:{host}", host, {"host": host, "internal": str(host.endswith(INTERNAL_DOMAIN)).lower()}


def _api(m: re.Match[str]) -> tuple:
    method, url = m.group("method").upper(), m.group("url")
    key, label, d = _endpoint(urlparse(url).hostname or url)
    return "calls", "endpoint", key, label, {**d, "method": method, "url": url}


def _mail(m: re.Match[str]) -> tuple:
    addr = m.group("to").lower()
    d = {"subject": m.groupdict().get("subject") or ""}
    return "notifies", "communication", f"mail:{addr}", addr, d


def _mq(m: re.Match[str]) -> tuple:
    q = m.group("queue").upper()
    return ("publishes" if m.group("op").lower() == "put" else "reads"), "queue", f"queue:{q.lower()}", q, {}


RULES: tuple[MiningRule, ...] = (
    MiningRule("jcl-path-in", "z/OS USS file opened read-only by a DD", re.compile(
        r"PATH='([^']+)',\s*PATHOPTS=\(ORDONLY"), _file("reads")),
    MiningRule("jcl-path-out", "z/OS USS file opened for write by a DD", re.compile(
        r"PATH='([^']+)',\s*PATHOPTS=\(OWRONLY"), _file("writes")),
    MiningRule("sh-in-file", "shell input file variable", re.compile(
        r"^\s*(?:IN|INPUT|SRC)_FILE\w*=\"?([^\s\"]+)", re.M), _file("reads")),
    MiningRule("sh-out-file", "shell output file variable", re.compile(
        r"^\s*(?:OUT|OUTPUT|DEST)_FILE\w*=\"?([^\s\"]+)", re.M), _file("writes")),
    MiningRule("sql-read", "SQL SELECT ... FROM schema.table", re.compile(
        r"\bFROM\s+([A-Za-z_]\w*\.[A-Za-z_]\w*)(?![\w.])(?!\s+import\b)", re.I), _table("reads")),
    MiningRule("sql-write", "SQL INSERT / MERGE / COPY INTO schema.table", re.compile(
        r"\b(?:INSERT\s+(?:OVERWRITE\s+)?INTO|MERGE\s+INTO|COPY\s+INTO)\s+([A-Za-z_]\w*\.[A-Za-z_]\w*)", re.I),
        _table("writes")),
    MiningRule("spark-read", "Spark spark.table(...)", re.compile(r"spark\.table\([\"']([\w.]+)[\"']\)"),
               _table("reads")),
    MiningRule("spark-write", "Spark saveAsTable(...)", re.compile(r"saveAsTable\([\"']([\w.]+)[\"']\)"),
               _table("writes")),
    MiningRule("mailx", "mailx to a recipient", re.compile(
        r"mailx\s+-s\s+\"(?P<subject>[^\"]*)\"\s+(?P<to>[\w.\-]+@[\w.\-]+)"), _mail),
    MiningRule("smtp-rcpt", "SMTP RCPT TO (JCL IEBGENER to SYSOUT SMTP)", re.compile(
        r"RCPT TO:<(?P<to>[^>]+)>"), _mail),
    MiningRule("airflow-email", "Airflow send_email(to=[...])", re.compile(
        r"send_email\(to=\[\"(?P<to>[^\"]+)\"\](?:,\s*subject=\"(?P<subject>[^\"]*)\")?"), _mail),
    MiningRule("curl", "curl to an HTTP API", re.compile(
        r"curl\b[^\n]*?-X\s+(?P<method>[A-Z]+)[^\n]*?\"(?P<url>https?://[^\"]+)\""), _api),
    MiningRule("requests", "Python requests to an HTTP API", re.compile(
        r"requests\.(?P<method>get|post|put|patch|delete)\(\"(?P<url>https?://[^\"]+)\""), _api),
    MiningRule("adf-web", "ADF Web activity", re.compile(
        r"\"method\":\s*\"(?P<method>[A-Z]+)\",\s*\"url\":\s*\"(?P<url>https?://[^\"]+)\""), _api),
    MiningRule("mq-jcl", "IBM MQ put/get from JCL", re.compile(
        r"PGM=MQ(?P<op>PUT|GET),PARM='QMGR=\w+ QUEUE=(?P<queue>[\w.]+)'"), _mq),
    MiningRule("mq-sh", "IBM MQ sample put/get from shell", re.compile(
        r"amqs(?P<op>put|get)\s+(?P<queue>[\w.]+)"), _mq),
    MiningRule("eventgrid", "Azure Event Grid event published", re.compile(
        r"EventGridEvent\(subject=\"([^\"]+)\""),
        lambda m: ("publishes", "event", f"event:{m.group(1).lower()}", m.group(1), {})),
    MiningRule("adf-sftp-sink", "ADF copy to an SFTP sink", re.compile(
        r"\"SftpWriteSettings\"[\s\S]{0,200}?\"host\":\s*\"(?P<host>[\w.\-]+)\"[\s\S]{0,120}?"
        r"\"folderPath\":\s*\"(?P<path>[^\"]+)\""),
        lambda m: ("transfers_to", "endpoint", *_endpoint(m.group("host"))[:2],
                   {**_endpoint(m.group("host"))[2], "path": m.group("path"), "protocol": "sftp"})),
    MiningRule("plaintext-secret", "credential assigned as a string literal", re.compile(
        r"(?i)\b\w*(?:password|passwd|pwd)\w*\s*=\s*\"(?!\$)[^\"\s]{4,}\""),
        lambda m: ("exposes", "secret", "secret:plaintext-credential", "plain-text credential",
                   {"variable": m.group(0).split("=")[0].strip()})),
)

_SFTP_SESSION = re.compile(r"sftp\b[^\n]*?@(?P<host>[\w.\-]+)")
_SFTP_CMD = re.compile(r"^\s*(?P<op>put|get)\s+(?P<a>\S+)\s+(?P<b>\S+)", re.M)
_FOLLOW = re.compile(r"\"notebookPath\":\s*\"([^\"]+)\"")


@dataclass
class _Text:
    path: str
    language: str
    text: str
    start_line: int


class SourceMiner:
    def __init__(self, rules: Iterable[MiningRule] = RULES) -> None:
        self.rules = tuple(rules)
        self.stats: Counter[str] = Counter()

    # ------------------------------------------------------------------ public
    def mine(self, job: Job, refs: list[SourceRef], repo: SourceRepository) -> list[MinedFact]:
        facts: list[MinedFact] = []
        seen_paths: set[str] = set()
        queue = list(refs)
        while queue:
            ref = queue.pop(0)
            got = repo.get(ref.path)
            if got is None or (ref.path, ref.section) in seen_paths:
                continue
            seen_paths.add((ref.path, ref.section))  # type: ignore[arg-type]
            lang, text = got
            chunk = self._section(ref.path, lang, text, ref.section)
            if chunk is None:
                continue
            self.stats["files"] += 1
            facts += self._apply(job, chunk)
            queue += [SourceRef(p) for p in _FOLLOW.findall(chunk.text)]   # notebooks behind ADF activities
        # one fact per (relation, key): keep the first location, count the rest
        uniq: dict[tuple[str, str], MinedFact] = {}
        for f in facts:
            uniq.setdefault((f.relation, f.key), f)
        for f in uniq.values():
            self.stats[f"{f.relation}:{f.object_type}"] += 1
        return list(uniq.values())

    # ------------------------------------------------------------------ internals
    @staticmethod
    def _section(path: str, lang: str, text: str, section: str | None) -> _Text | None:
        if not section:
            return _Text(path, lang, text, 1)
        lines = text.splitlines()
        if lang == "python":                  # an Airflow task block: `<task> = Operator(` ... `)`
            head = re.compile(rf"^(\s*){re.escape(section)}\s*=\s*\w+\(")
            for i, line in enumerate(lines):
                m = head.match(line)
                if m:
                    indent = m.group(1)
                    for j in range(i + 1, len(lines)):
                        if lines[j] == f"{indent})":
                            return _Text(path, lang, "\n".join(lines[i:j + 1]), i + 1)
            return None
        if lang == "json":                    # an ADF activity inside a pipeline document
            try:
                doc = json.loads(text)
            except json.JSONDecodeError:
                return None
            for act in doc.get("properties", {}).get("activities", []):
                if act.get("name") == section:
                    start = next((i + 1 for i, line in enumerate(lines) if f'"name": "{section}"' in line), 1)
                    return _Text(path, lang, json.dumps(act, indent=2), start)
            return None
        return _Text(path, lang, text, 1)

    def _apply(self, job: Job, t: _Text) -> list[MinedFact]:
        out: list[MinedFact] = []

        def line_of(pos: int) -> int:
            return t.start_line + t.text.count("\n", 0, pos)

        def snippet(pos: int) -> str:
            ln = line_of(pos) - t.start_line
            return t.text.splitlines()[ln].strip()[:160] if t.text else ""

        for rule in self.rules:
            for m in rule.pattern.finditer(t.text):
                built = rule.build(m)
                if built is None:
                    continue
                rel, otype, key, label, detail = built
                out.append(MinedFact(job.id, rel, otype, key, label, t.path, line_of(m.start()), rule.id,
                                     snippet(m.start()), detail))
        # sftp sessions span lines: the host is on the session line, the file on the put/get line
        for s in _SFTP_SESSION.finditer(t.text):
            window = t.text[s.end(): s.end() + 400]
            c = _SFTP_CMD.search(window)
            if not c:
                continue
            op = c.group("op")
            remote = c.group("b") if op == "put" else c.group("a")
            key, label, d = _endpoint(s.group("host"))
            pos = s.end() + c.start()
            out.append(MinedFact(job.id, "transfers_to" if op == "put" else "fetches_from", "endpoint", key, label,
                                 t.path, line_of(pos), f"sftp-{op}", snippet(pos),
                                 {**d, "path": remote, "protocol": "sftp"}))
        return out
