"""Pure shadow routing. No decision from this module authorizes an external action."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from functools import partial
import hashlib
import json

CLUSTER = 'advertising.cluster.set_excluded'
READ = 'xway.product.read'
OWNER = 'wb-executor'
PENDING = {'execution_pending', 'pending_verification', 'unknown'}


@dataclass(frozen=True)
class Capability:
    """Qualification belongs to an exact operation AND browser transport."""
    command: str
    transport: str
    level: str
    evidence_ref: str


CURRENT = (
    Capability(READ, 'codex_iab', 'live_readonly', 'docs/XWAY_READONLY_EXPERIMENT.md'),
    Capability(CLUSTER, 'offline_contract', 'replay_only', 'docs/CLUSTER_REPLAY_EXPERIMENT.md'),
)


def fingerprint(task: dict) -> str:
    """Handover cannot silently substitute a product, version or requested value."""
    value = {key: task[key] for key in ('proposal_id', 'version', 'command', 'identity', 'payload')}
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False).encode('utf-8')).hexdigest()


def _decision(task: dict, route: str, reason: str, *, candidate: str | None = None, owner: str = OWNER) -> dict:
    return dict(proposal_id=task['proposal_id'], version=task['version'],
                task_sha256=fingerprint(task), suggested_route=route, owner=owner,
                reason=reason, shadow_candidate=candidate, may_execute=False,
                requires_canonical_gate=True, mode='shadow_only')


def qualify(task: dict, transport: str, capabilities: tuple[Capability, ...]) -> tuple[bool, str]:
    """A replay or a different browser is insufficient evidence for real execution."""
    entries = [c for c in capabilities if c.command == task['command'] and c.transport == transport]
    if not entries:
        return False, 'no_qualified_skill_for_this_transport'
    level = 'live_readonly' if task['command'] == READ else 'live_write_verified'
    if not any(c.level == level and c.evidence_ref for c in entries):
        return False, 'skill_not_live_qualified'
    return True, 'qualified_exact_operation_and_transport'


def route(task: dict, state: dict, now: datetime, *, transport: str = 'hermes_yandex',
          capabilities: tuple[Capability, ...] = CURRENT, owner: str = OWNER) -> dict:
    """Recommend before reservation; outstanding attempts always stay in reconciliation."""
    fingerprint(task)
    decision = partial(_decision, owner=owner)
    command, status = task['command'], task['status']
    if command.startswith('prices.'):
        return decision(task, 'existing_server_route', 'outside_xway_scope')
    if command != READ and not command.startswith(('advertising.', 'xway.')):
        return decision(task, 'review', 'unknown_operation')
    if status == 'verified':
        return decision(task, 'none', 'already_verified_no_reexecution')
    if status == 'failed':
        return decision(task, 'review', 'failed_attempt_is_not_automatic_retry')
    if status in PENDING or task.get('submitted_at'):
        return decision(task, 'reconcile', 'attempt_already_reserved_or_outcome_unknown')
    if status != 'proposed':
        return decision(task, 'review', 'unsupported_task_status')
    candidate = 'kolos_offline_rehearsal' if command == CLUSTER else None
    if command != READ and state.get('ui_active_proposal'):
        return decision(task, 'wait_existing_attempt', 'shared_browser_attempt_open', candidate=candidate)
    if command != READ:
        policy = state.get('supervisor_policy', {})
        if (not policy.get('enabled') or not policy.get('starts_at') or not policy.get('expires_at')
                or not datetime.fromisoformat(policy['starts_at']) <= now < datetime.fromisoformat(policy['expires_at'])
                or command not in policy.get('allowed_commands', [])):
            return decision(task, 'review', 'canonical_authority_must_be_revalidated', candidate=candidate)
    ready, reason = qualify(task, transport, capabilities)
    return decision(task, 'kolos_candidate' if ready else 'hermes_executor', reason, candidate=candidate)


def handover(task: dict, selected: dict, progress: dict) -> dict:
    """Fallback is legal only before ui-begin, never after an uncertain Save."""
    decision = partial(_decision, owner=selected.get('owner', OWNER))
    if selected['task_sha256'] != fingerprint(task):
        raise ValueError('task_changed_during_handover')
    if task['status'] != 'proposed' or task.get('submitted_at'):
        return decision(task, 'reconcile', 'task_no_longer_unreserved')
    if selected['suggested_route'] != 'kolos_candidate':
        return decision(task, 'review', 'no_selected_kolos_preflight_to_hand_over')
    flags = ('may_interact_issued', 'write_dispatched', 'save_unknown', 'lock_held')
    if any(type(progress.get(k)) is not bool for k in flags) or 'attempt_id' not in progress:
        return decision(task, 'reconcile', 'incomplete_preflight_evidence')
    if progress.get('stage') != 'preflight' or any(progress.get(k) for k in
            ('attempt_id', 'may_interact_issued', 'write_dispatched', 'save_unknown', 'lock_held')):
        return decision(task, 'reconcile', 'handover_after_reservation_forbidden')
    if progress.get('reason') not in ('missing_skill', 'unsupported_view', 'preflight_failed'):
        return decision(task, 'review', 'unexpected_preflight_failure')
    return decision(task, 'hermes_executor', 'safe_fallback_before_ui_begin_same_task')
