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
from typing import Any

from pydantic import ValidationError

sys.path.insert(0, os.path.dirname(__file__))
from spiral_io import atomic_write_json, configure_utf8_stdout

configure_utf8_stdout()

# Common English stopwords to exclude from keyword comparison
_STOPWORDS = {
    "the",
    "and",
    "for",
    "are",
    "was",
    "this",
    "with",
    "from",
    "that",
    "not",
    "all",
    "can",
    "but",
    "has",
    "new",
    "add",
    "run",
    "use",
    "set",
    "get",
    "put",
    "may",
    "via",
    "its",
    "also",
    "any",
    "each",
    "when",
    "have",
    "been",
    "will",
    "into",
    "only",
    "more",
    "such",
    "than",
    "then",
    "they",
    "their",
    "them",
    "what",
    "where",
    "which",
    "who",
    "how",
    "per",
    "non",
    "now",
    "one",
    "two",
    "should",
    "would",
    "could",
    "must",
    "does",
    "did",
    "out",
    "too",
    "end",
    "log",
    "key",
}


def _story_text(story: dict[str, Any]) -> str:
    """Combine title + description + first 2 acceptance criteria for TF-IDF."""
    parts: list[str] = [
        story.get("title", ""),
        story.get("description", ""),
    ]
    acs = story.get("acceptanceCriteria", [])
    if isinstance(acs, list):
        parts.extend(str(a) for a in acs[:2])
    return " ".join(p for p in parts if p)


