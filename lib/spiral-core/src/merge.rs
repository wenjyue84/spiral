/// merge subcommand — ports merge_stories.py
use crate::prd;
use regex::Regex;

const PRIORITY_RANKS: &[(&str, i32)] = &[
    ("critical", 0),
    ("high", 1),
    ("medium", 2),
    ("low", 3),
];

fn priority_rank(p: &str) -> i32 {
    for (name, rank) in PRIORITY_RANKS {
        if p == *name {
            return *rank;
        }
    }
    2 // default medium
}

fn find_next_id(stories: &[serde_json::Value], prefix: &str) -> usize {
    let escaped = regex::escape(prefix);
    let re = Regex::new(&format!(r"^{}-(\d+)$", escaped)).unwrap();
    let mut max_id = 0usize;
    for s in stories {
        if let Some(id) = s.get("id").and_then(|v| v.as_str()) {
            if let Some(cap) = re.captures(id) {
                if let Ok(n) = cap[1].parse::<usize>() {
                    if n > max_id {
                        max_id = n;
                    }
                }
            }
        }
    }
    max_id + 1
}

fn matches_focus(story: &serde_json::Value, focus: &str) -> bool {
    if focus.is_empty() {
        return true;
    }
    let focus_lower = focus.to_lowercase();
    let title = story.get("title").and_then(|v| v.as_str()).unwrap_or("");
    let desc = story.get("description").and_then(|v| v.as_str()).unwrap_or("");
    let searchable = format!("{} {}", title, desc).to_lowercase();
    searchable.contains(&focus_lower)
}

fn load_candidates(path: &str) -> Vec<serde_json::Value> {
    if path.is_empty() || !std::path::Path::new(path).exists() {
        if !path.is_empty() {
            println!("[merge] WARNING: {} not found — treating as empty", path);
        }
        return Vec::new();
    }
    match prd::read_json(path) {
        Ok(v) => v
            .get("stories")
            .and_then(|s| s.as_array())
            .cloned()
            .unwrap_or_default(),
        Err(e) => {
            eprintln!("[merge] WARNING: {}", e);
            Vec::new()
        }
    }
}

fn story_to_prd_entry(story: &serde_json::Value, story_id: &str) -> serde_json::Value {
    let mut entry = serde_json::json!({
        "id": story_id,
        "title": story.get("title").cloned().unwrap_or(serde_json::Value::Null),
        "priority": story.get("priority").cloned().unwrap_or_else(|| serde_json::json!("medium")),
        "description": story.get("description").cloned().unwrap_or_else(|| serde_json::json!("")),
        "acceptanceCriteria": story.get("acceptanceCriteria").cloned().unwrap_or_else(|| serde_json::json!([])),
        "technicalNotes": story.get("technicalNotes").cloned().unwrap_or_else(|| serde_json::json!([])),
        "dependencies": story.get("dependencies").cloned().unwrap_or_else(|| serde_json::json!([])),
        "estimatedComplexity": story.get("estimatedComplexity").cloned().unwrap_or_else(|| serde_json::json!("medium")),
        "passes": false,
    });
    if let Some(source) = story.get("_source") {
        entry["_source"] = source.clone();
    }
    if story
        .get("_isTestFix")
        .and_then(|v| v.as_bool())
        .unwrap_or(false)
    {
        entry["isTestFix"] = serde_json::json!(true);
    }
    entry
}

