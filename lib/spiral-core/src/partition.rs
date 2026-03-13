/// partition subcommand — ports partition_prd.py
use crate::prd;
use std::collections::{HashMap, HashSet};

fn priority_rank(p: &str) -> i32 {
    match p {
        "critical" => 0,
        "high" => 1,
        "medium" => 2,
        "low" => 3,
        _ => 2,
    }
}

/// Compute topological levels for pending stories.
/// Level 0 = no pending deps. Level N = all pending deps are at level < N.
fn compute_levels(pending: &[serde_json::Value]) -> HashMap<String, usize> {
    let pending_ids: HashSet<String> = pending
        .iter()
        .filter_map(|s| s.get("id").and_then(|v| v.as_str()))
        .map(|s| s.to_string())
        .collect();

    let mut deps: HashMap<String, HashSet<String>> = HashMap::new();
    for s in pending {
        if let Some(sid) = s.get("id").and_then(|v| v.as_str()) {
            let dep_set: HashSet<String> = s
                .get("dependencies")
                .and_then(|d| d.as_array())
                .map(|arr| {
                    arr.iter()
                        .filter_map(|d| d.as_str())
                        .filter(|d| pending_ids.contains(*d))
                        .map(|s| s.to_string())
                        .collect()
                })
                .unwrap_or_default();
            deps.insert(sid.to_string(), dep_set);
        }
    }

    let mut levels: HashMap<String, usize> = HashMap::new();
    let mut resolved: HashSet<String> = HashSet::new();
    let mut level = 0usize;

    while resolved.len() < pending_ids.len() {
        let batch: Vec<String> = pending_ids
            .iter()
            .filter(|sid| !resolved.contains(*sid))
            .filter(|sid| {
                deps.get(*sid)
                    .map(|d| d.is_subset(&resolved))
                    .unwrap_or(true)
            })
            .cloned()
            .collect();

        if batch.is_empty() {
            // Circular deps — assign remaining at current level
            for sid in pending_ids.difference(&resolved) {
                levels.insert(sid.clone(), level);
            }
            break;
        }

        for sid in batch {
            levels.insert(sid.clone(), level);
            resolved.insert(sid);
        }
        level += 1;
    }

    levels
}

fn get_files_to_touch(story: &serde_json::Value) -> HashSet<String> {
    let mut files: HashSet<String> = story
        .get("filesTouch")
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str())
                .map(|s| s.to_string())
                .collect()
        })
        .unwrap_or_default();

    if files.is_empty() {
        // Also check technicalHints.filesTouch
        if let Some(hints) = story.get("technicalHints").and_then(|v| v.as_object()) {
            if let Some(ft) = hints.get("filesTouch").and_then(|v| v.as_array()) {
                files = ft
                    .iter()
                    .filter_map(|v| v.as_str())
                    .map(|s| s.to_string())
                    .collect();
            }
        }
    }
    files
}

/// Assign pending stories to n_workers buckets using dep co-location + file co-location
fn assign_stories(
    pending: &[serde_json::Value],
    n_workers: usize,
) -> Vec<Vec<serde_json::Value>> {
    if pending.is_empty() {
        return (0..n_workers).map(|_| Vec::new()).collect();
    }

    let pending_ids: HashSet<String> = pending
        .iter()
        .filter_map(|s| s.get("id").and_then(|v| v.as_str()))
        .map(|s| s.to_string())
        .collect();

    // Sort by priority so high-priority stories get bucket assignment first
    let mut pending_sorted: Vec<&serde_json::Value> = pending.iter().collect();
    pending_sorted.sort_by_key(|s| {
        priority_rank(s.get("priority").and_then(|v| v.as_str()).unwrap_or("medium"))
    });

    let mut buckets: Vec<Vec<serde_json::Value>> = (0..n_workers).map(|_| Vec::new()).collect();
    let mut assignments: HashMap<String, usize> = HashMap::new();
    let mut file_to_worker: HashMap<String, usize> = HashMap::new();

    for story in pending_sorted {
        let sid = story
            .get("id")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();

        // 1. Dependency co-location
        let deps_pending: Vec<String> = story
            .get("dependencies")
            .and_then(|d| d.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|d| d.as_str())
                    .filter(|d| pending_ids.contains(*d))
                    .map(|s| s.to_string())
                    .collect()
            })
            .unwrap_or_default();

        let mut assigned_worker: Option<usize> = None;
        for dep_id in &deps_pending {
            if let Some(&w) = assignments.get(dep_id) {
                assigned_worker = Some(w);
                break;
            }
        }

        // 2. File-overlap co-location
        let files_hint = get_files_to_touch(story);
        if assigned_worker.is_none() {
            for f in &files_hint {
                if let Some(&w) = file_to_worker.get(f) {
                    assigned_worker = Some(w);
                    break;
                }
            }
        }

        // 3. Least-loaded fallback
        let worker = assigned_worker.unwrap_or_else(|| {
            (0..n_workers)
                .min_by_key(|&i| buckets[i].len())
                .unwrap_or(0)
        });

        buckets[worker].push(story.clone());
        assignments.insert(sid, worker);
        for f in files_hint {
            file_to_worker.entry(f).or_insert(worker);
        }
    }

    buckets
}

