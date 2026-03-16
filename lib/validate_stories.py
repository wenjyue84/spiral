#!/usr/bin/env python3
"""
lib/validate_stories.py — Phase S story validation helper

Reads candidate stories from _research_output.json and _test_stories_output.json,
validates each against prd.json goals[], optionally checks a constitution file,
and writes:
  _validated_stories.json  — accepted stories (input to Phase M --research)
  _story_rejected.json     — rejected stories with rejection reasons (log only)

When --batch-api is passed (and ANTHROPIC_API_KEY is set), story validation is
delegated to the Anthropic Message Batches API for 50% cost savings.  Single-story
runs fall back to the synchronous /v1/messages path transparently.
The batch_id is recorded in each story's ``_batch_id`` field and in the
``--batch-out`` JSON file (default: <scratch_dir>/_phase_s_batch.json).

Exit code: 0 always (validation failures are non-fatal; use --min-overlap 0 to accept all).
"""
import argparse
import json
import os
import re
import sys

from pydantic import ValidationError

sys.path.insert(0, os.path.dirname(__file__))
from spiral_io import atomic_write_json, configure_utf8_stdout
configure_utf8_stdout()

# Common English stopwords to exclude from keyword comparison
_STOPWORDS = {
    "the", "and", "for", "are", "was", "this", "with", "from", "that",
    "not", "all", "can", "but", "has", "new", "add", "run", "use",
    "set", "get", "put", "may", "via", "its", "also", "any", "each",
    "when", "have", "been", "will", "into", "only", "more", "such",
    "than", "then", "they", "their", "them", "what", "where", "which",
    "who", "how", "per", "non", "now", "one", "two", "should", "would",
    "could", "must", "does", "did", "out", "too", "end", "log", "key",
}


def _normalize(text: str) -> set[str]:
    """Extract lowercase alpha-numeric tokens >= 3 chars, excluding stopwords."""
    return {
        w for w in re.findall(r"[a-z0-9]+", text.lower())
        if len(w) >= 3 and w not in _STOPWORDS
    }


def _goal_keywords(goals: list[str]) -> set[str]:
    """Extract meaningful keywords from the goals list."""
    words: set[str] = set()
    for g in goals:
        words |= _normalize(g)
    return words


def _story_keywords(story: dict) -> set[str]:
    """Extract keywords from a story's title and description."""
    text = story.get("title", "") + " " + story.get("description", "")
    return _normalize(text)


def _load_candidates(path: str) -> list[dict]:
    """Load story candidates from a JSON file with a .stories array."""
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        # Validate with Pydantic model (US-203)
        from llm_models import ResearchOutput, log_validation_error

        try:
            validated = ResearchOutput.model_validate(data)
            return [s.model_dump() for s in validated.stories]
        except ValidationError as exc:
            log_validation_error(exc, data, f"validate_stories:_load_candidates({path})")
            print(f"  [S] WARNING: validation failed for {path}: {exc}")
            return data.get("stories", [])
    except (json.JSONDecodeError, OSError):
        return []


def _load_constitution_forbidden(path: str) -> list[str]:
    """Extract forbidden phrases from a constitution file.

    Lines matching ``NOT:``, ``NEVER:``, ``AVOID:``, or ``FORBIDDEN:`` prefixes
    are treated as forbidden phrases (case-insensitive substring match).
    """
    forbidden: list[str] = []
    if not path or not os.path.exists(path):
        return forbidden
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                for prefix in ("NOT:", "NEVER:", "AVOID:", "FORBIDDEN:"):
                    if line.upper().startswith(prefix):
                        phrase = line[len(prefix):].strip().lower()
                        if phrase:
                            forbidden.append(phrase)
                        break
    except OSError:
        pass
    return forbidden


