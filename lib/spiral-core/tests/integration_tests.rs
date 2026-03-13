//! Integration tests for spiral-core subcommands.
//!
//! Each test spawns the compiled binary (CARGO_BIN_EXE_spiral-core) against
//! temporary files and asserts exit codes, stdout/stderr content, and
//! output JSON correctness.  Mirrors the Python pytest fixtures in tests/.

use std::fs;
use std::path::Path;
use std::process::{Command, Output};

// ── helpers ───────────────────────────────────────────────────────────────────

fn bin() -> std::path::PathBuf {
    // CARGO_BIN_EXE_spiral-core is set by cargo at test compile time.
    std::path::PathBuf::from(env!("CARGO_BIN_EXE_spiral-core"))
}

fn run(args: &[&str]) -> Output {
    Command::new(bin())
        .args(args)
        .output()
        .expect("failed to spawn spiral-core")
}

fn read_json(path: &Path) -> serde_json::Value {
    let content = fs::read_to_string(path).expect("failed to read JSON file");
    serde_json::from_str(&content).expect("invalid JSON")
}

fn write_json(path: &Path, value: &serde_json::Value) {
    fs::write(path, serde_json::to_string_pretty(value).unwrap()).unwrap();
}

/// Minimal valid PRD with 3 stories (mirrors conftest.valid_prd fixture)
fn minimal_prd() -> serde_json::Value {
    serde_json::json!({
        "productName": "TestApp",
        "branchName": "main",
        "userStories": [
            {
                "id": "US-001",
                "title": "Create hello world endpoint",
                "priority": "high",
                "description": "Simple HTTP endpoint returning a greeting",
                "acceptanceCriteria": ["GET /hello returns 200"],
                "dependencies": [],
                "passes": false
            },
            {
                "id": "US-002",
                "title": "Add personalized greeting parameter",
                "priority": "medium",
                "description": "Extend endpoint with name query param",
                "acceptanceCriteria": ["GET /hello?name=Alice returns 200"],
                "dependencies": ["US-001"],
                "passes": false
            },
            {
                "id": "US-003",
                "title": "Add health check endpoint",
                "priority": "low",
                "description": "Returns server status",
                "acceptanceCriteria": ["GET /health returns ok"],
                "dependencies": [],
                "passes": true
            }
        ]
    })
}

/// Empty candidates file ({"stories": []})
fn empty_candidates() -> serde_json::Value {
    serde_json::json!({ "stories": [] })
}

// ── validate ──────────────────────────────────────────────────────────────────

#[test]
fn validate_valid_example_prd() {
    let prd_path = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .join("templates/prd.example.json");
    assert!(prd_path.exists(), "templates/prd.example.json not found");

    let out = run(&["validate", prd_path.to_str().unwrap()]);
    assert_eq!(
        out.status.code(),
        Some(0),
        "validate should succeed on example PRD: {}",
        String::from_utf8_lossy(&out.stderr)
    );
    let stdout = String::from_utf8_lossy(&out.stdout);
    assert!(stdout.contains("[schema]"), "expected [schema] in output");
    assert!(stdout.contains("[dag]"), "expected [dag] in output");
}

