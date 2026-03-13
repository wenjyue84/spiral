/// validate subcommand — ports prd_schema.py + check_dag.py
use crate::prd;

pub fn run(prd_path: &str, quiet: bool) -> i32 {
    if !std::path::Path::new(prd_path).exists() {
        eprintln!("[schema] ERROR: {} not found", prd_path);
        return 1;
    }

    let prd_val = match prd::read_json(prd_path) {
        Ok(v) => v,
        Err(e) => {
            eprintln!("[schema] ERROR: {}", e);
            return 1;
        }
    };

    // Schema validation
    let errors = prd::validate_prd(&prd_val);
    if !errors.is_empty() {
        eprintln!("[schema] {} — {} error(s):", prd_path, errors.len());
        for err in &errors {
            eprintln!("  - {}", err);
        }
        return 1;
    }

    // DAG cycle detection
    let stories = prd_val["userStories"].as_array().unwrap();
    let cycles = prd::find_cycles(stories);
    if !cycles.is_empty() {
        eprintln!(
            "[dag] ERROR: Dependency cycle detected involving {} stories:",
            cycles.len()
        );
        for sid in &cycles {
            let story = stories
                .iter()
                .find(|s| s.get("id").and_then(|v| v.as_str()) == Some(sid.as_str()));
            let title = story
                .and_then(|s| s.get("title").and_then(|v| v.as_str()))
                .unwrap_or("");
            let deps_str: Vec<&str> = story
                .and_then(|s| s.get("dependencies").and_then(|v| v.as_array()))
                .map(|arr| arr.iter().filter_map(|d| d.as_str()).collect())
                .unwrap_or_default();
            eprintln!("  - {}: {} (deps: {})", sid, title, deps_str.join(", "));
        }
        return 1;
    }

    if !quiet {
        let story_count = stories.len();
        println!("[schema] {} — valid ({} stories)", prd_path, story_count);
        println!("[dag] {} — no cycles ({} stories)", prd_path, story_count);
    }
    0
}
