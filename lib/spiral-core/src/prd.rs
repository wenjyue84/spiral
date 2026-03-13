/// Shared PRD utilities: normalize, overlap, dedup, read/write JSON, validate.
use std::collections::{HashMap, HashSet};

/// Get story prefix from env (default: "US")
pub fn story_prefix() -> String {
    std::env::var("SPIRAL_STORY_PREFIX").unwrap_or_else(|_| "US".to_string())
}

/// Normalize text → set of lowercase alphanumeric tokens (mirrors Python normalize())
pub fn normalize(text: &str) -> HashSet<String> {
    let mut tokens = HashSet::new();
    let mut current = String::new();
    for ch in text.to_lowercase().chars() {
        if ch.is_ascii_alphanumeric() {
            current.push(ch);
        } else if !current.is_empty() {
            tokens.insert(current.clone());
            current.clear();
        }
    }
    if !current.is_empty() {
        tokens.insert(current);
    }
    tokens
}

/// Compute overlap ratio: |wa ∩ wb| / |wa|  (mirrors Python overlap_ratio())
pub fn overlap_ratio(a: &str, b: &str) -> f64 {
    let wa = normalize(a);
    let wb = normalize(b);
    if wa.is_empty() {
        return 0.0;
    }
    let intersection = wa.intersection(&wb).count();
    intersection as f64 / wa.len() as f64
}

/// Check duplicate by 60% word-overlap threshold (both directions, mirrors Python)
pub fn is_duplicate(candidate: &str, existing: &[String], threshold: f64) -> bool {
    for existing_title in existing {
        if overlap_ratio(candidate, existing_title) >= threshold {
            return true;
        }
        if overlap_ratio(existing_title, candidate) >= threshold {
            return true;
        }
    }
    false
}

/// Read and parse a JSON file
pub fn read_json(path: &str) -> Result<serde_json::Value, String> {
    let content = std::fs::read_to_string(path)
        .map_err(|e| format!("Failed to read {}: {}", path, e))?;
    serde_json::from_str(&content)
        .map_err(|e| format!("Invalid JSON in {}: {}", path, e))
}

/// Write JSON atomically (tmp → rename, with copy fallback for Windows cross-device)
pub fn write_json_atomic(path: &str, value: &serde_json::Value) -> Result<(), String> {
    let tmp = format!("{}.tmp", path);
    let content = serde_json::to_string_pretty(value)
        .map_err(|e| format!("Failed to serialize JSON: {}", e))?;
    let content = format!("{}\n", content);
    std::fs::write(&tmp, content.as_bytes())
        .map_err(|e| format!("Failed to write {}: {}", tmp, e))?;
    if std::fs::rename(&tmp, path).is_err() {
        // Fallback for Windows cross-device moves
        std::fs::copy(&tmp, path)
            .map_err(|e| format!("Failed to copy {} → {}: {}", tmp, path, e))?;
        let _ = std::fs::remove_file(&tmp);
    }
    Ok(())
}

fn type_name(v: &serde_json::Value) -> &'static str {
    match v {
        serde_json::Value::Null => "null",
        serde_json::Value::Bool(_) => "bool",
        serde_json::Value::Number(_) => "number",
        serde_json::Value::String(_) => "string",
        serde_json::Value::Array(_) => "array",
        serde_json::Value::Object(_) => "object",
    }
}