#[test]
fn validate_valid_minimal_prd() {
    let tmp = tempdir();
    let prd_path = tmp.join("prd.json");
    write_json(&prd_path, &minimal_prd());

    let out = run(&["validate", prd_path.to_str().unwrap()]);
    assert_eq!(
        out.status.code(),
        Some(0),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
}

#[test]
fn validate_quiet_flag_suppresses_output() {
    let tmp = tempdir();
    let prd_path = tmp.join("prd.json");
    write_json(&prd_path, &minimal_prd());

    let out = run(&["validate", prd_path.to_str().unwrap(), "--quiet"]);
    assert_eq!(out.status.code(), Some(0));
    assert!(
        out.stdout.is_empty(),
        "quiet mode should produce no stdout"
    );
}

#[test]
fn validate_missing_product_name_fails() {
    let tmp = tempdir();
    let prd_path = tmp.join("prd.json");
    let mut prd = minimal_prd();
    prd.as_object_mut().unwrap().remove("productName");
    write_json(&prd_path, &prd);

    let out = run(&["validate", prd_path.to_str().unwrap()]);
    assert_eq!(out.status.code(), Some(1));
    let stderr = String::from_utf8_lossy(&out.stderr);
    assert!(stderr.contains("productName"), "error should mention productName");
}

#[test]
fn validate_duplicate_ids_fails() {
    let tmp = tempdir();
    let prd_path = tmp.join("prd.json");
    let mut prd = minimal_prd();
    prd["userStories"][1]["id"] = serde_json::json!("US-001"); // duplicate
    write_json(&prd_path, &prd);

    let out = run(&["validate", prd_path.to_str().unwrap()]);
    assert_eq!(out.status.code(), Some(1));
    let stderr = String::from_utf8_lossy(&out.stderr);
    assert!(stderr.contains("duplicate"), "error should mention duplicate");
}

#[test]
fn validate_cycle_detection_fails() {
    let tmp = tempdir();
    let prd_path = tmp.join("prd.json");
    let prd = serde_json::json!({
        "productName": "CycleTest",
        "branchName": "main",
        "userStories": [
            {
                "id": "US-001",
                "title": "Story A",
                "priority": "high",
                "description": "A",
                "acceptanceCriteria": ["done"],
                "dependencies": ["US-002"],
                "passes": false
            },
            {
                "id": "US-002",
                "title": "Story B",
                "priority": "high",
                "description": "B",
                "acceptanceCriteria": ["done"],
                "dependencies": ["US-001"],  // cycle: A→B, B→A
                "passes": false
            }
        ]
    });
    write_json(&prd_path, &prd);

    let out = run(&["validate", prd_path.to_str().unwrap()]);
    assert_eq!(out.status.code(), Some(1));
    let stderr = String::from_utf8_lossy(&out.stderr);
    assert!(stderr.contains("cycle") || stderr.contains("Cycle"), "error should mention cycle");
}

#[test]
fn validate_dangling_dependency_fails() {
    let tmp = tempdir();
    let prd_path = tmp.join("prd.json");
    let prd = serde_json::json!({
        "productName": "DanglingTest",
        "branchName": "main",
        "userStories": [
            {
                "id": "US-001",
                "title": "Story with bad dep",
                "priority": "high",
                "description": "References missing US-9999",
                "acceptanceCriteria": ["done"],
                "dependencies": ["US-9999"],
                "passes": false
            }
        ]
    });
    write_json(&prd_path, &prd);

    let out = run(&["validate", prd_path.to_str().unwrap()]);
    assert_eq!(out.status.code(), Some(1));
    let stderr = String::from_utf8_lossy(&out.stderr);
    assert!(stderr.contains("not found"), "error should mention 'not found'");
}

#[test]
fn validate_nonexistent_file_fails() {
    let out = run(&["validate", "/nonexistent/path/prd.json"]);
    assert_eq!(out.status.code(), Some(1));
}

#[test]
fn validate_invalid_json_fails() {
    let tmp = tempdir();
    let prd_path = tmp.join("prd.json");
    fs::write(&prd_path, b"{ not valid json }").unwrap();

    let out = run(&["validate", prd_path.to_str().unwrap()]);
    assert_eq!(out.status.code(), Some(1));
}

#[test]
fn validate_invalid_priority_fails() {
    let tmp = tempdir();
    let prd_path = tmp.join("prd.json");
    let mut prd = minimal_prd();
    prd["userStories"][0]["priority"] = serde_json::json!("urgent");
    write_json(&prd_path, &prd);

    let out = run(&["validate", prd_path.to_str().unwrap()]);
    assert_eq!(out.status.code(), Some(1));
    let stderr = String::from_utf8_lossy(&out.stderr);
    assert!(stderr.contains("urgent"));
}

// ── merge ─────────────────────────────────────────────────────────────────────

#[test]
fn merge_empty_candidates_leaves_prd_unchanged() {
    let tmp = tempdir();
    let prd_path = tmp.join("prd.json");
    let research_path = tmp.join("research.json");
    let tests_path = tmp.join("tests.json");
    write_json(&prd_path, &minimal_prd());
    write_json(&research_path, &empty_candidates());
    write_json(&tests_path, &empty_candidates());

    let out = run(&[
        "merge",
        "--prd", prd_path.to_str().unwrap(),
        "--research", research_path.to_str().unwrap(),
        "--test-stories", tests_path.to_str().unwrap(),
    ]);
    assert_eq!(
        out.status.code(),
        Some(0),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );

    let result = read_json(&prd_path);
    // 3 original stories should still be there
    assert_eq!(result["userStories"].as_array().unwrap().len(), 3);
}

#[test]
fn merge_adds_new_research_stories() {
    let tmp = tempdir();
    let prd_path = tmp.join("prd.json");
    let research_path = tmp.join("research.json");
    let tests_path = tmp.join("tests.json");

    write_json(&prd_path, &minimal_prd());
    write_json(&research_path, &serde_json::json!({
        "stories": [
            {
                "title": "Implement user authentication flow",
                "priority": "high",
                "description": "Add login and logout endpoints",
                "acceptanceCriteria": ["POST /login returns JWT token"],
                "dependencies": [],
                "estimatedComplexity": "medium"
            }
        ]
    }));
    write_json(&tests_path, &empty_candidates());

    let out = run(&[
        "merge",
        "--prd", prd_path.to_str().unwrap(),
        "--research", research_path.to_str().unwrap(),
        "--test-stories", tests_path.to_str().unwrap(),
    ]);
    assert_eq!(
        out.status.code(),
        Some(0),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );

    let result = read_json(&prd_path);
    let stories = result["userStories"].as_array().unwrap();
    assert_eq!(stories.len(), 4, "new research story should be added");

    // The new story should have passes=false
    let new_story = stories.iter().find(|s| {
        s["title"]
            .as_str()
            .unwrap_or("")
            .contains("authentication")
    });
    assert!(new_story.is_some(), "new story should be in PRD");
    assert_eq!(new_story.unwrap()["passes"], false);
}

#[test]
fn merge_deduplicates_near_identical_titles() {
    let tmp = tempdir();
    let prd_path = tmp.join("prd.json");
    let research_path = tmp.join("research.json");
    let tests_path = tmp.join("tests.json");

    write_json(&prd_path, &minimal_prd());
    // Slightly rephrased version of "Create hello world endpoint" — should be deduped
    write_json(&research_path, &serde_json::json!({
        "stories": [
            {
                "title": "Create hello world endpoint implementation",
                "priority": "high",
                "description": "Creates the hello world endpoint",
                "acceptanceCriteria": ["GET /hello works"],
                "dependencies": []
            }
        ]
    }));
    write_json(&tests_path, &empty_candidates());

    let out = run(&[
        "merge",
        "--prd", prd_path.to_str().unwrap(),
        "--research", research_path.to_str().unwrap(),
        "--test-stories", tests_path.to_str().unwrap(),
    ]);
    assert_eq!(out.status.code(), Some(0));

    let result = read_json(&prd_path);
    // Should still be 3 stories (duplicate rejected)
    assert_eq!(
        result["userStories"].as_array().unwrap().len(),
        3,
        "near-duplicate title should not be added"
    );
}

#[test]
fn merge_preserves_existing_story_ids() {
    let tmp = tempdir();
    let prd_path = tmp.join("prd.json");
    let research_path = tmp.join("research.json");
    let tests_path = tmp.join("tests.json");

    write_json(&prd_path, &minimal_prd());
    write_json(&research_path, &serde_json::json!({
        "stories": [
            {
                "title": "Completely new feature X",
                "priority": "low",
                "description": "Something entirely new",
                "acceptanceCriteria": ["works"],
                "dependencies": []
            }
        ]
    }));
    write_json(&tests_path, &empty_candidates());

    run(&[
        "merge",
        "--prd", prd_path.to_str().unwrap(),
        "--research", research_path.to_str().unwrap(),
        "--test-stories", tests_path.to_str().unwrap(),
    ]);

    let result = read_json(&prd_path);
    let stories = result["userStories"].as_array().unwrap();
    // Original IDs must be preserved
    assert_eq!(stories[0]["id"], "US-001");
    assert_eq!(stories[1]["id"], "US-002");
    assert_eq!(stories[2]["id"], "US-003");
    // New story gets next ID
    assert_eq!(stories[3]["id"], "US-004");
}

#[test]
fn merge_max_new_cap_respected() {
    let tmp = tempdir();
    let prd_path = tmp.join("prd.json");
    let research_path = tmp.join("research.json");
    let tests_path = tmp.join("tests.json");
    let overflow_path = tmp.join("overflow.json");

    write_json(&prd_path, &minimal_prd());
    // Add 5 new unique stories, but cap at max_new=2
    write_json(&research_path, &serde_json::json!({
        "stories": [
            {"title": "Feature Alpha unique one", "priority": "high", "description": "desc", "acceptanceCriteria": ["done"], "dependencies": []},
            {"title": "Feature Beta unique two", "priority": "high", "description": "desc", "acceptanceCriteria": ["done"], "dependencies": []},
            {"title": "Feature Gamma unique three", "priority": "medium", "description": "desc", "acceptanceCriteria": ["done"], "dependencies": []},
            {"title": "Feature Delta unique four", "priority": "medium", "description": "desc", "acceptanceCriteria": ["done"], "dependencies": []},
            {"title": "Feature Epsilon unique five", "priority": "low", "description": "desc", "acceptanceCriteria": ["done"], "dependencies": []}
        ]
    }));
    write_json(&tests_path, &empty_candidates());

    let out = run(&[
        "merge",
        "--prd", prd_path.to_str().unwrap(),
        "--research", research_path.to_str().unwrap(),
        "--test-stories", tests_path.to_str().unwrap(),
        "--max-new", "2",
        "--overflow-out", overflow_path.to_str().unwrap(),
    ]);
    assert_eq!(out.status.code(), Some(0));

    let result = read_json(&prd_path);
    let n = result["userStories"].as_array().unwrap().len();
    assert_eq!(n, 5, "3 original + 2 new (capped by --max-new 2)");

    // Overflow file should contain the remaining stories
    assert!(overflow_path.exists(), "overflow file should be created");
    let overflow = read_json(&overflow_path);
    let overflow_stories = overflow["stories"].as_array().unwrap();
    assert!(!overflow_stories.is_empty(), "overflow file should have stories");
}

// ── partition ─────────────────────────────────────────────────────────────────

#[test]
fn partition_list_waves_outputs_wave_count() {
    let tmp = tempdir();
    let prd_path = tmp.join("prd.json");
    write_json(&prd_path, &minimal_prd());

    let out = run(&[
        "partition",
        "--prd", prd_path.to_str().unwrap(),
        "--workers", "2",
        "--outdir", tmp.to_str().unwrap(),
        "--list-waves",
    ]);
    assert_eq!(out.status.code(), Some(0));
    let stdout = String::from_utf8_lossy(&out.stdout);
    // Should print a number (the number of topological levels)
    let trimmed = stdout.trim();
    assert!(
        trimmed.parse::<usize>().is_ok(),
        "--list-waves should print a number, got: '{}'",
        trimmed
    );
}

#[test]
fn partition_wave_count_outputs_pending_count() {
    let tmp = tempdir();
    let prd_path = tmp.join("prd.json");
    write_json(&prd_path, &minimal_prd());

    let out = run(&[
        "partition",
        "--prd", prd_path.to_str().unwrap(),
        "--workers", "2",
        "--outdir", tmp.to_str().unwrap(),
        "--wave-count", "0",
    ]);
    assert_eq!(out.status.code(), Some(0));
    let stdout = String::from_utf8_lossy(&out.stdout);
    let trimmed = stdout.trim();
    assert!(
        trimmed.parse::<usize>().is_ok(),
        "--wave-count should print a number, got: '{}'",
        trimmed
    );
}

#[test]
fn partition_creates_worker_files() {
    let tmp = tempdir();
    let prd_path = tmp.join("prd.json");
    write_json(&prd_path, &minimal_prd());

    let out = run(&[
        "partition",
        "--prd", prd_path.to_str().unwrap(),
        "--workers", "2",
        "--outdir", tmp.to_str().unwrap(),
        "--wave-level", "0",
    ]);
    assert_eq!(
        out.status.code(),
        Some(0),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );

    // Should create worker_1.json and worker_2.json (or at least worker_1.json)
    let w1 = tmp.join("worker_1.json");
    assert!(w1.exists(), "worker_1.json should be created");

    // Each worker file should be a valid PRD
    let w1_prd = read_json(&w1);
    assert!(w1_prd["userStories"].is_array(), "worker file should have userStories array");
}

#[test]
fn partition_worker_files_contain_valid_stories() {
    let tmp = tempdir();
    let prd_path = tmp.join("prd.json");
    // 4-story PRD with dependencies
    let prd = serde_json::json!({
        "productName": "PartitionTest",
        "branchName": "main",
        "userStories": [
            {
                "id": "US-001", "title": "Story one",
                "priority": "critical", "description": "d",
                "acceptanceCriteria": ["done"], "dependencies": [],
                "passes": false
            },
            {
                "id": "US-002", "title": "Story two",
                "priority": "high", "description": "d",
                "acceptanceCriteria": ["done"], "dependencies": ["US-001"],
                "passes": false
            },
            {
                "id": "US-003", "title": "Story three",
                "priority": "medium", "description": "d",
                "acceptanceCriteria": ["done"], "dependencies": [],
                "passes": false
            },
            {
                "id": "US-004", "title": "Story four",
                "priority": "low", "description": "d",
                "acceptanceCriteria": ["done"], "dependencies": ["US-003"],
                "passes": false
            }
        ]
    });
    write_json(&prd_path, &prd);

    // Partition wave 0 into 2 workers
    let out = run(&[
        "partition",
        "--prd", prd_path.to_str().unwrap(),
        "--workers", "2",
        "--outdir", tmp.to_str().unwrap(),
        "--wave-level", "0",
    ]);
    assert_eq!(out.status.code(), Some(0));

    // Collect all stories across worker files
    let mut all_ids: Vec<String> = Vec::new();
    for i in 1..=2 {
        let wpath = tmp.join(&format!("worker_{}.json", i));
        if wpath.exists() {
            let w_prd = read_json(&wpath);
            if let Some(stories) = w_prd["userStories"].as_array() {
                for s in stories {
                    if let Some(id) = s["id"].as_str() {
                        all_ids.push(id.to_string());
                    }
                }
            }
        }
    }

    // Wave 0 = US-001 and US-003 (no deps, not passed)
    assert!(all_ids.contains(&"US-001".to_string()), "US-001 should be in wave 0");
    assert!(all_ids.contains(&"US-003".to_string()), "US-003 should be in wave 0");
    // US-002 and US-004 depend on wave 0 stories, so should NOT be in wave 0
    assert!(!all_ids.contains(&"US-002".to_string()), "US-002 should not be in wave 0 (has dep)");
    assert!(!all_ids.contains(&"US-004".to_string()), "US-004 should not be in wave 0 (has dep)");
}

// ── check-done ────────────────────────────────────────────────────────────────

#[test]
fn check_done_all_stories_passed_returns_complete() {
    let tmp = tempdir();
    let prd_path = tmp.join("prd.json");

    // All stories passed
    let prd = serde_json::json!({
        "productName": "DoneApp",
        "branchName": "main",
        "userStories": [
            {
                "id": "US-001", "title": "Story A",
                "priority": "high", "description": "d",
                "acceptanceCriteria": ["done"], "dependencies": [],
                "passes": true
            },
            {
                "id": "US-002", "title": "Story B",
                "priority": "high", "description": "d",
                "acceptanceCriteria": ["done"], "dependencies": [],
                "passes": true
            }
        ]
    });
    write_json(&prd_path, &prd);

    // Create a fake test-reports dir with a recent passing report
    let reports_dir = tmp.join("test-reports");
    let run_dir = reports_dir.join("20241201_120000_abc");
    fs::create_dir_all(&run_dir).unwrap();
    let report = serde_json::json!({
        "summary": {
            "failed": 0,
            "errored": 0,
            "passed": 2,
            "total": 2,
            "pass_rate": 1.0
        }
    });
    write_json(&run_dir.join("report.json"), &report);

    let out = run(&[
        "check-done",
        "--prd", prd_path.to_str().unwrap(),
        "--reports-dir", reports_dir.to_str().unwrap(),
    ]);

    // SPIRAL COMPLETE → exit 0
    assert_eq!(
        out.status.code(),
        Some(0),
        "all stories passed → SPIRAL COMPLETE: {}",
        String::from_utf8_lossy(&out.stdout)
    );
    let stdout = String::from_utf8_lossy(&out.stdout);
    assert!(
        stdout.contains("COMPLETE"),
        "expected COMPLETE in output, got: {}",
        stdout
    );
}

#[test]
fn check_done_pending_stories_returns_incomplete() {
    let tmp = tempdir();
    let prd_path = tmp.join("prd.json");
    write_json(&prd_path, &minimal_prd()); // has 2 pending, 1 passed

    let reports_dir = tmp.join("test-reports");
    let run_dir = reports_dir.join("20241201_120000_abc");
    fs::create_dir_all(&run_dir).unwrap();
    let report = serde_json::json!({
        "summary": {
            "failed": 2,
            "errored": 0,
            "passed": 1,
            "total": 3,
            "pass_rate": 0.333
        }
    });
    write_json(&run_dir.join("report.json"), &report);

    let out = run(&[
        "check-done",
        "--prd", prd_path.to_str().unwrap(),
        "--reports-dir", reports_dir.to_str().unwrap(),
    ]);

    // INCOMPLETE → exit 1
    assert_eq!(
        out.status.code(),
        Some(1),
        "pending stories → exit 1: {}",
        String::from_utf8_lossy(&out.stdout)
    );
    let stdout = String::from_utf8_lossy(&out.stdout);
    assert!(
        stdout.contains("INCOMPLETE"),
        "expected INCOMPLETE in output, got: {}",
        stdout
    );
}

#[test]
fn check_done_no_reports_dir_exits_nonzero() {
    let tmp = tempdir();
    let prd_path = tmp.join("prd.json");
    write_json(&prd_path, &minimal_prd());

    let out = run(&[
        "check-done",
        "--prd", prd_path.to_str().unwrap(),
        "--reports-dir", tmp.join("nonexistent-reports").to_str().unwrap(),
    ]);
    // No reports → cannot determine pass/fail → non-zero
    assert_ne!(out.status.code(), Some(0));
}

// ── merge-workers ─────────────────────────────────────────────────────────────

#[test]
fn merge_workers_promotes_passed_stories() {
    let tmp = tempdir();
    let main_prd_path = tmp.join("prd.json");
    let worker_prd_path = tmp.join("worker_1.json");

    write_json(&main_prd_path, &minimal_prd());

    // Worker reports US-001 as passed
    let worker_prd = serde_json::json!({
        "productName": "TestApp",
        "branchName": "main",
        "userStories": [
            {
                "id": "US-001", "title": "Create hello world endpoint",
                "priority": "high", "description": "Simple HTTP endpoint",
                "acceptanceCriteria": ["GET /hello returns 200"], "dependencies": [],
                "passes": true
            }
        ]
    });
    write_json(&worker_prd_path, &worker_prd);

    let out = run(&[
        "merge-workers",
        "--main", main_prd_path.to_str().unwrap(),
        "--workers", worker_prd_path.to_str().unwrap(),
    ]);
    assert_eq!(
        out.status.code(),
        Some(0),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );

    let result = read_json(&main_prd_path);
    let stories = result["userStories"].as_array().unwrap();
    let us001 = stories.iter().find(|s| s["id"] == "US-001").unwrap();
    assert_eq!(
        us001["passes"], true,
        "US-001 should be promoted to passes=true"
    );
    // US-002 and US-003 untouched
    let us002 = stories.iter().find(|s| s["id"] == "US-002").unwrap();
    assert_eq!(us002["passes"], false);
}

#[test]
fn merge_workers_handles_multiple_workers() {
    let tmp = tempdir();
    let main_prd_path = tmp.join("prd.json");

    write_json(&main_prd_path, &minimal_prd());

    // Worker 1 passes US-001
    let w1_path = tmp.join("worker_1.json");
    write_json(&w1_path, &serde_json::json!({
        "productName": "TestApp", "branchName": "main",
        "userStories": [
            {
                "id": "US-001", "title": "hello", "priority": "high",
                "description": "d", "acceptanceCriteria": ["done"],
                "dependencies": [], "passes": true
            }
        ]
    }));

    // Worker 2 passes US-002 — worker PRDs include all stories needed for validation
    let w2_path = tmp.join("worker_2.json");
    write_json(&w2_path, &serde_json::json!({
        "productName": "TestApp", "branchName": "main",
        "userStories": [
            {
                "id": "US-001", "title": "hello", "priority": "high",
                "description": "d", "acceptanceCriteria": ["done"],
                "dependencies": [], "passes": true
            },
            {
                "id": "US-002", "title": "greeting", "priority": "medium",
                "description": "d", "acceptanceCriteria": ["done"],
                "dependencies": ["US-001"], "passes": true
            }
        ]
    }));

    let out = run(&[
        "merge-workers",
        "--main", main_prd_path.to_str().unwrap(),
        "--workers", w1_path.to_str().unwrap(), w2_path.to_str().unwrap(),
    ]);
    assert_eq!(out.status.code(), Some(0));

    let result = read_json(&main_prd_path);
    let stories = result["userStories"].as_array().unwrap();

    let us001 = stories.iter().find(|s| s["id"] == "US-001").unwrap();
    let us002 = stories.iter().find(|s| s["id"] == "US-002").unwrap();
    assert_eq!(us001["passes"], true, "US-001 should pass");
    assert_eq!(us002["passes"], true, "US-002 should pass");
}

#[test]
fn merge_workers_missing_worker_file_warns_continues() {
    let tmp = tempdir();
    let main_prd_path = tmp.join("prd.json");
    write_json(&main_prd_path, &minimal_prd());

    // Worker file doesn't exist — should warn but not fail
    let out = run(&[
        "merge-workers",
        "--main", main_prd_path.to_str().unwrap(),
        "--workers", tmp.join("nonexistent_worker.json").to_str().unwrap(),
    ]);
    assert_eq!(
        out.status.code(),
        Some(0),
        "missing worker file should warn, not fail: {}",
        String::from_utf8_lossy(&out.stderr)
    );
}

// ── parity: Rust validate matches Python prd_schema + check_dag ───────────────

#[test]
fn parity_validate_vs_python_on_example_prd() {
    // Run Rust validate and Python prd_schema.py + check_dag.py on the same input.
    // Both should exit 0 for the example PRD.
    let prd_path = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .join("templates/prd.example.json");

    // Rust
    let rust_out = run(&["validate", prd_path.to_str().unwrap()]);
    let rust_ok = rust_out.status.code() == Some(0);

    // Python (skip gracefully if python3 not available)
    let schema_py = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .join("lib/prd_schema.py");

    if schema_py.exists() {
        if let Ok(py_out) = Command::new("python3")
            .args([
                schema_py.to_str().unwrap(),
                prd_path.to_str().unwrap(),
            ])
            .output()
        {
            let py_ok = py_out.status.code() == Some(0);
            assert_eq!(
                rust_ok, py_ok,
                "Rust and Python validate should agree on example PRD"
            );
        }
    } else {
        // Python fallback: still assert Rust passes
        assert!(rust_ok, "Rust validate should pass on example PRD");
    }
}

#[test]
fn parity_validate_invalid_prd_both_fail() {
    let tmp = tempdir();
    let prd_path = tmp.join("prd.json");
    let mut prd = minimal_prd();
    prd["userStories"][0]["priority"] = serde_json::json!("INVALID");
    write_json(&prd_path, &prd);

    // Rust should fail
    let rust_out = run(&["validate", prd_path.to_str().unwrap()]);
    assert_eq!(rust_out.status.code(), Some(1), "Rust should reject invalid priority");

    // Python should also fail (if available)
    let schema_py = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .join("lib/prd_schema.py");

    if schema_py.exists() {
        if let Ok(py_out) = Command::new("python3")
            .args([
                schema_py.to_str().unwrap(),
                prd_path.to_str().unwrap(),
            ])
            .output()
        {
            assert_ne!(
                py_out.status.code(),
                Some(0),
                "Python should also reject invalid priority"
            );
        }
    }
}

// ── utilities ─────────────────────────────────────────────────────────────────

/// Create a temporary directory that is cleaned up when dropped.
fn tempdir() -> TempDir {
    TempDir::new()
}

struct TempDir(std::path::PathBuf);

impl TempDir {
    fn new() -> Self {
        let path = std::env::temp_dir().join(format!(
            "spiral_test_{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .subsec_nanos()
        ));
        fs::create_dir_all(&path).expect("failed to create temp dir");
        TempDir(path)
    }

    fn join(&self, name: &str) -> std::path::PathBuf {
        self.0.join(name)
    }

    fn to_str(&self) -> Option<&str> {
        self.0.to_str()
    }
}

impl Drop for TempDir {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

impl std::ops::Deref for TempDir {
    type Target = std::path::PathBuf;
    fn deref(&self) -> &Self::Target {
        &self.0
    }
}
