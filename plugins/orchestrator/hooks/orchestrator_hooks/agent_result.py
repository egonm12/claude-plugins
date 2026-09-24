"""The agent_result record: what a worker did, read when it stops.

Claude Code also runs internal agents, such as prompt suggestions. Their
records are written too, with their agent_type, so a reader can filter them.
"""

from __future__ import annotations

from typing import Any, Dict

from . import payload as hook_payload
from . import records, state, transcript
from .config import Config


def log_agent_result(payload: Dict[str, Any], config: Config) -> None:
    """Append one agent_result record for the worker in a SubagentStop payload."""
    _, current = state.load_for(config.state_dir, payload)
    path = hook_payload.value(payload, "agent_transcript_path")
    run = transcript.agent_run(path)
    # A worker that hands back through SubagentHandback leaves only closing text in last_assistant_message.
    report = run.report if run.report is not None else hook_payload.value(payload, "last_assistant_message")
    records.append(config.log_file, records.AgentResultRecord(
        session_id=hook_payload.session_id(payload), turn=current.turn if current else 0,
        agent_id=hook_payload.field_text(payload, "agent_id"), agent_type=hook_payload.field_text(payload, "agent_type"),
        tool_use_id=transcript.agent_tool_use_id(path), model=run.model, duration_s=run.duration_s,
        context_tokens_end=run.context_tokens_end,
        report_chars=len(report) if isinstance(report, str) else None), config.log_off)