def _validate_via_batch_api(
    all_candidates: list[dict],
    goals: list[str],
    forbidden_phrases: list[str],
    api_key: str,
    batch_out: str,
    base_url: str,
    batch_size: int = 0,
) -> tuple[list[dict], list[dict]]:
    """Validate story candidates using the Anthropic Message Batches API.

    Assigns a ``_custom_id`` to each candidate (its index) and submits a
    single batch request (or multiple chunks when *batch_size* > 0).
    Polls until all results are available, then applies the LLM decisions.
    The batch_id is written to *batch_out* and stamped onto each story as
    ``_batch_id``.

    Single-story runs use the synchronous /v1/messages fallback.

    Parameters
    ----------
    batch_size:
        Maximum number of stories per batch request (0 = no cap, send all
        in one batch). When > 0, candidates are split into chunks of this
        size and submitted as separate batch requests.
    """
    import batch_validate as _bv  # lazy import so the module is optional

    goal_text = "\n".join(goals) if goals else "(no goals specified)"

    # Stamp _custom_id for correlation
    for i, story in enumerate(all_candidates):
        story["_custom_id"] = f"story-{i}"

    accepted: list[dict] = []
    rejected: list[dict] = []
    # All batch IDs collected across chunks (for summary)
    all_batch_ids: list[str] = []

    if len(all_candidates) == 1:
        # --- Synchronous fallback for single story ---
        story = all_candidates[0]
        ok, reason = _bv.validate_story_sync(
            story, goal_text, forbidden_phrases, api_key, base_url
        )
        if ok:
            accepted.append(story)
        else:
            rejected.append({**story, "_rejection_reason": reason})
        print(f"  [S] Batch API sync: {story.get('title', '')[:70]!r} → {'ACCEPT' if ok else 'REJECT'}")
    else:
        # --- Batch path (with optional chunking) ---
        # Split into chunks when batch_size is set
        chunk_size = batch_size if batch_size > 0 else len(all_candidates)
        chunks: list[list[dict]] = [
            all_candidates[i: i + chunk_size]
            for i in range(0, len(all_candidates), chunk_size)
        ]
        print(
            f"  [S] Submitting {len(all_candidates)} stories to Message Batches API"
            f" in {len(chunks)} chunk(s) (batch_size={chunk_size})…"
        )

        for chunk in chunks:
            requests = _bv.build_batch_requests(chunk, goal_text, forbidden_phrases)
            batch_info = _bv.submit_batch(requests, api_key, base_url)
            batch_id = str(batch_info.get("id", ""))
            all_batch_ids.append(batch_id)
            print(f"  [S] Batch submitted: {batch_id} ({len(chunk)} stories)")

            raw_results = _bv.poll_batch(batch_id, api_key, base_url)
            decisions = _bv.parse_batch_results(raw_results)

            story_map = {str(s.get("_custom_id", "")): s for s in chunk}
            for custom_id, story in story_map.items():
                decision = decisions.get(custom_id, {"accepted": True, "reason": "missing"})
                story["_batch_id"] = batch_id
                ok = bool(decision.get("accepted", True))
                reason = str(decision.get("reason", ""))
                title = story.get("title", "")
                if ok:
                    accepted.append(story)
                else:
                    rejected.append({**story, "_rejection_reason": reason})
                    print(f"  [S] REJECTED (batch): {title[:70]!r} — {reason}")

    # Write batch summary using the last batch_id (or first if single chunk)
    summary_batch_id = all_batch_ids[-1] if all_batch_ids else ""
    if batch_out:
        _write_batch_summary(batch_out, summary_batch_id, accepted, rejected)

    return accepted, rejected


def _write_batch_summary(
    batch_out: str,
    batch_id: str,
    accepted: list[dict],
    rejected: list[dict],
) -> None:
    """Write a Phase S batch results summary to *batch_out*."""
    import datetime

    rows: list[dict[str, object]] = []
    for story in accepted:
        rows.append(
            {
                "batch_id": batch_id,
                "story_id": story.get("id", ""),
                "title": story.get("title", ""),
                "accepted": True,
            }
        )
    for story in rejected:
        rows.append(
            {
                "batch_id": batch_id,
                "story_id": story.get("id", ""),
                "title": story.get("title", ""),
                "accepted": False,
                "rejection_reason": story.get("_rejection_reason", ""),
            }
        )
    summary: dict[str, object] = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "batch_id": batch_id,
        "total": len(rows),
        "accepted": len(accepted),
        "rejected": len(rejected),
        "results": rows,
    }
    try:
        os.makedirs(os.path.dirname(os.path.abspath(batch_out)), exist_ok=True)
        with open(batch_out, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=2)
            fh.write("\n")
    except OSError as exc:
        print(f"  [S] WARNING: could not write batch summary to {batch_out}: {exc}")


