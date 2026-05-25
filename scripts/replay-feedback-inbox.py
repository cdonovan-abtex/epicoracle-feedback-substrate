#!/usr/bin/env python3
"""Drain a JSONL fallback inbox into GitHub issues — idempotent + dry-run.

Run periodically (cron, manual) on each satellite. Reads
``backend/storage/feedback_inbox.jsonl`` (or whatever path passed in)
and for each record:

1. Check idempotency: does an issue carrying this ``submission_id``
   already exist on the target repo? If yes, skip + mark for archive.
2. Otherwise, reconstruct the ``FeedbackPayload`` and call
   ``dispatch_feedback``.
3. On success, write the line to ``inbox-archive/YYYY-MM-DD.jsonl``
   (rolling per-day archive) and remove it from the live inbox.

Defaults to dry-run per ``feedback_test_mode_isolation``. Pass
``--commit`` to actually replay. Records that fail to replay (still no
network, for instance) are LEFT in the inbox and logged; the next cron
tick will retry.

Usage::

  python scripts/replay-feedback-inbox.py \\
      --inbox backend/storage/feedback_inbox.jsonl \\
      --repo cdonovan-abtex/epicoracle-marketplace \\
      --commit
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from epicoracle_feedback import (
    FeedbackKind,
    FeedbackPayload,
    check_idempotency,
    dispatch_feedback,
    resolve_gh_token,
)

logger = logging.getLogger("replay")


def _parse_record(line: str) -> tuple[FeedbackPayload, dict] | None:
    """Parse one JSONL record into (payload, raw_record).

    Returns None on parse error — the caller logs + skips.
    """
    try:
        raw = json.loads(line)
    except json.JSONDecodeError as exc:
        logger.warning("skip: bad json: %s", exc)
        return None
    payload_dict = raw.get("payload")
    if not isinstance(payload_dict, dict):
        logger.warning("skip: missing payload block")
        return None
    try:
        payload = FeedbackPayload(
            submission_id=UUID(payload_dict["submission_id"]),
            correlation_id=UUID(payload_dict.get("correlation_id", payload_dict["submission_id"])),
            subject=payload_dict["subject"],
            body=payload_dict["body"],
            kind=FeedbackKind(payload_dict["kind"]),
            route_path=payload_dict["route_path"],
            satellite=payload_dict["satellite"],
            satellite_version=payload_dict["satellite_version"],
            user_agent=payload_dict.get("user_agent", ""),
            submitted_by=payload_dict["submitted_by"],
            browser_timestamp=payload_dict["browser_timestamp"],
        )
    except (KeyError, ValueError) as exc:
        logger.warning("skip: cannot reconstruct payload: %s", exc)
        return None
    return payload, raw


def _archive_record(record: dict, archive_dir: Path) -> None:
    archive_dir.mkdir(parents=True, exist_ok=True)
    day = datetime.now(tz=UTC).strftime("%Y-%m-%d")
    archive = archive_dir / f"{day}.jsonl"
    with archive.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def replay(
    *,
    inbox_path: Path,
    repo: str,
    gh_token: str | None,
    commit: bool,
) -> tuple[int, int, int]:
    """Replay one pass over the inbox.

    Returns ``(replayed, deduplicated, failed)``.
    """
    if not inbox_path.exists():
        logger.info("inbox not found: %s — nothing to do", inbox_path)
        return 0, 0, 0

    lines = inbox_path.read_text(encoding="utf-8").splitlines()
    remaining: list[str] = []
    archive_dir = inbox_path.parent / "inbox-archive"
    replayed = deduplicated = failed = 0

    for line in lines:
        if not line.strip():
            continue
        parsed = _parse_record(line)
        if parsed is None:
            failed += 1
            remaining.append(line)
            continue

        payload, raw = parsed

        # Idempotency: GitHub already has this submission?
        existing = check_idempotency(repo, payload.submission_id, gh_token=gh_token)
        if existing is not None:
            logger.info(
                "dedup hit: submission_id=%s already at issue #%d — archiving record",
                payload.submission_id,
                existing,
            )
            deduplicated += 1
            if commit:
                _archive_record(raw, archive_dir)
            continue

        if not commit:
            logger.info("[DRY-RUN] would replay submission_id=%s", payload.submission_id)
            remaining.append(line)
            continue

        result = dispatch_feedback(
            payload,
            repo=repo,
            gh_token=gh_token,
            inbox_path=inbox_path.with_suffix(".replay.failed.jsonl"),
        )
        if result.queued_offline:
            logger.warning(
                "replay still offline: submission_id=%s err=%s",
                payload.submission_id,
                result.error,
            )
            failed += 1
            remaining.append(line)
        else:
            replayed += 1
            _archive_record(raw, archive_dir)

    if commit:
        # Truncate + rewrite with the surviving lines.
        with inbox_path.open("w", encoding="utf-8") as fh:
            for line in remaining:
                fh.write(line + "\n")

    return replayed, deduplicated, failed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay a JSONL feedback inbox.")
    parser.add_argument("--inbox", required=True, type=Path)
    parser.add_argument("--repo", required=True)
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Actually replay. Default is dry-run (per feedback_test_mode_isolation).",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not args.commit:
        logger.info("DRY-RUN — pass --commit to actually replay")

    replayed, deduplicated, failed = replay(
        inbox_path=args.inbox,
        repo=args.repo,
        gh_token=resolve_gh_token(),
        commit=args.commit,
    )
    logger.info(
        "replay done: replayed=%d deduplicated=%d failed=%d",
        replayed,
        deduplicated,
        failed,
    )
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
