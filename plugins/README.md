# SPIRAL Plugins

Plugins extend SPIRAL via hooks that fire at defined lifecycle points.
Each plugin lives in its own subdirectory with a `plugin.toml` manifest.

## Directory layout

```
plugins/
├── README.md              # This file
├── notify-slack/
│   ├── plugin.toml        # Manifest (required)
│   ├── post-story         # Hook script (executable)
│   └── run-completion     # Hook script (executable)
└── notify-whatsapp/
    ├── plugin.toml
    ├── post-story
    └── run-completion
```

## plugin.toml schema

```toml
[plugin]
# --- Required fields ---
name        = "plugin-name"      # unique identifier, matches directory name
version     = "1.0.0"            # semver
hooks       = ["post-story"]     # list of lifecycle hooks this plugin handles

# --- Recommended metadata (backward compatible) ---
description = "One-sentence description"
tags        = ["notification", "slack"]   # searchable tags
inputs      = ["story_id", "passes"]      # env vars / fields consumed
outputs     = ["slack_message_ts"]        # side-effects produced

# --- Optional ---
allowed_env = ["SLACK_WEBHOOK_URL"]       # env vars the plugin may read
```

### Required fields

| Field     | Type            | Description                           |
|-----------|-----------------|---------------------------------------|
| `name`    | string          | Unique plugin identifier              |
| `version` | string (semver) | Plugin version                        |
| `hooks`   | string[]        | Lifecycle hook names (see below)      |

### Optional metadata fields

| Field         | Type     | Description                                   |
|---------------|----------|-----------------------------------------------|
| `description` | string   | Human-readable summary                        |
| `tags`        | string[] | Searchable labels (e.g. `["notification"]`)   |
| `inputs`      | string[] | Data fields the plugin reads from SPIRAL      |
| `outputs`     | string[] | Side-effects or data the plugin produces      |
| `allowed_env` | string[] | Environment variables the plugin may access   |

### Backward compatibility

Older plugins without `description`, `tags`, `inputs`, or `outputs` are fully
supported. The `spiral skills list` command shows `?` or empty strings for
missing optional fields.

## Supported lifecycle hooks

| Hook             | When it fires                                  |
|------------------|------------------------------------------------|
| `post-story`     | After each story attempt (pass or fail)        |
| `run-completion` | After all iterations complete or time limit    |
| `pre-phase`      | Before a named SPIRAL phase begins             |
| `post-phase`     | After a named SPIRAL phase completes           |

## `spiral skills` CLI

```bash
# List all installed plugins with their metadata
spiral skills list

# Install a plugin from a tarball URL
spiral skills install https://example.com/my-plugin-1.0.0.tar.gz
```

### `spiral skills list` output

```
NAME                   VERSION    HOOKS                      DESCRIPTION
────────────────────────────────────────────────────────────────────────
notify-slack           1.0.0      post-story, run-completion Sends story lifecycle notifications...
notify-whatsapp        1.0.0      post-story, run-completion Sends story lifecycle notifications...
```

### `spiral skills install` validation

The `install` command enforces schema validation before extracting any files:

1. The tarball must contain a `plugin.toml`
2. `plugin.toml` must parse as valid TOML
3. Required fields (`name`, `version`, `hooks`) must be present and non-empty
4. Extraction occurs only after validation passes

Plugins without a valid manifest are **rejected** with a clear error message.