def validate_stories(
    research_path: str,
    test_stories_path: str,
    prd_path: str,
    validated_out: str,
    rejected_out: str,
    constitution_path: str = "",
    min_overlap: int = 1,
    ai_suggest_path: str = "",
    test_story_candidates_path: str = "",
    use_batch_api: bool = False,
    batch_out: str = "",
    batch_base_url: str = "",
    batch_size: int = 0,
) -> tuple[list[dict], list[dict]]:
    """Core validation logic. Returns (accepted, rejected) lists."""

    # Load prd.json goals
    try:
        with open(prd_path, encoding="utf-8") as fh:
            prd = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[S] ERROR: Cannot read prd.json: {exc}", file=sys.stderr)
        sys.exit(1)

    goals: list[str] = prd.get("goals", [])
    gkw = _goal_keywords(goals) if goals else set()

    # Load optional constitution forbidden phrases
    forbidden_phrases = _load_constitution_forbidden(constitution_path)

    # Combine candidates from all sources (dedup by lower-cased title)
    research_stories = _load_candidates(research_path)
    test_stories = _load_candidates(test_stories_path)
    ai_suggest_stories = _load_candidates(ai_suggest_path) if ai_suggest_path else []
    test_story_candidates = _load_candidates(test_story_candidates_path) if test_story_candidates_path else []

    # Tag source if not already set
    for story in research_stories:
        if "_source" not in story:
            story["_source"] = "research"
    for story in test_stories:
        if "_source" not in story:
            story["_source"] = "test-fix"
    for story in ai_suggest_stories:
        if "_source" not in story:
            story["_source"] = "ai-example"
    for story in test_story_candidates:
        if "_source" not in story:
            story["_source"] = "test-story"

    seen_titles: set[str] = set()
    all_candidates: list[dict] = []
    # Order: research, test-fix, ai-example, test-story
    for story in research_stories + test_stories + ai_suggest_stories + test_story_candidates:
        t = story.get("title", "").strip().lower()
        if t and t not in seen_titles:
            seen_titles.add(t)
            all_candidates.append(story)

    accepted: list[dict] = []
    rejected: list[dict] = []

    # ── Batch API path (US-390) ───────────────────────────────────────────
    if use_batch_api:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            print(
                "  [S] WARNING: --batch-api requested but ANTHROPIC_API_KEY not set"
                " — falling back to keyword validation",
                file=sys.stderr,
            )
            use_batch_api = False
        else:
            _base = batch_base_url or os.environ.get(
                "SPIRAL_BATCH_API_URL", "https://api.anthropic.com"
            )
            try:
                # Filter candidates that need LLM validation (research / ai-example)
                # test-fix and test-story are auto-approved (same as keyword path)
                llm_candidates: list[dict] = []
                auto_approved: list[dict] = []
                for story in all_candidates:
                    if not story.get("title", "").strip():
                        continue
                    _src = story.get("_source", "research")
                    if story.get("_isTestFix") or _src in ("test-fix", "test-story"):
                        auto_approved.append(story)
                    else:
                        llm_candidates.append(story)

                accepted.extend(auto_approved)

                if llm_candidates:
                    _accepted, _rejected = _validate_via_batch_api(
                        llm_candidates,
                        goals,
                        forbidden_phrases,
                        api_key,
                        batch_out,
                        _base,
                        batch_size=batch_size,
                    )
                    accepted.extend(_accepted)
                    rejected.extend(_rejected)

                # Write outputs
                atomic_write_json(validated_out, {"stories": accepted})
                atomic_write_json(rejected_out, {"stories": rejected})
                return accepted, rejected
            except Exception as exc:  # noqa: BLE001
                print(
                    f"  [S] WARNING: Batch API validation failed ({exc})"
                    " — falling back to keyword validation",
                    file=sys.stderr,
                )
                # Reset and fall through to keyword path
                accepted = []
                rejected = []

    # ── Keyword / constitution path (default) ────────────────────────────
    for story in all_candidates:
        title = story.get("title", "").strip()
        if not title:
            continue  # skip malformed entries

        rejection_reason: str | None = None

        # 1. Constitution check
        if forbidden_phrases:
            story_text = (title + " " + story.get("description", "")).lower()
            for phrase in forbidden_phrases:
                if phrase in story_text:
                    rejection_reason = f'Violates constitution: "{phrase}"'
                    break

        # 2. Goal alignment check
        # Skipped for: test-fix, test-story (auto-approved; constitution still runs)
        # Applied for: research, ai-example (must connect to project goals)
        _src = story.get("_source", "research")
        _skip_alignment = (
            story.get("_isTestFix")
            or _src in ("test-fix", "test-story")
        )
        if rejection_reason is None and gkw and min_overlap > 0 and not _skip_alignment:
            skw = _story_keywords(story)
            overlap = len(gkw & skw)
            if overlap < min_overlap:
                rejection_reason = (
                    f"No connection to project goals "
                    f"(keyword overlap={overlap}, required>={min_overlap})"
                )

        if rejection_reason:
            rejected.append({**story, "_rejection_reason": rejection_reason})
            print(f"  [S] REJECTED: {title[:70]!r} — {rejection_reason}")
        else:
            accepted.append(story)

    # Write outputs
    atomic_write_json(validated_out, {"stories": accepted})
    atomic_write_json(rejected_out, {"stories": rejected})

    return accepted, rejected


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase S: validate story candidates against project goals"
    )
    parser.add_argument("--prd", required=True, help="Path to prd.json")
    parser.add_argument(
        "--research", required=True, help="Path to _research_output.json"
    )
    parser.add_argument(
        "--test-stories", required=True, help="Path to _test_stories_output.json"
    )
    parser.add_argument(
        "--validated-out", required=True, help="Output: _validated_stories.json"
    )
    parser.add_argument(
        "--rejected-out", required=True, help="Output: _story_rejected.json"
    )
    parser.add_argument(
        "--constitution",
        default="",
        help="Optional constitution file with NOT:/NEVER:/AVOID: lines",
    )
    parser.add_argument(
        "--min-overlap",
        type=int,
        default=1,
        help="Min goal-keyword overlap to accept a story (0 = accept all)",
    )
    parser.add_argument(
        "--ai-suggest",
        default="",
        help="Path to Phase A ai-suggest output (_ai_suggest_output.json)",
    )
    parser.add_argument(
        "--test-story-candidates",
        default="",
        help="Path to Source 5 test story candidates (_test_story_candidates.json)",
    )
    parser.add_argument(
        "--batch-api",
        action="store_true",
        default=False,
        help=(
            "Use Anthropic Message Batches API for validation (requires ANTHROPIC_API_KEY)."
            " Single-story runs fall back to the synchronous /v1/messages path."
        ),
    )
    parser.add_argument(
        "--batch-out",
        default="",
        help="Path to write Phase S batch summary JSON (batch_id + per-story results).",
    )
    parser.add_argument(
        "--batch-base-url",
        default="",
        help="Override Anthropic API base URL (default: https://api.anthropic.com).",
    )
    args = parser.parse_args()

    # --batch-api can also be enabled via env var SPIRAL_BATCH_VALIDATE=1
    use_batch_api: bool = args.batch_api or (
        os.environ.get("SPIRAL_BATCH_VALIDATE", "0").strip() == "1"
    )

    accepted, rejected = validate_stories(
        research_path=args.research,
        test_stories_path=args.test_stories,
        prd_path=args.prd,
        validated_out=args.validated_out,
        rejected_out=args.rejected_out,
        constitution_path=args.constitution,
        min_overlap=args.min_overlap,
        ai_suggest_path=args.ai_suggest,
        test_story_candidates_path=args.test_story_candidates,
        use_batch_api=use_batch_api,
        batch_out=args.batch_out,
        batch_base_url=args.batch_base_url,
    )

    total = len(accepted) + len(rejected)
    rate = (len(accepted) / total * 100) if total > 0 else 100.0
    print(
        f"  [S] Validated {total} stories: "
        f"{len(accepted)} accepted ({rate:.0f}%), {len(rejected)} rejected"
    )

    # Source breakdown
    src_stats: dict[str, list[int]] = {}  # source -> [accepted_count, total_count]
    for story in accepted:
        src = story.get("_source", "research")
        src_stats.setdefault(src, [0, 0])
        src_stats[src][0] += 1
        src_stats[src][1] += 1
    for story in rejected:
        src = story.get("_source", "research")
        src_stats.setdefault(src, [0, 0])
        src_stats[src][1] += 1
    if src_stats:
        parts = " | ".join(
            f"{src}={counts[0]} accepted/{counts[1]}"
            for src, counts in src_stats.items()
        )
        print(f"  [S] Source breakdown: {parts}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
