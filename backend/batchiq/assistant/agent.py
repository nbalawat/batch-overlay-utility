"""Operations assistant: natural-language Q&A over the unified estate."""
from __future__ import annotations

import logging

from batchiq.assistant.offline import OfflineProvider
from batchiq.assistant.tools import TOOLS, ToolBox
from batchiq.llm.base import AssistantResult, LLMProvider
from batchiq.llm.factory import build_provider
from batchiq.service import EstateService

log = logging.getLogger(__name__)

SYSTEM = """You are the operations assistant inside a batch intelligence overlay. The overlay sits on top of \
a bank's existing schedulers (Control-M, AutoSys, Airflow and Azure Data Factory), normalises their jobs into \
one model, correlates dependencies across them and maps jobs to business processes and SLAs.

Answer questions from batch operators, service owners and executives about tonight's batch.
- Use the tools to get facts. Never invent job names, times or numbers.
- The knowledge graph links jobs to files, tables, queues, hosts, e-mails, external endpoints, teams, \
business processes and incidents, and says where each fact came from (definition, code, runtime, approved \
link, proposed link). Say so when an answer depends on a link that is still in review.
- For layered questions chain the tools: describe_entity, trace_lineage and find_path for dependencies; \
get_ecosystem for questions about one scheduler; host_outage_impact for what-if outages; \
find_communications for e-mails, transfers and API calls; list_findings, list_link_candidates and \
list_changes for analysis, review and change history.
- Lead with the answer. Then give the evidence, naming which scheduler each job lives in, because \
cross-scheduler links are what operators can't see in any single console.
- Tie technical issues to business impact: process, SLA time, breach probability, services.
- When recommending an action, say which scheduler it runs in and that it needs operator approval.
- Times are in the estate's local time (24h). Keep answers under 200 words unless asked for more."""


class Assistant:
    def __init__(self, svc: EstateService, provider: LLMProvider | None = None) -> None:
        self.svc = svc
        self.toolbox = ToolBox(svc)
        self.offline = OfflineProvider(self.toolbox)
        self.provider = provider or build_provider(self.offline)

    def ask(self, question: str, history: list[dict[str, str]] | None = None) -> AssistantResult:
        history = history or []
        try:
            return self.provider.answer(SYSTEM, history, question, TOOLS, self.toolbox.execute)
        except Exception as exc:  # LLM outage must never break the console
            log.warning("LLM provider %s failed, falling back to offline: %s", self.provider.name, exc)
            res = self.offline.answer(SYSTEM, history, question, TOOLS, self.toolbox.execute)
            res.note = f"The {self.provider.name} provider was unavailable ({type(exc).__name__}). Offline answer shown."
            return res
