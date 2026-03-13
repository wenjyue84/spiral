/// merge_workers subcommand — ports merge_worker_results.py
use crate::prd;
use std::collections::{HashMap, HashSet};

pub fn run(main_path: &str, worker_paths: &[String]) -> i32 {
    if !std::path::Path::new(main_path).exists() {
        eprintln!("[merge_workers] ERROR: {} not found", main_path);
        return 1;
    }

    let mut main_prd = match prd::read_json(main_path) {
        Ok(v) => v,
        Err(e) => {
            eprintln!("[merge_workers] ERROR: {}", e);
            return 1;
        }
    };

    let errors = prd::validate_prd(&main_prd);
    if !errors.is_empty() {
        eprintln!("[schema] Main PRD validation failed:");
        for e in &errors {
            eprintln!("  - {}", e);
        }
        return 1;
    }

    let main_ids: HashSet<String> = main_prd["userStories"]
        .as_array()
        .map(|arr| {
            arr.iter()
                .filter_map(|s| s.get("id").and_then(|v| v.as_str()))
                .map(|s| s.to_string())
                .collect()
        })
        .unwrap_or_default();

    let mut passed_ids: HashSet<String> = HashSet::new();
    let mut decomposed_map: HashMap<String, Vec<String>> = HashMap::new();
    let mut new_substories: Vec<serde_json::Value> = Vec::new();

    for wpath in worker_paths {
        if !std::path::Path::new(wpath).exists() {
            println!("[merge_workers] WARNING: {} not found — skipping", wpath);
            continue;
        }
        let worker_prd = match prd::read_json(wpath) {
            Ok(v) => v,
            Err(e) => {
                eprintln!("[merge_workers] WARNING: {}", e);
                continue;
            }
        };
        let w_errors = prd::validate_prd(&worker_prd);
        if !w_errors.is_empty() {
            eprintln!("[schema] Worker PRD validation failed ({}):", wpath);
            for e in &w_errors {
                eprintln!("  - {}", e);
            }
            return 1;
        }
        if let Some(w_stories) = worker_prd["userStories"].as_array() {
            for s in w_stories {
                let sid = s
                    .get("id")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string();

                // Collect passed stories
                if s.get("passes").and_then(|v| v.as_bool()).unwrap_or(false) {
                    passed_ids.insert(sid.clone());
                }

                // Collect decomposition flags from workers
                if s.get("_decomposed")
                    .and_then(|v| v.as_bool())
                    .unwrap_or(false)
                    && main_ids.contains(&sid)
                {
                    let children: Vec<String> = s
                        .get("_decomposedInto")
                        .and_then(|v| v.as_array())
                        .map(|arr| {
                            arr.iter()
                                .filter_map(|v| v.as_str())
                                .map(|s| s.to_string())
                                .collect()
                        })
                        .unwrap_or_default();
                    decomposed_map.insert(sid.clone(), children);
                }

                // Collect new sub-stories created by decomposition
                let decomposed_from = s
                    .get("_decomposedFrom")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string();
                if !decomposed_from.is_empty() && !main_ids.contains(&sid) {
                    new_substories.push(s.clone());
                }
            }
        }
    }

    // Promote passes and decomposition in main PRD
    let mut newly_passed = 0;
    if let Some(stories) = main_prd["userStories"].as_array_mut() {
        for s in stories.iter_mut() {
            let sid = s
                .get("id")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();

            if passed_ids.contains(&sid)
                && !s.get("passes").and_then(|v| v.as_bool()).unwrap_or(false)
            {
                s["passes"] = serde_json::json!(true);
                newly_passed += 1;
                let title = s.get("title").and_then(|v| v.as_str()).unwrap_or("");
                println!(
                    "[merge_workers]   + {} — {}",
                    sid,
                    &title[..title.len().min(60)]
                );
            }

            if let Some(children) = decomposed_map.get(&sid) {
                s["_decomposed"] = serde_json::json!(true);
                s["_decomposedInto"] = serde_json::Value::Array(
                    children.iter().map(|c| serde_json::json!(c)).collect(),
                );
                println!(
                    "[merge_workers]   ~ {} decomposed → [{}]",
                    sid,
                    children.join(", ")
                );
            }
        }
    }

    // Append new sub-stories
    if !new_substories.is_empty() {
        if let Some(stories) = main_prd["userStories"].as_array_mut() {
            for ss in &new_substories {
                let sid = ss.get("id").and_then(|v| v.as_str()).unwrap_or("?");
                let parent = ss
                    .get("_decomposedFrom")
                    .and_then(|v| v.as_str())
                    .unwrap_or("?");
                let title = ss.get("title").and_then(|v| v.as_str()).unwrap_or("");
                println!(
                    "[merge_workers]   + {} (sub-story of {}) — {}",
                    sid,
                    parent,
                    &title[..title.len().min(60)]
                );
                stories.push(ss.clone());
            }
        }
    }

    match prd::write_json_atomic(main_path, &main_prd) {
        Ok(_) => {}
        Err(e) => {
            eprintln!("[merge_workers] ERROR: {}", e);
            return 1;
        }
    }

    let total = main_prd["userStories"]
        .as_array()
        .map(|a| a.len())
        .unwrap_or(0);
    let total_passed = main_prd["userStories"]
        .as_array()
        .map(|arr| {
            arr.iter()
                .filter(|s| s.get("passes").and_then(|v| v.as_bool()).unwrap_or(false))
                .count()
        })
        .unwrap_or(0);
    let pending = total - total_passed;

    println!(
        "[merge_workers] {} newly passed. Total: {}/{} ({} pending)",
        newly_passed, total_passed, total, pending
    );
    0
}