def _semantic_dedup_pass(
    candidates: list[dict[str, Any]],
    existing_stories: list[dict[str, Any]],
    threshold: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (kept_candidates, semantic_rejected) using TF-IDF cosine similarity.

    Only stories with _source in ['research', 'ai-example'] are checked.
    Compares each candidate against existing prd.json stories.
    """
    if threshold <= 0.0 or not existing_stories:
        return candidates, []

    to_check = [(i, c) for i, c in enumerate(candidates) if c.get("_source") in ("research", "ai-example")]
    if not to_check:
        return candidates, []

    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
    except ImportError:
        return candidates, []

    existing_pairs = [(s, _story_text(s)) for s in existing_stories if _story_text(s).strip()]
    if not existing_pairs:
        return candidates, []

    f_existing_stories_seq, f_existing_texts_seq = zip(*existing_pairs)
    f_existing_stories: tuple[dict[str, Any], ...] = f_existing_stories_seq
    f_existing_texts: tuple[str, ...] = f_existing_texts_seq

    kept_indices: set[int] = set(range(len(candidates)))
    semantic_rejected: list[dict[str, Any]] = []

    for i, candidate in to_check:
        candidate_text = _story_text(candidate)
        if not candidate_text.strip():
            continue
        all_texts: list[str] = list(f_existing_texts) + [candidate_text]
        try:
            vectorizer = TfidfVectorizer(min_df=1, stop_words="english")
            tfidf_matrix = vectorizer.fit_transform(all_texts)
        except ValueError:
            continue
        candidate_vec = tfidf_matrix[-1]
        existing_vecs = tfidf_matrix[:-1]
        sims = cosine_similarity(candidate_vec, existing_vecs)[0]
        max_idx = int(sims.argmax())
        max_sim = float(sims[max_idx])
        if max_sim >= threshold:
            duplicate_of = f_existing_stories[max_idx].get("id", "unknown")
            reason = f"semantic_duplicate_of: {duplicate_of}"
            semantic_rejected.append({**candidate, "_rejected": True, "_rejection_reason": reason})
            kept_indices.discard(i)
            print(f"  [S] REJECTED (semantic_dup): {candidate.get('title', '')[:70]!r} — {reason}")

    kept = [candidates[i] for i in range(len(candidates)) if i in kept_indices]
    return kept, semantic_rejected


def _normalize(text: str) -> set[str]:
    """Extract lowercase alpha-numeric tokens >= 3 chars, excluding stopwords."""
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) >= 3 and w not in _STOPWORDS}


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
    """Load story candidates from a JSON or YAML file with a .stories array."""
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as fh:
            if path.endswith(".yaml") or path.endswith(".yml"):
                try:
                    import yaml

                    data = yaml.safe_load(fh) or {}
                except ImportError:
                    print(f"  [S] WARNING: pyyaml not installed; cannot read {path} — skipping")
                    return []
            else:
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
                        phrase = line[len(prefix) :].strip().lower()
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
    num_votes: int = 1,
) -> tuple[list[dict], list[dict]]:
    """Validate story candidates using the Anthropic Message Batches API.

    Assigns a ``_custom_id`` to each candidate (its index) and submits a
    single batch request (or multiple chunks when *batch_size* > 0).
    Polls until all results are available, then applies the LLM decisions.
    The batch_id is written to *batch_out* and stamped onto each story as
    ``_batch_id``.

    Single-story runs use the synchronous /v1/messages fallback with optional
    majority-voting consensus (US-342) when num_votes > 1.

    Parameters
    ----------
    batch_size:
        Maximum number of stories per batch request (0 = no cap, send all
        in one batch). When > 0, candidates are split into chunks of this
        size and submitted as separate batch requests.
    num_votes:
        Number of independent validation calls per story (default 1).
        When > 1, results are aggregated with majority voting. Requires ANTHROPIC_API_KEY.
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
        # --- Synchronous fallback for single story (with optional voting) ---
        story = all_candidates[0]
        if num_votes > 1:
            ok, reason, votes_accept, votes_reject = _bv.validate_story_sync_votes(
                story, goal_text, forbidden_phrases, api_key, base_url, num_votes
            )
            story["_votes_accept"] = votes_accept
            story["_votes_reject"] = votes_reject
        else:
            ok, reason = _bv.validate_story_sync(story, goal_text, forbidden_phrases, api_key, base_url)
            story["_votes_accept"] = 1 if ok else 0
            story["_votes_reject"] = 0 if ok else 1

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
            all_candidates[i : i + chunk_size] for i in range(0, len(all_candidates), chunk_size)
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
    num_votes: int = 1,
) -> tuple[list[dict], list[dict]]:
    """Core validation logic. Returns (accepted, rejected) lists.

    Parameters
    ----------
    num_votes:
        Number of independent validation calls per story (default 1, no voting).
        When > 1, results are aggregated with majority voting (US-342).
        Requires ANTHROPIC_API_KEY and only applies to LLM validation paths.
    """

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

    # ── Semantic dedup pass (US-371) ─────────────────────────────────────────
    sem_threshold = float(os.environ.get("SPIRAL_SEMANTIC_DEDUP_THRESHOLD", "0.85"))
    existing_stories = prd.get("userStories", [])
    all_candidates, pre_rejected = _semantic_dedup_pass(all_candidates, existing_stories, sem_threshold)

    accepted: list[dict] = []
    rejected: list[dict] = list(pre_rejected)

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
            _base = batch_base_url or os.environ.get("SPIRAL_BATCH_API_URL", "https://api.anthropic.com")
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
                        num_votes=num_votes,
                    )
                    accepted.extend(_accepted)
                    rejected.extend(_rejected)

                # Write outputs
                atomic_write_json(validated_out, {"stories": accepted})
                atomic_write_json(rejected_out, {"stories": rejected})
                return accepted, rejected
            except Exception as exc:  # noqa: BLE001
                print(
                    f"  [S] WARNING: Batch API validation failed ({exc}) — falling back to keyword validation",
                    file=sys.stderr,
                )
                # Reset and fall through to keyword path
                accepted = []
                rejected = []

    # ── Keyword / constitution path (default) ────────────────────────────
    _empty_tech_notes_count = 0
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
        _skip_alignment = story.get("_isTestFix") or _src in ("test-fix", "test-story")
        if rejection_reason is None and gkw and min_overlap > 0 and not _skip_alignment:
            skw = _story_keywords(story)
            overlap = len(gkw & skw)
            if overlap < min_overlap:
                rejection_reason = (
                    f"No connection to project goals (keyword overlap={overlap}, required>={min_overlap})"
                )

        # 3. Complexity gate — reject "large" stories before PRD merge (US-442)
        # Large stories consistently hit cost ceilings and require late decomposition.
        # Forcing split at creation time avoids wasting retry budget.
        if rejection_reason is None:
            complexity = story.get("estimatedComplexity", "")
            if complexity == "large":
                rejection_reason = "complexity_too_large: split into small/medium stories before submitting"

        # 4. AC and technicalNotes quality warnings (non-blocking — logged but do not reject)
        if rejection_reason is None:
            ac_list = story.get("acceptanceCriteria", [])
            if isinstance(ac_list, list) and len(ac_list) > 4:
                print(f"  [S] WARNING: {title[:60]!r} has {len(ac_list)} ACs (recommended <=4)")
            tech_notes = story.get("technicalNotes", [])
            if not tech_notes:
                _empty_tech_notes_count += 1

        if rejection_reason:
            rejected.append({**story, "_rejection_reason": rejection_reason})
            print(f"  [S] REJECTED: {title[:70]!r} — {rejection_reason}")
        else:
            accepted.append(story)

    # Batch summary for empty technicalNotes (instead of per-story spam)
    if _empty_tech_notes_count > 0:
        print(f"  [S] WARNING: {_empty_tech_notes_count} stories have empty technicalNotes (Phase E enrichment will fill these)")

    # Write outputs
    atomic_write_json(validated_out, {"stories": accepted})
    atomic_write_json(rejected_out, {"stories": rejected})

    return accepted, rejected


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase S: validate story candidates against project goals")
    parser.add_argument("--prd", required=True, help="Path to prd.json")
    parser.add_argument("--research", required=True, help="Path to _research_output.json")
    parser.add_argument("--test-stories", required=True, help="Path to _test_stories_output.json")
    parser.add_argument("--validated-out", required=True, help="Output: _validated_stories.json")
    parser.add_argument("--rejected-out", required=True, help="Output: _story_rejected.json")
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
    parser.add_argument(
        "--batch-size",
        type=int,
        default=0,
        help=(
            "Max stories per batch request (0 = no cap, send all in one batch). "
            "Overrides SPIRAL_STORY_BATCH_SIZE env var. "
            "When > 1 and ANTHROPIC_API_KEY is set, batch API is auto-enabled."
        ),
    )
    parser.add_argument(
        "--num-votes",
        type=int,
        default=0,
        help=(
            "Number of independent validation calls per story for majority voting (US-342). "
            "Default 0 reads from SPIRAL_VALIDATION_VOTES env var (default 3). "
            "Set to 1 for single-call behavior (no voting overhead)."
        ),
    )
    args = parser.parse_args()

    # --batch-size from env var fallback
    batch_size: int = args.batch_size or int(os.environ.get("SPIRAL_STORY_BATCH_SIZE", "0") or "0")

    # --num-votes from env var fallback (US-342)
    num_votes: int = args.num_votes or int(os.environ.get("SPIRAL_VALIDATION_VOTES", "3") or "3")

    # --batch-api can also be enabled via env var SPIRAL_BATCH_VALIDATE=1
    # or auto-triggered when batch_size > 1 and ANTHROPIC_API_KEY is set
    use_batch_api: bool = (
        args.batch_api
        or (os.environ.get("SPIRAL_BATCH_VALIDATE", "0").strip() == "1")
        or (batch_size > 1 and bool(os.environ.get("ANTHROPIC_API_KEY", "").strip()))
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
        batch_size=batch_size,
        num_votes=num_votes,
    )

    total = len(accepted) + len(rejected)
    rate = (len(accepted) / total * 100) if total > 0 else 100.0
    print(f"  [S] Validated {total} stories: {len(accepted)} accepted ({rate:.0f}%), {len(rejected)} rejected")

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
        parts = " | ".join(f"{src}={counts[0]} accepted/{counts[1]}" for src, counts in src_stats.items())
        print(f"  [S] Source breakdown: {parts}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
