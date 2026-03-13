/// synthesize subcommand — ports synthesize_tests.py
use crate::prd;
use std::collections::HashSet;
use std::path::Path;

fn priority_from_category(category: &str) -> &'static str {
    match category {
        "smoke" | "security" => "critical",
        "regression" | "api_contract" | "integration" => "high",
        "unit" | "edge_cases" => "medium",
        "performance" => "low",
        _ => "medium",
    }
}

fn parse_test_id(test_id: &str) -> (String, String, String) {
    let parts: Vec<&str> = test_id.split('.').collect();
    let method = parts.last().copied().unwrap_or(test_id).to_string();
    let class_name = if parts.len() >= 2 {
        parts[parts.len() - 2].to_string()
    } else {
        String::new()
    };
    let category_hint = if parts.len() >= 3 {
        format!("{}.{}", parts[1], parts[2])
    } else {
        "unit".to_string()
    };
    (category_hint, class_name, method)
}

fn extract_method_source(filepath: &str, method_name: &str, max_lines: usize) -> Option<String> {
    let content = std::fs::read_to_string(filepath).ok()?;
    let lines: Vec<&str> = content.lines().collect();

    let mut start: Option<usize> = None;
    let mut base_indent = 0usize;

    for (i, line) in lines.iter().enumerate() {
        let stripped = line.trim_start();
        if stripped.starts_with(&format!("def {}(", method_name))
            || stripped.starts_with(&format!("async def {}(", method_name))
        {
            start = Some(i);
            base_indent = line.len() - stripped.len();
            break;
        }
    }

    let start = start?;
    let mut result = vec![lines[start].trim_end().to_string()];

    for line in &lines[start + 1..start + 1 + max_lines] {
        if line.trim().is_empty() {
            result.push(String::new());
            continue;
        }
        let cur_indent = line.len() - line.trim_start().len();
        if !line.trim().is_empty() && cur_indent <= base_indent {
            break;
        }
        result.push(line.trim_end().to_string());
    }

    Some(result.join("\n"))
}

fn extract_test_source(test_id: &str, repo_root: &str) -> Option<String> {
    let parts: Vec<&str> = test_id.split('.').collect();
    for end in (1..=parts.len()).rev() {
        let mut path = Path::new(repo_root).to_path_buf();
        for part in &parts[..end] {
            path = path.join(part);
        }
        let path_str = format!("{}.py", path.display());
        if Path::new(&path_str).exists() {
            let remainder = &parts[end..];
            let method_name = remainder.last().copied()?;
            if !method_name.starts_with("test") {
                return None;
            }
            return extract_method_source(&path_str, method_name, 20);
        }
    }
    None
}

fn find_recent_reports(reports_dir: &str, n: usize) -> Vec<String> {
    if !Path::new(reports_dir).is_dir() {
        return Vec::new();
    }
    let entries = match std::fs::read_dir(reports_dir) {
        Ok(e) => e,
        Err(_) => return Vec::new(),
    };
    let mut subdirs: Vec<String> = entries
        .filter_map(|e| e.ok())
        .filter(|e| e.path().is_dir())
        .map(|e| e.file_name().to_string_lossy().to_string())
        .collect();
    subdirs.sort_by(|a, b| b.cmp(a)); // newest-first

    let mut paths = Vec::new();
    for d in subdirs {
        let candidate = format!("{}/{}/report.json", reports_dir, d);
        if Path::new(&candidate).exists() {
            paths.push(candidate);
            if paths.len() >= n {
                break;
            }
        }
    }
    paths
}

fn aggregate_failures(
    report_paths: &[String],
) -> (Vec<serde_json::Value>, Vec<String>) {
    let mut seen_ids: HashSet<String> = HashSet::new();
    let mut failures: Vec<serde_json::Value> = Vec::new();
    let mut report_names: Vec<String> = Vec::new();

    for path in report_paths {
        let report = match prd::read_json(path) {
            Ok(v) => v,
            Err(_) => continue,
        };

        let report_dir = Path::new(path)
            .parent()
            .and_then(|p| p.file_name())
            .map(|n| n.to_string_lossy().to_string())
            .unwrap_or_default();

        let all_results = report
            .get("all_results")
            .and_then(|v| v.as_array())
            .cloned()
            .unwrap_or_default();

        let mut new_count = 0;
        for r in all_results {
            let status = r.get("status").and_then(|v| v.as_str()).unwrap_or("");
            if status != "FAIL" && status != "ERROR" {
                continue;
            }
            let tid = r
                .get("id")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            if !tid.is_empty() && seen_ids.insert(tid) {
                failures.push(r);
                new_count += 1;
            }
        }

        report_names.push(report_dir.clone());
        println!(
            "[synthesize] Report {}: {} new failures (running pool: {})",
            report_dir,
            new_count,
            failures.len()
        );
    }

    (failures, report_names)
}

