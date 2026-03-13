/// check_done subcommand — ports check_done.py
use crate::prd;
use std::path::Path;

fn find_latest_report(reports_dir: &str) -> Option<String> {
    if !Path::new(reports_dir).is_dir() {
        return None;
    }
    let entries = std::fs::read_dir(reports_dir).ok()?;
    let mut subdirs: Vec<String> = entries
        .filter_map(|e| e.ok())
        .filter(|e| e.path().is_dir())
        .map(|e| e.file_name().to_string_lossy().to_string())
        .collect();
    subdirs.sort_by(|a, b| b.cmp(a)); // newest-first

    for d in subdirs {
        let candidate = format!("{}/{}/report.json", reports_dir, d);
        if Path::new(&candidate).exists() {
            return Some(candidate);
        }
    }
    None
}

pub fn run(prd_path: &str, reports_dir: &str) -> i32 {
    if !Path::new(prd_path).exists() {
        eprintln!("[check_done] ERROR: {} not found", prd_path);
        return 1;
    }

    let prd_val = match prd::read_json(prd_path) {
        Ok(v) => v,
        Err(e) => {
            eprintln!("[check_done] ERROR: {}", e);
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
    let total = stories.len();
    let pending: Vec<&serde_json::Value> = stories
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
        .collect();
    let done = total - pending.len();

    println!(
        "[check_done] PRD: {}/{} stories complete, {} pending",
        done,
        total,
        pending.len()
    );

    if !pending.is_empty() {
        println!("[check_done] Pending stories:");
        for s in &pending {
            let id = s.get("id").and_then(|v| v.as_str()).unwrap_or("?");
            let title = s.get("title").and_then(|v| v.as_str()).unwrap_or("?");
            let priority = s.get("priority").and_then(|v| v.as_str()).unwrap_or("?");
            println!("  [{}] {} (priority: {})", id, title, priority);
        }
    }

    // ── Check latest test report ─────────────────────────────────────────────
    let report_path = match find_latest_report(reports_dir) {
        Some(p) => p,
        None => {
            eprintln!(
                "[check_done] WARNING: No test report found in {}/ — run tests first",
                reports_dir
            );
            println!("[check_done] RESULT: INCOMPLETE (no test report)");
            return 1;
        }
    };

    // Warn if report is stale (>120 min)
    if let Ok(metadata) = std::fs::metadata(&report_path) {
        if let Ok(modified) = metadata.modified() {
            if let Ok(elapsed) = modified.elapsed() {
                let age_min = elapsed.as_secs() / 60;
                if age_min > 120 {
                    eprintln!(
                        "[check_done] WARNING: Test report is {} min old — results may be stale; re-run tests for accurate check",
                        age_min
                    );
                }
            }
        }
    }

    let report = match prd::read_json(&report_path) {
        Ok(v) => v,
        Err(e) => {
            eprintln!("[check_done] ERROR: {}", e);
            return 1;
        }
    };

    let summary = report.get("summary").cloned().unwrap_or_default();
    let failed = summary.get("failed").and_then(|v| v.as_i64()).unwrap_or(0);
    let errored = summary.get("errored").and_then(|v| v.as_i64()).unwrap_or(0);
    let passed = summary.get("passed").and_then(|v| v.as_i64()).unwrap_or(0);
    let test_total = summary.get("total").and_then(|v| v.as_i64()).unwrap_or(0);
    let pass_rate = summary
        .get("pass_rate")
        .and_then(|v| v.as_str())
        .unwrap_or("?");

    let report_name = Path::new(&report_path)
        .parent()
        .and_then(|p| p.file_name())
        .map(|n| n.to_string_lossy().to_string())
        .unwrap_or_default();

    println!(
        "[check_done] Tests ({}): {}/{} pass ({}), {} failed, {} errored",
        report_name, passed, test_total, pass_rate, failed, errored
    );

    let prd_done = pending.is_empty();
    let tests_clean = failed == 0 && errored == 0;

    if prd_done && tests_clean {
        println!("[check_done] RESULT: SPIRAL COMPLETE — all stories done and 100% tests pass!");
        return 0;
    }

    let mut reasons = Vec::new();
    if !prd_done {
        reasons.push(format!("{} pending stories", pending.len()));
    }
    if !tests_clean {
        reasons.push(format!("{} test failure(s)", failed + errored));
    }
    println!(
        "[check_done] RESULT: INCOMPLETE ({})",
        reasons.join(", ")
    );
    1
}