pub fn run(
    prd_path: &str,
    workers: usize,
    outdir: &str,
    wave_count: Option<usize>,
    list_waves: bool,
    wave_level: Option<usize>,
) -> i32 {
    if !std::path::Path::new(prd_path).exists() {
        eprintln!("[partition] ERROR: {} not found", prd_path);
        return 1;
    }

    let prd_val = match prd::read_json(prd_path) {
        Ok(v) => v,
        Err(e) => {
            eprintln!("[partition] ERROR: {}", e);
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

    let stories = prd_val["userStories"].as_array().unwrap();
    let completed: Vec<serde_json::Value> = stories
        .iter()
        .filter(|s| {
            s.get("passes")
                .and_then(|v| v.as_bool())
                .unwrap_or(false)
        })
        .cloned()
        .collect();
    let pending: Vec<serde_json::Value> = stories
        .iter()
        .filter(|s| {
            !s.get("passes")
                .and_then(|v| v.as_bool())
                .unwrap_or(false)
                && !s
                    .get("_decomposed")
                    .and_then(|v| v.as_bool())
                    .unwrap_or(false)
        })
        .cloned()
        .collect();

    // ── Query mode: --list-waves ─────────────────────────────────────────────
    if list_waves {
        if pending.is_empty() {
            println!("0");
            return 0;
        }
        let levels = compute_levels(&pending);
        let max_level = levels.values().copied().max().unwrap_or(0) + 1;
        println!("{}", max_level);
        return 0;
    }

    // ── Query mode: --wave-count N ───────────────────────────────────────────
    if let Some(n) = wave_count {
        if pending.is_empty() {
            println!("0");
            return 0;
        }
        let levels = compute_levels(&pending);
        let count = levels.values().filter(|&&lvl| lvl == n).count();
        println!("{}", count);
        return 0;
    }

    // ── Partition mode ───────────────────────────────────────────────────────
    if workers < 2 {
        eprintln!("[partition] ERROR: --workers must be >= 2");
        return 1;
    }
    if outdir.is_empty() {
        eprintln!("[partition] ERROR: --outdir is required for partition mode");
        return 1;
    }

    let mut pending_to_use = pending.clone();
    if let Some(n) = wave_level {
        if pending_to_use.is_empty() {
            println!("[partition] No pending stories — nothing to partition");
            return 0;
        }
        let levels = compute_levels(&pending_to_use);
        pending_to_use = pending_to_use
            .into_iter()
            .filter(|s| {
                let sid = s.get("id").and_then(|v| v.as_str()).unwrap_or("");
                levels.get(sid).copied().unwrap_or(0) == n
            })
            .collect();
        println!(
            "[partition] Filtered to wave level {}: {} stories",
            n,
            pending_to_use.len()
        );
    }

    println!(
        "[partition] {} completed, {} pending → {} workers",
        completed.len(),
        pending_to_use.len(),
        workers
    );

    if pending_to_use.is_empty() {
        println!("[partition] No pending stories — nothing to partition");
        return 0;
    }

    let buckets = assign_stories(&pending_to_use, workers);
    let _ = std::fs::create_dir_all(outdir);

    const PRIO_ORDER: &[(&str, i32)] = &[
        ("critical", 0),
        ("high", 1),
        ("medium", 2),
        ("low", 3),
    ];

    for (i, bucket) in buckets.iter().enumerate() {
        let worker_num = i + 1;
        let mut worker_prd = prd_val.clone();
        let mut worker_stories = completed.clone();
        worker_stories.extend_from_slice(bucket);
        worker_prd["userStories"] = serde_json::Value::Array(worker_stories);

        let out_path = format!("{}/worker_{}.json", outdir, worker_num);
        match prd::write_json_atomic(&out_path, &worker_prd) {
            Ok(_) => {}
            Err(e) => {
                eprintln!("[partition] ERROR: {}", e);
                return 1;
            }
        }

        let story_ids: Vec<&str> = bucket
            .iter()
            .filter_map(|s| s.get("id").and_then(|v| v.as_str()))
            .collect();
        let id_list = if story_ids.len() > 5 {
            format!("{}...", story_ids[..5].join(", "))
        } else {
            story_ids.join(", ")
        };

        let mut pcount: HashMap<&str, usize> = HashMap::new();
        for s in bucket {
            let p = s
                .get("priority")
                .and_then(|v| v.as_str())
                .unwrap_or("medium");
            *pcount.entry(p).or_insert(0) += 1;
        }
        let mut pcount_parts: Vec<(&str, usize)> = pcount.into_iter().collect();
        pcount_parts.sort_by_key(|(p, _)| {
            PRIO_ORDER
                .iter()
                .find(|(n, _)| *n == *p)
                .map(|(_, r)| *r)
                .unwrap_or(2)
        });
        let pcount_str: Vec<String> = pcount_parts
            .iter()
            .map(|(p, c)| format!("{}:{}", p, c))
            .collect();

        println!(
            "[partition] Worker {}: {} stories [{}] ({}) → {}",
            worker_num,
            bucket.len(),
            id_list,
            pcount_str.join(" "),
            out_path
        );
    }

    0
}