fn result_to_story(result: &serde_json::Value, repo_root: &str) -> serde_json::Value {
    let test_id = result
        .get("id")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let name = result
        .get("name")
        .and_then(|v| v.as_str())
        .unwrap_or(&test_id)
        .to_string();
    let description = result
        .get("description")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let category = result
        .get("category")
        .and_then(|v| v.as_str())
        .unwrap_or("unit")
        .to_string();
    let status = result
        .get("status")
        .and_then(|v| v.as_str())
        .unwrap_or("FAIL")
        .to_string();
    let error = result.get("error").cloned().unwrap_or_default();

    let (category_hint, class_name, method_name) = parse_test_id(&test_id);
    let category_key = category_hint
        .split(':')
        .next()
        .unwrap_or("unit")
        .to_string();

    let priority = {
        let p = priority_from_category(&category);
        if p == "medium" {
            priority_from_category(&category_key)
        } else {
            p
        }
    };

    let readable = method_name
        .trim_start_matches("test_")
        .replace('_', " ")
        .trim()
        .to_string();
    let title = if !class_name.is_empty() {
        let cls_readable = class_name
            .replace("Test", "")
            .replace('_', " ")
            .trim()
            .to_string();
        format!("Fix failing test: {} — {}", cls_readable, readable)
    } else {
        format!("Fix failing test: {}", readable)
    };

    let mut ac = vec![serde_json::json!(format!(
        "Test `{}` passes without error.",
        test_id
    ))];
    if let Some(msg) = error.get("message").and_then(|v| v.as_str()) {
        let msg = msg[..msg.len().min(200)].replace('\n', " ");
        ac.push(serde_json::json!(format!("Root cause resolved: {}", msg)));
    }

    let mut tech_notes = vec![
        serde_json::json!(format!("Test category: {}", category)),
        serde_json::json!(format!("Test ID: {}", test_id)),
    ];
    if let Some(et) = error.get("type").and_then(|v| v.as_str()) {
        tech_notes.push(serde_json::json!(format!("Error type: {}", et)));
    }
    if !description.is_empty() {
        tech_notes.push(serde_json::json!(format!("Test description: {}", description)));
    }
    if !repo_root.is_empty() {
        if let Some(source) = extract_test_source(&test_id, repo_root) {
            tech_notes.push(serde_json::json!(format!(
                "Failing test source:\n```python\n{}\n```",
                source
            )));
        }
    }

    serde_json::json!({
        "title": title,
        "priority": priority,
        "description": format!(
            "Automated test `{}` is failing with status {}. This indicates a regression or missing implementation in the {} suite. {}",
            name, status, category, description
        ).trim().to_string(),
        "acceptanceCriteria": ac,
        "technicalNotes": tech_notes,
        "dependencies": [],
        "estimatedComplexity": "small",
        "_source": format!("test-synthesis:{}", test_id),
    })
}

pub fn run(
    prd_path: &str,
    reports_dir: &str,
    output: &str,
    recent_reports: usize,
    repo_root: &str,
    focus: &str,
) -> i32 {
    if !focus.is_empty() {
        println!(
            "[synthesize] Focus active: \"{}\" — matching stories tagged for priority boost",
            focus
        );
    }

    // Load existing titles from prd.json for dedup
    let mut existing_titles: Vec<String> = Vec::new();
    if Path::new(prd_path).exists() {
        let prd_val = match prd::read_json(prd_path) {
            Ok(v) => v,
            Err(e) => {
                eprintln!("[synthesize] ERROR: {}", e);
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
        existing_titles = prd_val["userStories"]
            .as_array()
            .map(|arr| {
                arr.iter()
                    .filter_map(|s| s.get("title").and_then(|v| v.as_str()))
                    .map(|s| s.to_string())
                    .collect()
            })
            .unwrap_or_default();
    }

    let report_paths = find_recent_reports(reports_dir, recent_reports);
    if report_paths.is_empty() {
        println!(
            "[synthesize] WARNING: No test reports found in {}/",
            reports_dir
        );
        if let Some(parent) = Path::new(output).parent() {
            let _ = std::fs::create_dir_all(parent);
        }
        let empty = serde_json::json!({ "stories": [] });
        match prd::write_json_atomic(output, &empty) {
            Ok(_) => {}
            Err(e) => {
                eprintln!("[synthesize] ERROR: {}", e);
                return 1;
            }
        }
        println!("[synthesize] Wrote 0 stories → {}", output);
        return 0;
    }

    let (failures, report_names) = aggregate_failures(&report_paths);
    println!(
        "[synthesize] Aggregated {} unique failures from {} report(s)",
        failures.len(),
        report_names.len()
    );

    let repo_root_abs = std::fs::canonicalize(repo_root)
        .map(|p| p.to_string_lossy().to_string())
        .unwrap_or_else(|_| repo_root.to_string());

    let mut candidates: Vec<serde_json::Value> = Vec::new();
    let mut seen_titles: Vec<String> = existing_titles.clone();

    for result in &failures {
        let mut story = result_to_story(result, &repo_root_abs);
        let title = story
            .get("title")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        if prd::is_duplicate(&title, &seen_titles, 0.6) {
            println!("[synthesize] Skipping duplicate: {}", title);
            continue;
        }
        if !focus.is_empty() {
            let focus_lower = focus.to_lowercase();
            let t = story.get("title").and_then(|v| v.as_str()).unwrap_or("");
            let d = story
                .get("description")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            let searchable = format!("{} {}", t, d).to_lowercase();
            story["_focusRelevant"] = serde_json::json!(searchable.contains(&focus_lower));
        }
        seen_titles.push(title);
        candidates.push(story);
    }

    println!(
        "[synthesize] Generated {} new story candidates from test failures",
        candidates.len()
    );

    if let Some(parent) = Path::new(output).parent() {
        let _ = std::fs::create_dir_all(parent);
    }

    let n_candidates = candidates.len();
    let output_val = serde_json::json!({ "stories": candidates });
    match prd::write_json_atomic(output, &output_val) {
        Ok(_) => {}
        Err(e) => {
            eprintln!("[synthesize] ERROR: {}", e);
            return 1;
        }
    }
    println!("[synthesize] Wrote {} stories → {}", n_candidates, output);
    0
}
