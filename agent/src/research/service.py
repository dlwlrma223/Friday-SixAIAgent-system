"""Research entry point for other agents: guard -> log -> search.

Every call is logged. Queries that trip the PII guard are parked as a
pending approval and only sent after the user approves.
"""

from dataclasses import dataclass
from typing import Literal

from src.research.store import ResearchStore
from src.tools import pii_guard
from src.tools.research import ResearchError, ResearchResponse, ResearchTool

ANSWER_PREVIEW_CHARS = 200


@dataclass(frozen=True)
class ResearchOutcome:
    status: Literal["sent", "pending_approval", "failed"]
    log_id: int
    response: ResearchResponse | None = None
    approval_id: int | None = None
    error: str | None = None


class ResearchService:
    def __init__(self, tool: ResearchTool, store: ResearchStore) -> None:
        self._tool = tool
        self._store = store

    def request(self, agent_name: str, query: str, purpose: str | None = None) -> ResearchOutcome:
        query = query.strip()
        flags = pii_guard.check(query, self._store.load_personal_terms())

        if flags:
            log_id = self._store.create_log(agent_name, query, purpose, flags, "pending_approval")
            approval_id = self._store.create_approval(
                agent_name,
                title=f"{agent_name} 想用 Research 查一段可能含個資的內容",
                detail=f"命中規則：{', '.join(flags)}\n查詢內容：{query}",
            )
            self._store.attach_approval(log_id, approval_id)
            return ResearchOutcome("pending_approval", log_id, approval_id=approval_id)

        # Log before sending so a crash mid-call still leaves a record.
        log_id = self._store.create_log(agent_name, query, purpose, [], "sent")
        return self._send(log_id, query, final_status="sent")

    def resume_approved(self, log_id: int) -> ResearchOutcome:
        """Send a previously parked query. Checks the DB, never trusts the caller."""
        log = self._store.get_log(log_id)
        if log is None:
            raise ValueError(f"research log {log_id} not found")
        if log["status"] != "pending_approval" or log["approval_id"] is None:
            raise ValueError(f"research log {log_id} is not awaiting approval")
        if self._store.approval_status(log["approval_id"]) != "approved":
            raise PermissionError(f"approval {log['approval_id']} is not approved")
        return self._send(log_id, log["query"], final_status="approved_sent")

    def _send(self, log_id: int, query: str, *, final_status: str) -> ResearchOutcome:
        try:
            response = self._tool.run(query)
        except (ResearchError, ValueError) as exc:
            self._store.mark_failed(log_id, str(exc))
            return ResearchOutcome("failed", log_id, error=str(exc))

        preview = response.answer[:ANSWER_PREVIEW_CHARS] if response.answer else None
        self._store.mark_sent(log_id, final_status, len(response.results), preview)
        return ResearchOutcome("sent", log_id, response=response)