/// Validate a prd.json Value. Returns list of error strings (empty = valid).
/// Mirrors Python validate_prd() exactly.
pub fn validate_prd(prd: &serde_json::Value) -> Vec<String> {
    let mut errors: Vec<String> = Vec::new();

    if !prd.is_object() {
        errors.push("Root must be a JSON object".to_string());
        return errors;
    }

    // Required top-level keys
    for key in &["productName", "branchName", "userStories"] {
        if prd.get(key).is_none() {
            errors.push(format!("Missing required top-level key: {}", key));
        }
    }

    if let Some(pn) = prd.get("productName") {
        if !pn.is_string() {
            errors.push(format!("productName must be string, got {}", type_name(pn)));
        }
    }
    if let Some(bn) = prd.get("branchName") {
        if !bn.is_string() {
            errors.push(format!("branchName must be string, got {}", type_name(bn)));
        }
    }

    // userStories type check
    match prd.get("userStories") {
        Some(us) if !us.is_array() => {
            errors.push(format!("userStories must be a list, got {}", type_name(us)));
            return errors;
        }
        None => return errors,
        _ => {}
    }

    if let Some(ov) = prd.get("overview") {
        if !ov.is_string() {
            errors.push(format!("overview must be string, got {}", type_name(ov)));
        }
    }
    if let Some(goals) = prd.get("goals") {
        if !goals.is_array() {
            errors.push(format!("goals must be a list, got {}", type_name(goals)));
        }
    }

    let stories = prd["userStories"].as_array().unwrap();
    let valid_priorities: HashSet<&str> = ["critical", "high", "medium", "low"].iter().cloned().collect();
    let valid_complexities: HashSet<&str> = ["small", "medium", "large"].iter().cloned().collect();
    let id_re = regex::Regex::new(r"^(US|UT)-\d{3,4}$").unwrap();

    let mut seen_ids: HashMap<String, usize> = HashMap::new();
    let mut all_ids: HashSet<String> = HashSet::new();

    for (i, story) in stories.iter().enumerate() {
        let prefix = format!("userStories[{}]", i);

        if !story.is_object() {
            errors.push(format!("{}: must be an object, got {}", prefix, type_name(story)));
            continue;
        }

        // id
        let mut sid = String::new();
        match story.get("id") {
            None => errors.push(format!("{}: missing required field 'id'", prefix)),
            Some(v) if !v.is_string() => {
                errors.push(format!("{}: id must be string, got {}", prefix, type_name(v)));
            }
            Some(v) => {
                sid = v.as_str().unwrap().to_string();
                if !id_re.is_match(&sid) {
                    errors.push(format!("{}: id '{}' does not match pattern (US|UT)-NNN", prefix, sid));
                }
                if let Some(&first) = seen_ids.get(&sid) {
                    errors.push(format!(
                        "{}: duplicate story ID '{}' (first at index {})",
                        prefix, sid, first
                    ));
                }
                seen_ids.insert(sid.clone(), i);
                all_ids.insert(sid.clone());
            }
        }

        // title
        match story.get("title") {
            None => errors.push(format!("{}: missing required field 'title'", prefix)),
            Some(t) if !t.is_string() || t.as_str().unwrap().trim().is_empty() => {
                errors.push(format!("{}: title must be a non-empty string", prefix));
            }
            _ => {}
        }

        // passes
        match story.get("passes") {
            None => errors.push(format!("{}: missing required field 'passes'", prefix)),
            Some(p) if !p.is_boolean() => {
                errors.push(format!("{}: passes must be boolean, got {}", prefix, type_name(p)));
            }
            _ => {}
        }

        // priority
        match story.get("priority") {
            None => errors.push(format!("{}: missing required field 'priority'", prefix)),
            Some(pr) => match pr.as_str() {
                Some(s) if !valid_priorities.contains(s) => {
                    errors.push(format!(
                        "{}: invalid priority '{}' (valid: {})",
                        prefix,
                        s,
                        "critical, high, low, medium"
                    ));
                }
                None => errors.push(format!("{}: priority must be string", prefix)),
                _ => {}
            },
        }

        // description (optional)
        if let Some(d) = story.get("description") {
            if !d.is_string() && !d.is_null() {
                errors.push(format!("{}: description must be string", prefix));
            }
        }

        // acceptanceCriteria (required)
        match story.get("acceptanceCriteria") {
            None => errors.push(format!("{}: missing required field 'acceptanceCriteria'", prefix)),
            Some(ac) if !ac.is_array() => {
                errors.push(format!("{}: acceptanceCriteria must be a list", prefix));
            }
            _ => {}
        }

        // dependencies (required)
        match story.get("dependencies") {
            None => errors.push(format!("{}: missing required field 'dependencies'", prefix)),
            Some(d) if !d.is_array() => {
                errors.push(format!("{}: dependencies must be a list", prefix));
            }
            _ => {}
        }

        // estimatedComplexity (optional)
        if let Some(ec) = story.get("estimatedComplexity") {
            if let Some(s) = ec.as_str() {
                if !valid_complexities.contains(s) {
                    errors.push(format!(
                        "{}: invalid estimatedComplexity '{}' (valid: large, medium, small)",
                        prefix, s
                    ));
                }
            }
        }

        // technicalNotes (optional)
        if let Some(tn) = story.get("technicalNotes") {
            if !tn.is_array() && !tn.is_null() {
                errors.push(format!("{}: technicalNotes must be a list", prefix));
            }
        }

        // _decomposed (optional bool)
        if let Some(d) = story.get("_decomposed") {
            if !d.is_boolean() && !d.is_null() {
                errors.push(format!("{}: _decomposed must be boolean", prefix));
            }
        }

        // _decomposedFrom (optional string)
        if let Some(df) = story.get("_decomposedFrom") {
            if !df.is_string() && !df.is_null() {
                errors.push(format!("{}: _decomposedFrom must be string", prefix));
            }
        }

        // _decomposedInto (optional list)
        if let Some(di) = story.get("_decomposedInto") {
            if !di.is_array() && !di.is_null() {
                errors.push(format!("{}: _decomposedInto must be a list", prefix));
            }
        }

        // filesTouch (optional list)
        if let Some(ft) = story.get("filesTouch") {
            if !ft.is_array() && !ft.is_null() {
                errors.push(format!("{}: filesTouch must be a list", prefix));
            }
        }

        // isTestFix (optional bool)
        if let Some(itf) = story.get("isTestFix") {
            if !itf.is_boolean() && !itf.is_null() {
                errors.push(format!("{}: isTestFix must be boolean", prefix));
            }
        }
    }

    // Cross-story checks
    for (i, story) in stories.iter().enumerate() {
        if !story.is_object() {
            continue;
        }
        let sid = story.get("id").and_then(|v| v.as_str()).unwrap_or("");
        let prefix = format!("userStories[{}] ({})", i, sid);

        // Dependency references
        if let Some(deps) = story.get("dependencies").and_then(|d| d.as_array()) {
            for dep in deps {
                if let Some(dep_str) = dep.as_str() {
                    if dep_str == sid {
                        errors.push(format!(
                            "{}: self-referencing dependency '{}'",
                            prefix, dep_str
                        ));
                    } else if !all_ids.contains(dep_str) {
                        errors.push(format!(
                            "{}: dependency '{}' not found in userStories",
                            prefix, dep_str
                        ));
                    }
                }
            }
        }

        // _decomposedFrom
        if let Some(parent) = story.get("_decomposedFrom").and_then(|v| v.as_str()) {
            if !all_ids.contains(parent) {
                errors.push(format!(
                    "{}: _decomposedFrom '{}' not found in userStories",
                    prefix, parent
                ));
            }
        }

        // _decomposedInto
        if let Some(children) = story.get("_decomposedInto").and_then(|v| v.as_array()) {
            for child in children {
                if let Some(child_str) = child.as_str() {
                    if !all_ids.contains(child_str) {
                        errors.push(format!(
                            "{}: _decomposedInto '{}' not found in userStories",
                            prefix, child_str
                        ));
                    }
                }
            }
        }
    }

    errors
}