#[allow(clippy::too_many_arguments)]
pub fn run(
    prd_path: &str,
    research_path: &str,
    test_stories_path: &str,
    overflow_in: &str,
    overflow_out: &str,
    max_new: usize,
    max_pending: usize,
    focus: &str,
) -> i32 {
    if !std::path::Path::new(prd_path).exists() {
        eprintln!("[merge] ERROR: {} not found", prd_path);
        return 1;
    }

    let mut prd_val = match prd::read_json(prd_path) {
        Ok(v) => v,
        Err(e) => {
            eprintln!("[merge] ERROR: {}", e);
            return 1;
        }
    };

    let errors = prd::validate_prd(&prd_val);
    if !errors.is_empty() {
        eprintln!("[schema] PRD validation failed:");
        for e in &errors {
            eprintln!("  - {}", e);
        }
        return 1;
    }

    let existing_stories: Vec<serde_json::Value> = prd_val["userStories"]
        .as_array()
        .cloned()
        .unwrap_or_default();
    let existing_titles: Vec<String> = existing_stories
        .iter()
        .filter_map(|s| s.get("title").and_then(|v| v.as_str()))
        .map(|s| s.to_string())
        .collect();
    let current_pending = existing_stories
        .iter()
        .filter(|s| {
            !s.get("passes")
                .and_then(|v| v.as_bool())
                .unwrap_or(false)
        })
        .count();

    println!(
        "[merge] prd.json: {} existing stories ({} pending)",
        existing_stories.len(),
        current_pending
    );

    let effective_cap = if max_pending > 0 {
        let room = max_pending.saturating_sub(current_pending);
        println!(
            "[merge] Max pending limit: {} (current: {}, room: {})",
            max_pending, current_pending, room
        );
        if room == 0 {
            println!(
                "[merge] At or over max pending limit ({}/{}) — no new stories will be added",
                current_pending, max_pending
            );
            return 0;
        }
        std::cmp::min(max_new, room)
    } else {
        max_new
    };

    let mut test_candidates = load_candidates(test_stories_path);
    let mut research_candidates = load_candidates(research_path);
    let overflow_candidates = if overflow_in.is_empty() {
        Vec::new()
    } else {
        load_candidates(overflow_in)
    };

    if !overflow_candidates.is_empty() {
        println!(
            "[merge] Overflow (carried from previous iteration): {} candidates",
            overflow_candidates.len()
        );
    }
    println!(
        "[merge] Test candidates: {}, Research candidates: {}",
        test_candidates.len(),
        research_candidates.len()
    );

    // Sort by priority
    test_candidates.sort_by_key(|s| {
        priority_rank(s.get("priority").and_then(|v| v.as_str()).unwrap_or("medium"))
    });
    research_candidates.sort_by_key(|s| {
        priority_rank(s.get("priority").and_then(|v| v.as_str()).unwrap_or("medium"))
    });

    if !focus.is_empty() {
        test_candidates.sort_by(|a, b| {
            let fa = if matches_focus(a, focus) { 0i32 } else { 1 };
            let fb = if matches_focus(b, focus) { 0i32 } else { 1 };
            fa.cmp(&fb).then(
                priority_rank(a.get("priority").and_then(|v| v.as_str()).unwrap_or("medium"))
                    .cmp(&priority_rank(
                        b.get("priority").and_then(|v| v.as_str()).unwrap_or("medium"),
                    )),
            )
        });
        println!(
            "[merge] Focus: \"{}\" — research hard-filtered, test stories soft-prioritized",
            focus
        );
    }

    let mut new_stories: Vec<serde_json::Value> = Vec::new();
    let mut seen_titles: Vec<String> = existing_titles.clone();

    // ── Group 1: Test-synthesis candidates ──────────────────────────────────
    for mut story in test_candidates {
        if new_stories.len() >= effective_cap {
            println!(
                "[merge] Cap of {} reached during test candidates",
                effective_cap
            );
            break;
        }
        let title = story
            .get("title")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        if title.is_empty() {
            continue;
        }
        if prd::is_duplicate(&title, &seen_titles, 0.6) {
            println!(
                "[merge] Skip duplicate (test): {}",
                &title[..title.len().min(80)]
            );
            continue;
        }
        story["_isTestFix"] = serde_json::json!(true);
        seen_titles.push(title);
        new_stories.push(story);
    }

    // ── Group 2: Research pool = overflow (priority) + fresh research ───────
    let research_pool: Vec<serde_json::Value> = overflow_candidates
        .into_iter()
        .chain(research_candidates.into_iter())
        .collect();
    let mut leftover_research: Vec<serde_json::Value> = Vec::new();

    for story in research_pool {
        let title = story
            .get("title")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        if title.is_empty() {
            continue;
        }
        if !focus.is_empty() && !matches_focus(&story, focus) {
            println!(
                "[merge] Skip (focus mismatch): {}",
                &title[..title.len().min(80)]
            );
            continue;
        }
        if prd::is_duplicate(&title, &seen_titles, 0.6) {
            println!(
                "[merge] Skip duplicate (research): {}",
                &title[..title.len().min(80)]
            );
            continue;
        }
        if new_stories.len() >= effective_cap {
            // Cap hit — save non-duplicate for next iteration (strip _ fields)
            let mut leftover = serde_json::json!({});
            if let Some(obj) = story.as_object() {
                for (k, v) in obj {
                    if !k.starts_with('_') {
                        leftover[k] = v.clone();
                    }
                }
            }
            leftover_research.push(leftover);
        } else {
            seen_titles.push(title);
            new_stories.push(story);
        }
    }

    // ── Write overflow file ──────────────────────────────────────────────────
    if !overflow_out.is_empty() {
        let leftover_count = leftover_research.len();
        let overflow_val = serde_json::json!({ "stories": leftover_research });
        match prd::write_json_atomic(overflow_out, &overflow_val) {
            Ok(_) => {
                if leftover_count > 0 {
                    println!(
                        "[merge] Overflow: {} unused research candidates → {}",
                        leftover_count, overflow_out
                    );
                } else {
                    println!("[merge] Overflow: cleared (all candidates consumed or cap not reached)");
                }
            }
            Err(e) => eprintln!("[merge] WARNING: Failed to write overflow: {}", e),
        }
    }

    if new_stories.is_empty() {
        println!("[merge] No new stories to add — prd.json unchanged");
        return 0;
    }

    // ── Assign IDs and patch prd.json atomically ─────────────────────────────
    let prefix = prd::story_prefix();
    let mut next_num = find_next_id(&existing_stories, &prefix);
    let mut added_entries: Vec<serde_json::Value> = Vec::new();

    for story in &new_stories {
        let story_id = format!("{}-{:03}", prefix, next_num);
        next_num += 1;
        let entry = story_to_prd_entry(story, &story_id);
        let flag = if entry
            .get("isTestFix")
            .and_then(|v| v.as_bool())
            .unwrap_or(false)
        {
            " [testFix]"
        } else {
            ""
        };
        let title = entry
            .get("title")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let prio = entry
            .get("priority")
            .and_then(|v| v.as_str())
            .unwrap_or("medium");
        println!(
            "[merge] Adding [{}] ({}){} {}",
            story_id,
            prio,
            flag,
            &title[..title.len().min(70)]
        );
        added_entries.push(entry);
    }

    let mut all_stories = existing_stories.clone();
    all_stories.extend(added_entries.iter().cloned());
    prd_val["userStories"] = serde_json::Value::Array(all_stories.clone());

    match prd::write_json_atomic(prd_path, &prd_val) {
        Ok(_) => {}
        Err(e) => {
            eprintln!("[merge] ERROR: {}", e);
            return 1;
        }
    }

    let total_after = all_stories.len();
    let pending_after = all_stories
        .iter()
        .filter(|s| {
            !s.get("passes")
                .and_then(|v| v.as_bool())
                .unwrap_or(false)
        })
        .count();
    println!(
        "[merge] Done: added {} stories. prd.json now has {} total ({} pending).",
        added_entries.len(),
        total_after,
        pending_after
    );
    0
}