/// Kahn's topological sort — returns story IDs involved in cycles (empty = no cycles)
pub fn find_cycles(stories: &[serde_json::Value]) -> Vec<String> {
    let story_ids: HashSet<String> = stories
        .iter()
        .filter_map(|s| s.get("id").and_then(|v| v.as_str()))
        .map(|s| s.to_string())
        .collect();

    // Build adjacency: id → set of deps that exist in story_ids
    let mut deps: HashMap<String, HashSet<String>> = HashMap::new();
    for s in stories {
        if let Some(sid) = s.get("id").and_then(|v| v.as_str()) {
            let dep_set: HashSet<String> = s
                .get("dependencies")
                .and_then(|d| d.as_array())
                .map(|arr| {
                    arr.iter()
                        .filter_map(|d| d.as_str())
                        .filter(|d| story_ids.contains(*d))
                        .map(|s| s.to_string())
                        .collect()
                })
                .unwrap_or_default();
            deps.insert(sid.to_string(), dep_set);
        }
    }

    // Iterative Kahn's: repeatedly find and remove stories with all deps resolved
    let mut resolved: HashSet<String> = HashSet::new();
    loop {
        let batch: Vec<String> = story_ids
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
            break;
        }
        for sid in batch {
            resolved.insert(sid);
        }
    }

    let mut cycle_members: Vec<String> = story_ids.difference(&resolved).cloned().collect();
    cycle_members.sort();
    cycle_members
}
