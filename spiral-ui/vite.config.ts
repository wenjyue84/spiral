import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import fs from 'node:fs'
import path from 'node:path'
import os from 'node:os'
import { spawnSync } from 'node:child_process'
import type { IncomingMessage, ServerResponse } from 'node:http'
import { handleAnalytics } from './src/server/analyticsApi'

// ── Spiral API plugin ──────────────────────────────────────────────────────────
// Provides endpoints for config saving and the project dashboard:
//   GET  /api/project                → { projectRoot }
//   POST /api/save-config            → writes spiral.config.sh
//   GET  /api/projects               → list of registered projects
//   POST /api/register-project       → register { name, root }
//   GET  /api/project-live?name=X    → full live data for dashboard

const PROJECTS_FILE = path.join(os.homedir(), '.spiral', 'ui-projects.json');

/** Normalize MSYS2/Git-Bash paths (/c/Users/...) to Windows paths (C:/Users/...). */
function normalizePath(p: string): string {
  return p.replace(/^\/([a-zA-Z])\//, (_: string, d: string) => `${d.toUpperCase()}:/`);
}

function readRegistry(): Record<string, string> {
  try {
    if (fs.existsSync(PROJECTS_FILE)) {
      const raw = JSON.parse(fs.readFileSync(PROJECTS_FILE, 'utf8')) as Record<string, string>;
      // Normalize any MSYS2-style paths so Node.js fs calls resolve correctly on Windows
      return Object.fromEntries(Object.entries(raw).map(([k, v]) => [k, normalizePath(v)]));
    }
  } catch { /* ignore */ }
  return {};
}

function writeRegistry(reg: Record<string, string>) {
  const dir = path.dirname(PROJECTS_FILE);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(PROJECTS_FILE, JSON.stringify(reg, null, 2), 'utf8');
}

/** Parse `spiral.config.sh` — extract `export KEY=VALUE` lines. */
function parseConfigSh(configPath: string): Record<string, string> {
  if (!fs.existsSync(configPath)) return {};
  const text = fs.readFileSync(configPath, 'utf8');
  const result: Record<string, string> = {};
  for (const line of text.split('\n')) {
    const m = line.match(/^\s*(?:export\s+)?([A-Z_][A-Z0-9_]*)=["']?([^"'\n]*)["']?\s*(?:#.*)?$/);
    if (m) result[m[1]] = m[2].trim();
  }
  return result;
}

/** Resolve constitution path from config or fall back to .specify/memory/constitution.md */
function readConstitution(projectRoot: string, config: Record<string, string>): string {
  const candidates = [
    config['SPIRAL_SPECKIT_CONSTITUTION'] ? path.join(projectRoot, config['SPIRAL_SPECKIT_CONSTITUTION']) : '',
    path.join(projectRoot, '.specify', 'memory', 'constitution.md'),
    path.join(projectRoot, 'constitution.md'),
  ].filter(Boolean);

  for (const p of candidates) {
    if (fs.existsSync(p)) {
      try { return fs.readFileSync(p, 'utf8'); } catch { /* ignore */ }
    }
  }
  return '';
}

/** Query git log for the latest commit timestamp per story ID. Returns a map of storyId → ISO timestamp. */
function getStoryCompletionTimes(projectRoot: string): Record<string, string> {
  const result: Record<string, string> = {};
  try {
    const proc = spawnSync('git', ['log', '--all', '--format=%aI|%s', '--no-merges'], {
      cwd: projectRoot, encoding: 'utf8', timeout: 10_000, stdio: ['pipe', 'pipe', 'pipe'],
    });
    if (proc.status !== 0 || !proc.stdout) return result;
    for (const line of proc.stdout.split('\n')) {
      const sep = line.indexOf('|');
      if (sep < 0) continue;
      const ts = line.substring(0, sep).trim();
      const subject = line.substring(sep + 1);
      const m = subject.match(/US-\d+|UT-\d+/);
      if (m && !result[m[0]]) {
        // git log is newest-first, so first match = latest commit for that story
        result[m[0]] = ts;
      }
    }
  } catch { /* git not available or not a repo */ }
  return result;
}

/** Read last N lines of a text file. */
function tailFile(filePath: string, lines = 200): string {
  if (!fs.existsSync(filePath)) return '';
  try {
    const text = fs.readFileSync(filePath, 'utf8');
    const all = text.split('\n');
    return all.slice(Math.max(0, all.length - lines)).join('\n');
  } catch { return ''; }
}

/** Read JSONL file and return parsed lines (silently skip bad lines). */
function readJsonl(filePath: string): unknown[] {
  if (!fs.existsSync(filePath)) return [];
  try {
    return fs.readFileSync(filePath, 'utf8')
      .split('\n')
      .filter(Boolean)
      .flatMap(line => { try { return [JSON.parse(line)]; } catch { return []; } });
  } catch { return []; }
}

function spiralApiPlugin() {
  const PROJECT_ROOT = process.env.SPIRAL_PROJECT_ROOT || process.cwd();

  return {
    name: 'spiral-api',
    configureServer(server: { middlewares: { use: (path: string, fn: (req: IncomingMessage, res: ServerResponse, next: () => void) => void) => void } }) {

      // ── GET /api/project — returns current project root ─────────────────
      server.middlewares.use('/api/project', (req, res, next) => {
        if (req.method !== 'GET') { next(); return; }
        res.setHeader('Content-Type', 'application/json');
        res.setHeader('Access-Control-Allow-Origin', '*');
        res.end(JSON.stringify({ projectRoot: PROJECT_ROOT }));
      });

      // ── POST /api/save-config — writes spiral.config.sh ─────────────────
      server.middlewares.use('/api/save-config', (req, res, next) => {
        if (req.method !== 'POST') { next(); return; }
        let body = '';
        req.on('data', (chunk: Buffer) => { body += chunk.toString(); });
        req.on('end', () => {
          try {
            const { content, name: saveProjectName } = JSON.parse(body) as { content: string; name?: string };
            const saveRoot = saveProjectName ? (readRegistry()[saveProjectName] ?? PROJECT_ROOT) : PROJECT_ROOT;
            const configPath = path.join(saveRoot, 'spiral.config.sh');
            fs.writeFileSync(configPath, content, 'utf8');
            res.setHeader('Content-Type', 'application/json');
            res.setHeader('Access-Control-Allow-Origin', '*');
            res.end(JSON.stringify({ ok: true, path: configPath }));
          } catch (e) {
            res.statusCode = 500;
            res.setHeader('Content-Type', 'application/json');
            res.end(JSON.stringify({ error: String(e) }));
          }
        });
      });

      // ── POST /api/save-constitution — writes constitution.md ─────────────
      server.middlewares.use('/api/save-constitution', (req, res, next) => {
        if (req.method !== 'POST') { next(); return; }
        let body = '';
        req.on('data', (chunk: Buffer) => { body += chunk.toString(); });
        req.on('end', () => {
          try {
            const { content, name: saveProjectName } = JSON.parse(body) as { content: string; name?: string };
            const saveRoot = saveProjectName ? (readRegistry()[saveProjectName] ?? PROJECT_ROOT) : PROJECT_ROOT;
            const saveConfig = parseConfigSh(path.join(saveRoot, 'spiral.config.sh'));
            const candidates = [
              saveConfig['SPIRAL_SPECKIT_CONSTITUTION'] ? path.join(saveRoot, saveConfig['SPIRAL_SPECKIT_CONSTITUTION']) : '',
              path.join(saveRoot, '.specify', 'memory', 'constitution.md'),
              path.join(saveRoot, 'constitution.md'),
            ].filter(Boolean);
            // Use first existing path, or fallback to default
            let savePath = candidates.find(p => fs.existsSync(p)) ?? candidates[1];
            const dir = path.dirname(savePath);
            if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
            fs.writeFileSync(savePath, content, 'utf8');
            res.setHeader('Content-Type', 'application/json');
            res.setHeader('Access-Control-Allow-Origin', '*');
            res.end(JSON.stringify({ ok: true, path: savePath }));
          } catch (e) {
            res.statusCode = 500;
            res.setHeader('Content-Type', 'application/json');
            res.end(JSON.stringify({ error: String(e) }));
          }
        });
      });

      // ── GET /api/skills — list skill .md files from ralph/skills/ ──────────
      server.middlewares.use('/api/skills', (req, res, next) => {
        if (req.method !== 'GET') { next(); return; }
        try {
          const url = new URL(req.url ?? '/', 'http://localhost');
          const projName = url.searchParams.get('name');
          const saveRoot = projName ? (readRegistry()[projName] ?? PROJECT_ROOT) : PROJECT_ROOT;
          const skillsDir = path.join(saveRoot, 'ralph', 'skills');
          let skills: { name: string }[] = [];
          if (fs.existsSync(skillsDir)) {
            skills = fs.readdirSync(skillsDir)
              .filter((f: string) => f.endsWith('.md'))
              .map((f: string) => ({ name: f.replace(/\.md$/, '') }));
          }
          res.setHeader('Content-Type', 'application/json');
          res.setHeader('Access-Control-Allow-Origin', '*');
          res.end(JSON.stringify({ skills }));
        } catch (e) {
          res.statusCode = 500;
          res.setHeader('Content-Type', 'application/json');
          res.end(JSON.stringify({ error: String(e) }));
        }
      });

      // ── GET /api/skill?skill=<name> — read a single skill file ───────────
      server.middlewares.use('/api/skill', (req, res, next) => {
        if (req.method !== 'GET') { next(); return; }
        try {
          const url = new URL(req.url ?? '/', 'http://localhost');
          const skillName = url.searchParams.get('skill');
          const projName = url.searchParams.get('name');
          if (!skillName) {
            res.statusCode = 400;
            res.setHeader('Content-Type', 'application/json');
            res.end(JSON.stringify({ error: 'skill param required' }));
            return;
          }
          const saveRoot = projName ? (readRegistry()[projName] ?? PROJECT_ROOT) : PROJECT_ROOT;
          const skillPath = path.join(saveRoot, 'ralph', 'skills', `${skillName}.md`);
          if (!fs.existsSync(skillPath)) {
            res.statusCode = 404;
            res.setHeader('Content-Type', 'application/json');
            res.end(JSON.stringify({ error: 'skill not found' }));
            return;
          }
          const content = fs.readFileSync(skillPath, 'utf8');
          res.setHeader('Content-Type', 'application/json');
          res.setHeader('Access-Control-Allow-Origin', '*');
          res.end(JSON.stringify({ name: skillName, content }));
        } catch (e) {
          res.statusCode = 500;
          res.setHeader('Content-Type', 'application/json');
          res.end(JSON.stringify({ error: String(e) }));
        }
      });

      // ── POST /api/save-skill — writes ralph/skills/<name>.md ─────────────
      server.middlewares.use('/api/save-skill', (req, res, next) => {
        if (req.method !== 'POST') { next(); return; }
        let body = '';
        req.on('data', (chunk: Buffer) => { body += chunk.toString(); });
        req.on('end', () => {
          try {
            const { content, skillName, name: projName } = JSON.parse(body) as { content: string; skillName: string; name?: string };
            if (!skillName) {
              res.statusCode = 400;
              res.setHeader('Content-Type', 'application/json');
              res.end(JSON.stringify({ error: 'skillName required' }));
              return;
            }
            const saveRoot = projName ? (readRegistry()[projName] ?? PROJECT_ROOT) : PROJECT_ROOT;
            const skillsDir = path.join(saveRoot, 'ralph', 'skills');
            if (!fs.existsSync(skillsDir)) fs.mkdirSync(skillsDir, { recursive: true });
            const skillPath = path.join(skillsDir, `${skillName}.md`);
            fs.writeFileSync(skillPath, content, 'utf8');
            res.setHeader('Content-Type', 'application/json');
            res.setHeader('Access-Control-Allow-Origin', '*');
            res.end(JSON.stringify({ ok: true, path: skillPath }));
          } catch (e) {
            res.statusCode = 500;
            res.setHeader('Content-Type', 'application/json');
            res.end(JSON.stringify({ error: String(e) }));
          }
        });
      });

      // ── GET /api/projects — list registered projects ─────────────────────
      server.middlewares.use('/api/projects', (req, res, next) => {
        if (req.method !== 'GET') { next(); return; }
        res.setHeader('Content-Type', 'application/json');
        res.setHeader('Access-Control-Allow-Origin', '*');
        const reg = readRegistry();
        // Deduplicate by normalized root path (keep first occurrence)
        const seen = new Map<string, string>();
        for (const [name, root] of Object.entries(reg)) {
          const nr = normalizePath(root).toLowerCase().replace(/\\/g, '/').replace(/\/$/, '');
          if (!seen.has(nr)) seen.set(nr, name);
        }
        const projects = [...seen.entries()].map(([, name]) => ({ name, root: reg[name] }));
        res.end(JSON.stringify({ projects }));
      });

      // ── POST /api/register-project — register { name, root } ─────────────
      server.middlewares.use('/api/register-project', (req, res, next) => {
        if (req.method !== 'POST') { next(); return; }
        let body = '';
        req.on('data', (chunk: Buffer) => { body += chunk.toString(); });
        req.on('end', () => {
          try {
            const { name, root } = JSON.parse(body) as { name: string; root: string };
            if (!name || !root) {
              res.statusCode = 400;
              res.setHeader('Content-Type', 'application/json');
              res.end(JSON.stringify({ error: 'name and root are required' }));
              return;
            }
            const reg = readRegistry();
            // Remove case-insensitive duplicates — keep latest registration
            const nameLower = name.toLowerCase();
            for (const key of Object.keys(reg)) {
              if (key.toLowerCase() === nameLower) delete reg[key];
            }
            reg[name] = root;
            writeRegistry(reg);
            res.setHeader('Content-Type', 'application/json');
            res.setHeader('Access-Control-Allow-Origin', '*');
            res.end(JSON.stringify({ ok: true, name, root }));
          } catch (e) {
            res.statusCode = 500;
            res.setHeader('Content-Type', 'application/json');
            res.end(JSON.stringify({ error: String(e) }));
          }
        });
      });

      // ── GET/POST /api/phase-config?name=X — per-project phase enable/disable toggles ──
      // Stored in <projectRoot>/.spiral/ui-phase-config.json
      // Default: Research (R) is OFF, all other phases are ON.
      server.middlewares.use('/api/phase-config', (req, res, next) => {
        const url = new URL(req.url ?? '', 'http://localhost');
        const name = url.searchParams.get('name') ?? '';
        res.setHeader('Access-Control-Allow-Origin', '*');
        res.setHeader('Content-Type', 'application/json');
        if (!name) { res.statusCode = 400; res.end(JSON.stringify({ error: 'name required' })); return; }
        const reg = readRegistry();
        const root = reg[name];
        if (!root) { res.statusCode = 404; res.end(JSON.stringify({ error: 'Project not found' })); return; }

        const configPath = path.join(root, '.spiral', 'ui-phase-config.json');
        const PHASE_DEFAULTS: Record<string, boolean> = {
          A: true, R: false, T: true, S: true, M: true, I: true, V: true, P: true, C: true,
        };

        if (req.method === 'GET') {
          try {
            const saved = fs.existsSync(configPath)
              ? JSON.parse(fs.readFileSync(configPath, 'utf8')) as Record<string, boolean>
              : {};
            res.end(JSON.stringify({ ...PHASE_DEFAULTS, ...saved }));
          } catch { res.end(JSON.stringify(PHASE_DEFAULTS)); }
          return;
        }

        if (req.method === 'POST') {
          let body = '';
          req.on('data', (chunk: Buffer) => { body += chunk.toString(); });
          req.on('end', () => {
            try {
              const { config } = JSON.parse(body) as { config: Record<string, boolean> };
              const spiralDir = path.join(root, '.spiral');
              if (!fs.existsSync(spiralDir)) fs.mkdirSync(spiralDir, { recursive: true });
              fs.writeFileSync(configPath, JSON.stringify(config, null, 2), 'utf8');

              // Also update spiral.config.sh: write SKIP_RESEARCH and SPIRAL_SKIP_PHASES
              const skipPhases = Object.entries(config)
                .filter(([, enabled]) => !enabled)
                .map(([phase]) => phase)
                .join(',');
              const configSh = path.join(root, 'spiral.config.sh');
              let shContent = fs.existsSync(configSh) ? fs.readFileSync(configSh, 'utf8') : '';

              // Helper: set/add a shell variable in the config string
              const patchShVar = (content: string, key: string, value: string): string => {
                const re = new RegExp(`^(\\s*(?:export\\s+)?${key}=).*$`, 'm');
                const line = `${key}="${value}"`;
                return re.test(content) ? content.replace(re, line) : content + (content.endsWith('\n') ? '' : '\n') + line + '\n';
              };

              shContent = patchShVar(shContent, 'SPIRAL_SKIP_PHASES', skipPhases);
              shContent = patchShVar(shContent, 'SKIP_RESEARCH', config['R'] === false ? '1' : '0');
              fs.writeFileSync(configSh, shContent, 'utf8');

              res.end(JSON.stringify({ ok: true }));
            } catch (e) {
              res.statusCode = 500;
              res.end(JSON.stringify({ error: String(e) }));
            }
          });
          return;
        }

        next();
      });

      // ── GET /api/phase-trace?name=X — phase trace data for Phase Trace tab ──
      server.middlewares.use('/api/phase-trace', (req, res, next) => {
        if (req.method !== 'GET') { next(); return; }
        const url = new URL(req.url ?? '', 'http://localhost');
        const name = url.searchParams.get('name') ?? '';

        res.setHeader('Access-Control-Allow-Origin', '*');
        res.setHeader('Content-Type', 'application/json');

        if (!name) { res.statusCode = 400; res.end(JSON.stringify({ error: 'name required' })); return; }

        const reg = readRegistry();
        const root = reg[name];
        if (!root) { res.statusCode = 404; res.end(JSON.stringify({ error: 'Project not found' })); return; }

        try {
          // Parse _last_run.log into iterations and phases.
          // Helper: read a log candidate and return its text (null bytes stripped).
          const readLogCandidate = (p: string): string =>
            fs.existsSync(p) ? fs.readFileSync(p, 'utf8').replace(/\0/g, '') : '';

          // Quick check: does the text contain at least one iteration banner?
          const hasIterations = (text: string): boolean =>
            /SPIRAL Iteration \d+/.test(text);

          // Try _last_run.log first, then rotated logs (.1, .2, .3) as fallbacks
          // when the primary log has no parsed iterations (e.g. mid-run / crashed).
          const spiralDir = path.join(root, '.spiral');
          const logCandidates = [
            path.join(spiralDir, '_last_run.log'),
            path.join(spiralDir, '_last_run.log.1'),
            path.join(spiralDir, '_last_run.log.2'),
            path.join(spiralDir, '_last_run.log.3'),
          ];
          let logText = '';
          for (const candidate of logCandidates) {
            const text = readLogCandidate(candidate);
            if (hasIterations(text)) { logText = text; break; }
            // If primary log exists but has no iterations yet, keep it for
            // display purposes but continue trying rotated logs.
            if (candidate === logCandidates[0] && text) logText = text;
          }

          // Parse phase output files
          const readJsonSafe = (p: string) => {
            try { return fs.existsSync(p) ? JSON.parse(fs.readFileSync(p, 'utf8')) : null; } catch { return null; }
          };

          const phaseOutputs: Record<string, unknown> = {
            aiSuggestions: readJsonSafe(path.join(root, '.spiral', '_ai_suggestions_output.json')),
            research: readJsonSafe(path.join(root, '.spiral', '_research_output.json')),
            testStories: readJsonSafe(path.join(root, '.spiral', '_test_stories_output.json')),
            validated: readJsonSafe(path.join(root, '.spiral', '_validated_stories.json')),
            overflow: readJsonSafe(path.join(root, '.spiral', '_research_overflow.json')),
            checkpoint: readJsonSafe(path.join(root, '.spiral', '_checkpoint.json')),
          };

          // Parse spiral_events.jsonl for phase_start/phase_end events
          const eventsPath = path.join(root, '.spiral', 'spiral_events.jsonl');
          const rawEvents = readJsonl(eventsPath);

          type PhaseEvent = { event?: string; type?: string; phase?: string; iteration?: number; duration_s?: number; ts?: string; run_id?: string; [k: string]: unknown };

          // Collect run_ids and filter to a single primary run to avoid
          // cross-worker event mixing (parallel workers each have their own run_id).
          const recentRunIds = new Set<string>();
          const allRunIds: string[] = [];
          for (const e of rawEvents as PhaseEvent[]) {
            if (e.run_id && !recentRunIds.has(e.run_id)) {
              allRunIds.push(e.run_id);
              recentRunIds.add(e.run_id);
            }
          }
          const checkpointRunId = (phaseOutputs.checkpoint as any)?.run_id as string | undefined;
          const primaryRunId = (checkpointRunId && recentRunIds.has(checkpointRunId))
            ? checkpointRunId
            : allRunIds[allRunIds.length - 1] ?? '';

          const phaseEvents = (rawEvents as PhaseEvent[]).filter(e => {
            const isPhaseEvent = e.event === 'phase_start' || e.event === 'phase_end' ||
                                 e.type === 'phase_start' || e.type === 'phase_end';
            if (!isPhaseEvent) return false;
            if (primaryRunId && e.run_id && e.run_id !== primaryRunId) return false;
            return true;
          });

          // Clamp negative durations (stale endtime files can cause negative values)
          for (const evt of phaseEvents) {
            if (typeof evt.duration_s === 'number' && evt.duration_s < 0) {
              evt.duration_s = 0;
            }
          }

          // Parse iterations from the log
          type IterPhase = { phase: string; label: string; lines: string[]; lineStart: number; lineEnd: number; substeps: { id: string; label: string; lines: string[]; lineStart: number; lineEnd: number }[] };
          type Iteration = { iter: number; phases: IterPhase[]; lineStart: number; lineEnd: number };

          const iterations: Iteration[] = [];
          const lines = logText.split('\n');

          // Pattern: "SPIRAL Iteration N / M"
          const iterRe = /SPIRAL Iteration (\d+)\s*\/\s*(\d+)/;
          // Pattern: "[Phase X] LABEL" — X can be A-Z or 0. May be preceded by ║ box chars
          const phaseRe = /\[Phase ([A-Z0-9])\]\s*(.*?)(?:\s*[—–-]\s*(.*))?$/;
          // Pattern: "[Phase X / substep] text" — sub-stages within a phase
          const subStepRe = /\[Phase ([A-Z0-9])\s*\/\s*(\w+)\]\s*(.*)/;
          // Pattern: "[Phase X.N] text" — numbered sub-phases (e.g. I.5)
          const subPhaseRe = /\[Phase ([A-Z0-9])\.(\d+)\]\s*(.*)/;
          // Pattern: "[0-A] text" through "[0-E] text" — Phase 0 sub-phases
          const phase0SubRe = /\[0-([A-E])\]\s*(.*)/;
          // Pattern: "[X] text" — short-form phase markers (single uppercase letter or digit)
          // Matches: [I] WARNING, [C] Not done, [G] Auto-gate, [R] Skipping, [V] No test, [P] Pushed, [M] Merge, [T] Test, [S] Story
          const phaseShortRe = /^\s*\[([A-Z0-9])\]\s+(.*)/;
          // Pattern: "[tag]", "[test-ratchet]", "[security-scan]", "[CAPACITY]", "[merge]" — quality gates & events
          const qualityGateRe = /\[(test-ratchet|security-scan|tag|CAPACITY|merge)\]\s*(.*)/;
          // Pattern: "SPIRAL Phase 0" banner
          const phase0BannerRe = /SPIRAL Phase 0/;

          let currentIter: Iteration | null = null;
          let currentPhase: IterPhase | null = null;
          let currentSubstep: { id: string; label: string; lines: string[]; lineStart: number; lineEnd: number } | null = null;

          const pushSubstep = () => {
            if (currentSubstep && currentPhase) {
              currentSubstep.lineEnd = currentSubstep.lines.length > 0 ? currentSubstep.lineStart + currentSubstep.lines.length - 1 : currentSubstep.lineStart;
              currentPhase.substeps.push(currentSubstep);
              currentSubstep = null;
            }
          };

          const pushPhase = (endLine: number) => {
            if (currentPhase && currentIter) {
              pushSubstep();
              currentPhase.lineEnd = endLine;
              currentIter.phases.push(currentPhase);
              currentPhase = null;
            }
          };

          for (let i = 0; i < lines.length; i++) {
            const line = lines[i];

            // New iteration
            const iterMatch = line.match(iterRe);
            if (iterMatch) {
              pushPhase(i - 1);
              if (currentIter) {
                currentIter.lineEnd = i - 1;
                iterations.push(currentIter);
              }
              currentIter = { iter: parseInt(iterMatch[1]), phases: [], lineStart: i, lineEnd: i };
              continue;
            }

            if (!currentIter) continue;

            // Phase 0 banner (before iteration loop starts — attach to iter 0 or current)
            if (line.match(phase0BannerRe) && !currentPhase?.phase?.startsWith('0')) {
              pushPhase(i - 1);
              currentPhase = { phase: '0', label: 'Session Setup', lines: [], lineStart: i, lineEnd: i, substeps: [] };
              currentPhase.lines.push(line);
              continue;
            }

            // Phase 0 sub-phases: [0-A] through [0-E]
            const p0sub = line.match(phase0SubRe);
            if (p0sub) {
              // If no Phase 0 parent exists yet, create one
              if (!currentPhase || currentPhase.phase !== '0') {
                pushPhase(i - 1);
                currentPhase = { phase: '0', label: 'Session Setup', lines: [], lineStart: i, lineEnd: i, substeps: [] };
              }
              pushSubstep();
              currentSubstep = { id: `0-${p0sub[1]}`, label: p0sub[2].trim(), lines: [line], lineStart: i, lineEnd: i };
              currentPhase.lines.push(line);
              continue;
            }

            // Sub-step within a phase: [Phase I / decompose], [Phase I / retry], etc.
            const subMatch = line.match(subStepRe);
            if (subMatch) {
              const parentPhase = subMatch[1];
              // If we're inside the matching parent phase, add as substep
              if (currentPhase && currentPhase.phase === parentPhase) {
                pushSubstep();
                currentSubstep = { id: `${parentPhase}/${subMatch[2]}`, label: subMatch[3].trim(), lines: [line], lineStart: i, lineEnd: i };
                currentPhase.lines.push(line);
                continue;
              }
              // Otherwise treat as a new phase
              pushPhase(i - 1);
              currentPhase = { phase: parentPhase, label: `${subMatch[2]} — ${subMatch[3].trim()}`, lines: [line], lineStart: i, lineEnd: i, substeps: [] };
              continue;
            }

            // Numbered sub-phase: [Phase I.5]
            const subNumMatch = line.match(subPhaseRe);
            if (subNumMatch) {
              const parentPhase = subNumMatch[1];
              if (currentPhase && currentPhase.phase === parentPhase) {
                pushSubstep();
                currentSubstep = { id: `${parentPhase}.${subNumMatch[2]}`, label: subNumMatch[3].trim(), lines: [line], lineStart: i, lineEnd: i };
                currentPhase.lines.push(line);
                continue;
              }
            }

            // Quality gate markers — attach as substep of current phase
            const gateMatch = line.match(qualityGateRe);
            if (gateMatch && currentPhase) {
              pushSubstep();
              currentSubstep = { id: gateMatch[1], label: gateMatch[2].trim(), lines: [line], lineStart: i, lineEnd: i };
              currentPhase.lines.push(line);
              continue;
            }

            // Full phase marker: [Phase X] LABEL
            const phaseMatch = line.match(phaseRe);
            if (phaseMatch) {
              // If we're already inside this phase, just accumulate the line
              // instead of creating a duplicate phase entry
              if (currentPhase && currentPhase.phase === phaseMatch[1]) {
                currentPhase.lines.push(line);
                continue;
              }
              pushPhase(i - 1);
              currentPhase = {
                phase: phaseMatch[1],
                label: (phaseMatch[2] + (phaseMatch[3] ? ' — ' + phaseMatch[3] : '')).trim(),
                lines: [line],
                lineStart: i,
                lineEnd: i,
                substeps: [],
              };
              continue;
            }

            // Short-form phase marker: [X] text
            const shortMatch = line.match(phaseShortRe);
            if (shortMatch) {
              // If same phase as current, just add to it
              if (currentPhase && currentPhase.phase === shortMatch[1]) {
                currentPhase.lines.push(line);
                continue;
              }
              pushPhase(i - 1);
              currentPhase = {
                phase: shortMatch[1],
                label: shortMatch[2],
                lines: [line],
                lineStart: i,
                lineEnd: i,
                substeps: [],
              };
              continue;
            }

            // Accumulate lines for current phase/substep
            if (currentSubstep) {
              currentSubstep.lines.push(line);
            }
            if (currentPhase) {
              currentPhase.lines.push(line);
            }
          }

          // Close final phase and iteration
          if (currentPhase && currentIter) {
            currentPhase.lineEnd = lines.length - 1;
            currentIter.phases.push(currentPhase);
          }
          if (currentIter) {
            currentIter.lineEnd = lines.length - 1;
            iterations.push(currentIter);
          }

          // Deduplicate iterations by iter number (keep last occurrence)
          const iterMap = new Map<number, Iteration>();
          for (const iter of iterations) {
            iterMap.set(iter.iter, iter);
          }

          // Synthesize iteration stubs from phase events ONLY when the log has no
          // iteration data at all (e.g. log was rotated away mid-run).
          // Guard: if the log already has iterations, skip stub synthesis — old
          // spiral_events.jsonl entries from previous runs would otherwise create
          // empty greyed-out iterations 2-N for iterations that haven't happened
          // yet in the current run.
          if (iterMap.size === 0) {
            for (const evt of phaseEvents) {
              const iterNum = evt.iteration;
              if (iterNum != null && !iterMap.has(iterNum)) {
                iterMap.set(iterNum, {
                  iter: iterNum,
                  phases: [],
                  lineStart: -1,
                  lineEnd: -1,
                });
              }
            }
          }

          const dedupedIterations = [...iterMap.values()].sort((a, b) => a.iter - b.iter);

          // Deduplicate phases within each iteration (same phase letter → merge lines/substeps)
          // Handles edge cases where the log emits multiple [Phase X] banners for the same phase
          for (const iter of dedupedIterations) {
            const phaseMap = new Map<string, IterPhase>();
            for (const phase of iter.phases) {
              if (phaseMap.has(phase.phase)) {
                const existing = phaseMap.get(phase.phase)!;
                existing.lines.push(...phase.lines);
                existing.substeps.push(...phase.substeps);
                existing.lineEnd = phase.lineEnd;
              } else {
                phaseMap.set(phase.phase, phase);
              }
            }
            iter.phases = [...phaseMap.values()];
          }

          // Inject placeholder phases for the full pipeline so every iteration shows all stages.
          // Canonical phase execution order — must match spiral.sh main loop:
          //   A → R+T → S → E(enrich) → M → X(context) → G+I → V → C → L(learn)
          const FULL_PIPELINE = ['A', 'R', 'T', 'S', 'E', 'M', 'X', 'I', 'V', 'P', 'C', 'L'];
          const PIPELINE_LABELS: Record<string, string> = {
            A: 'AI Suggestions', R: 'Research', T: 'Test Synthesis', S: 'Story Validate',
            E: 'Story Enrichment', M: 'Merge', X: 'Context Build', I: 'Implement',
            V: 'Validate', P: 'Push', C: 'Check Done', L: 'Learning',
          };

          // Phases that have EVER fired a phase_start event across all iterations.
          // A phase absent from this set is intentionally bypassed (e.g. Phase A disabled in config).
          const phasesEverStarted = new Set(
            phaseEvents
              .filter(e => e.event === 'phase_start' || e.type === 'phase_start')
              .map(e => e.phase)
              .filter(Boolean)
          );
          // Also count phases seen in the parsed log lines as "ever started"
          for (const iter of dedupedIterations) {
            for (const p of iter.phases) {
              if (p.lineStart !== -1) phasesEverStarted.add(p.phase);
            }
          }

          for (const iter of dedupedIterations) {
            const existingPhases = new Set(iter.phases.map(p => p.phase));
            for (const phaseId of FULL_PIPELINE) {
              if (!existingPhases.has(phaseId)) {
                const bypassed = !phasesEverStarted.has(phaseId);
                iter.phases.push({
                  phase: phaseId,
                  label: bypassed
                    ? `${PIPELINE_LABELS[phaseId] ?? phaseId} (bypassed)`
                    : `${PIPELINE_LABELS[phaseId] ?? phaseId} (not run)`,
                  lines: [bypassed
                    ? `(Phase ${phaseId} is not enabled in this Spiral config)`
                    : `(Phase ${phaseId} has not run yet this iteration)`],
                  lineStart: -1,
                  lineEnd: -1,
                  substeps: [],
                  bypassed,
                } as typeof iter.phases[0] & { bypassed: boolean });
              }
            }
          }

          // Cap lines per phase to last 150 to avoid huge payloads
          for (const iter of dedupedIterations) {
            for (const p of iter.phases) {
              if (p.lines.length > 150) {
                p.lines = ['... (' + (p.lines.length - 150) + ' lines truncated)', ...p.lines.slice(-150)];
              }
              for (const sub of (p.substeps ?? [])) {
                if (sub.lines.length > 80) {
                  sub.lines = ['... (' + (sub.lines.length - 80) + ' lines truncated)', ...sub.lines.slice(-80)];
                }
              }
            }
          }

          res.end(JSON.stringify({
            iterations: dedupedIterations.slice(-10), // last 10 iterations
            phaseOutputs,
            phaseEvents,
            primaryRunId,
          }));
        } catch (e) {
          res.statusCode = 500;
          res.end(JSON.stringify({ error: String(e) }));
        }
      });

      // ── GET /api/project-live?name=X — full live data for dashboard ───────
      server.middlewares.use('/api/project-live', (req, res, next) => {
        if (req.method !== 'GET') { next(); return; }
        const url = new URL(req.url ?? '', 'http://localhost');
        const name = url.searchParams.get('name') ?? '';

        res.setHeader('Access-Control-Allow-Origin', '*');
        res.setHeader('Content-Type', 'application/json');

        if (!name) {
          res.statusCode = 400;
          res.end(JSON.stringify({ error: 'name parameter is required' }));
          return;
        }

        const reg = readRegistry();
        const root = reg[name];
        if (!root) {
          res.statusCode = 404;
          res.end(JSON.stringify({ error: `Project "${name}" not found. Is SPIRAL running with this project?` }));
          return;
        }

        try {
          // Config
          const config = parseConfigSh(path.join(root, 'spiral.config.sh'));

          // Story completion times from git history
          const completionTimes = getStoryCompletionTimes(root);

          // prd.json
          let progress = null;
          const prdPath = path.join(root, 'prd.json');
          if (fs.existsSync(prdPath)) {
            try {
              const prd = JSON.parse(fs.readFileSync(prdPath, 'utf8')) as {
                productName?: string;
                overview?: string;
                userStories?: Array<{ id: string; title: string; description?: string; passes: boolean; priority?: string; complexity?: string; _failureReason?: string; dependencies?: string[]; _status?: string; _source?: string; retryCount?: number; acceptanceCriteria?: string[]; filesTouch?: string[]; _scopeCreep?: boolean; last_attempted?: string }>;
              };
              const stories = (prd.userStories ?? []).map(s => ({
                id: s.id,
                title: s.title,
                description: s.description,
                passes: s.passes,
                priority: s.priority,
                complexity: s.complexity,
                failureReason: s._failureReason,
                dependencies: s.dependencies,
                status: s._status,
                source: s._source,
                retryCount: s.retryCount,
                acceptanceCriteria: s.acceptanceCriteria,
                filesTouch: s.filesTouch,
                completedAt: s.passes ? completionTimes[s.id] ?? null : null,
                scopeCreep: s._scopeCreep ?? false,
                lastAttempted: s.last_attempted ?? null,
              }));
              const done = stories.filter(s => s.passes).length;
              const pending = stories.filter(s => !s.passes).length;
              progress = {
                total: stories.length,
                done,
                pending,
                productName: prd.productName,
                overview: prd.overview,
                stories,
              };
            } catch { /* prd.json unreadable */ }
          }

          // Constitution
          const constitution = readConstitution(root, config);

          // Activity log (last 200 lines of _last_run.log)
          const activity = tailFile(path.join(root, '.spiral', '_last_run.log'), 200);

          // Progress history
          const progressHistory = readJsonl(path.join(root, '.spiral', 'ui-progress-history.jsonl'));

          // US-189: Token burn data from token_metrics.jsonl
          const rawTokenMetrics = readJsonl(path.join(root, '.spiral', 'token_metrics.jsonl'));
          // Aggregate per story_id: { story_id, input, output, total, calls }
          const tokenBurnMap: Record<string, { story_id: string; input: number; output: number; total: number; calls: number }> = {};
          for (const rec of rawTokenMetrics) {
            const r = rec as { story_id?: string; input_tokens?: number; output_tokens?: number; total_tokens?: number };
            const sid = r.story_id ?? 'unknown';
            if (!tokenBurnMap[sid]) tokenBurnMap[sid] = { story_id: sid, input: 0, output: 0, total: 0, calls: 0 };
            tokenBurnMap[sid].input += r.input_tokens ?? 0;
            tokenBurnMap[sid].output += r.output_tokens ?? 0;
            tokenBurnMap[sid].total += r.total_tokens ?? ((r.input_tokens ?? 0) + (r.output_tokens ?? 0));
            tokenBurnMap[sid].calls += 1;
          }
          const tokenBurn = Object.values(tokenBurnMap);

          // US-223: Cache hit rate from spiral_events.jsonl (prompt_cache + phase_cache_hit events)
          const rawEvents = readJsonl(path.join(root, '.spiral', 'spiral_events.jsonl'));
          type CachePhaseStats = { hits: number; total: number; creation_tokens: number; read_tokens: number };
          const cacheByPhase: Record<string, CachePhaseStats> = {};
          for (const ev of rawEvents) {
            const e = ev as { event?: string; phase?: string; cache_hit?: boolean; cache_creation_tokens?: number; cache_read_tokens?: number };
            if (e.event !== 'prompt_cache' && e.event !== 'phase_cache_hit') continue;
            const phase = e.phase ?? 'I';
            if (!cacheByPhase[phase]) cacheByPhase[phase] = { hits: 0, total: 0, creation_tokens: 0, read_tokens: 0 };
            cacheByPhase[phase].total += 1;
            if (e.cache_hit) cacheByPhase[phase].hits += 1;
            cacheByPhase[phase].creation_tokens += e.cache_creation_tokens ?? 0;
            cacheByPhase[phase].read_tokens += e.cache_read_tokens ?? 0;
          }
          const cacheStats = Object.entries(cacheByPhase).map(([phase, s]) => ({
            phase,
            hit_rate: s.total > 0 ? s.hits / s.total : 0,
            hits: s.hits,
            total: s.total,
            creation_tokens: s.creation_tokens,
            read_tokens: s.read_tokens,
          }));

          // Last-seen from registry metadata (we just use now since we read files live)
          const lastSeen = new Date().toISOString();

          // Last completed story + recently completed feed + per-story attempt history from results.tsv
          type CompletedEntry = { id: string; title: string; timestamp: string; model: string; duration: number; retryCount: number; totalTokens: number; totalDuration: number };
          let lastCompletedStory: CompletedEntry | null = null;
          const recentlyCompleted: CompletedEntry[] = [];
          const storyAttemptsMap: Record<string, { timestamp: string; status: string; model: string; duration: number; commitSha: string }[]> = {};
          // Track per-story aggregates and completed stories per iteration
          const storyAggregates: Record<string, { attempts: number; totalTokens: number; totalDuration: number }> = {};
          const completedByIter: Record<number, string[]> = {};
          const tsvPath = path.join(root, 'results.tsv');
          if (fs.existsSync(tsvPath)) {
            try {
              const tsvLines = fs.readFileSync(tsvPath, 'utf8').split('\n').filter(Boolean);
              // Parse header to find column indices
              const headers = tsvLines[0].split('\t');
              const colIdx = (name: string) => headers.indexOf(name);
              const iTimestamp = colIdx('timestamp'), iSpiralIter = colIdx('spiral_iter'),
                    iStoryId = colIdx('story_id'), iStoryTitle = colIdx('story_title'),
                    iStatus = colIdx('status'), iDuration = colIdx('duration_sec'),
                    iModel = colIdx('model'), iCommitSha = colIdx('commit_sha'),
                    iCacheRead = colIdx('cache_read_tokens'), iCacheCreation = colIdx('cache_creation_tokens'),
                    iReview = colIdx('review_tokens'),
                    iInput = colIdx('input_tokens'), iOutput = colIdx('output_tokens');

              for (let i = 1; i < tsvLines.length; i++) {
                const cols = tsvLines[i].split('\t');
                const sid = cols[iStoryId] ?? '';
                const duration = parseInt(cols[iDuration]) || 0;
                const tokens = (parseInt(cols[iCacheRead]) || 0) + (parseInt(cols[iCacheCreation]) || 0) + (parseInt(cols[iReview]) || 0)
                  + (iInput >= 0 ? (parseInt(cols[iInput]) || 0) : 0) + (iOutput >= 0 ? (parseInt(cols[iOutput]) || 0) : 0);
                const attempt = {
                  timestamp: cols[iTimestamp] ?? '',
                  status: cols[iStatus] ?? '',
                  model: cols[iModel] ?? '',
                  duration,
                  commitSha: cols[iCommitSha] ?? '',
                };
                if (sid) {
                  if (!storyAttemptsMap[sid]) storyAttemptsMap[sid] = [];
                  storyAttemptsMap[sid].push(attempt);
                  // Aggregate per-story stats
                  if (!storyAggregates[sid]) storyAggregates[sid] = { attempts: 0, totalTokens: 0, totalDuration: 0 };
                  storyAggregates[sid].attempts += 1;
                  storyAggregates[sid].totalTokens += tokens;
                  storyAggregates[sid].totalDuration += duration;
                }
                if ((cols[iStatus] ?? '') === 'keep') {
                  const iterNum = parseInt(cols[iSpiralIter]) || 0;
                  if (!completedByIter[iterNum]) completedByIter[iterNum] = [];
                  completedByIter[iterNum].push(sid);
                  const agg = storyAggregates[sid] ?? { attempts: 0, totalTokens: 0, totalDuration: 0 };
                  const entry: CompletedEntry = {
                    id: sid, title: cols[iStoryTitle] ?? '', timestamp: cols[iTimestamp] ?? '',
                    model: cols[iModel] ?? '', duration,
                    retryCount: Math.max(0, agg.attempts - 1),
                    totalTokens: agg.totalTokens,
                    totalDuration: agg.totalDuration,
                  };
                  lastCompletedStory = entry;
                  recentlyCompleted.push(entry);
                }
              }
              // Sort descending by timestamp, keep top 10
              recentlyCompleted.sort((a, b) => b.timestamp.localeCompare(a.timestamp));
              recentlyCompleted.splice(10);
              // Keep last 5 attempts per story, sorted by timestamp desc
              for (const sid of Object.keys(storyAttemptsMap)) {
                storyAttemptsMap[sid].sort((a, b) => b.timestamp.localeCompare(a.timestamp));
                storyAttemptsMap[sid].splice(5);
              }
            } catch { /* ignore */ }
          }

          // Fallback: populate from prd.json passed stories with git completion times
          if (recentlyCompleted.length === 0 && progress) {
            const passedStories = (progress as { stories: { id: string; title: string; passes: boolean; completedAt: string | null }[] }).stories
              .filter((s: { passes: boolean; completedAt: string | null }) => s.passes && s.completedAt)
              .map((s: { id: string; title: string; completedAt: string | null }) => {
                const agg = storyAggregates[s.id];
                return {
                  id: s.id, title: s.title, timestamp: s.completedAt!, model: '', duration: 0,
                  retryCount: agg ? Math.max(0, agg.attempts - 1) : 0,
                  totalTokens: agg?.totalTokens ?? 0,
                  totalDuration: agg?.totalDuration ?? 0,
                };
              })
              .sort((a: { timestamp: string }, b: { timestamp: string }) => b.timestamp.localeCompare(a.timestamp))
              .slice(0, 10);
            recentlyCompleted.push(...passedStories);
            if (passedStories.length > 0) {
              lastCompletedStory = passedStories[0];
            }
          }

          // Fallback: check story_passed events from spiral_events.jsonl
          if (!lastCompletedStory) {
            const storyEvents = [...rawEvents, ...readJsonl(path.join(root, 'spiral_events.jsonl'))];
            for (const ev of storyEvents) {
              const e = ev as { event?: string; storyId?: string; ts?: string; model?: string };
              if (e.event === 'story_passed' && e.ts) {
                if (!lastCompletedStory || e.ts > lastCompletedStory.timestamp) {
                  const agg = storyAggregates[e.storyId ?? ''];
                  lastCompletedStory = {
                    id: e.storyId ?? '', title: '', timestamp: e.ts, model: e.model ?? '', duration: 0,
                    retryCount: agg ? Math.max(0, agg.attempts - 1) : 0,
                    totalTokens: agg?.totalTokens ?? 0,
                    totalDuration: agg?.totalDuration ?? 0,
                  };
                }
              }
            }
          }

          // Checkpoint and log modification time for RUNNING detection
          const checkpointPath = path.join(root, '.spiral', '_checkpoint.json');
          let checkpointTs: string | null = null;
          try {
            if (fs.existsSync(checkpointPath)) {
              const cp = JSON.parse(fs.readFileSync(checkpointPath, 'utf8')) as { ts?: string };
              checkpointTs = cp.ts ?? null;
            }
          } catch { /* ignore */ }

          const logPath = path.join(root, '.spiral', '_last_run.log');
          let lastLogModified: string | null = null;
          try {
            if (fs.existsSync(logPath)) {
              lastLogModified = fs.statSync(logPath).mtime.toISOString();
            }
          } catch { /* ignore */ }

          const configRaw = (() => {
            try {
              const p = path.join(root, 'spiral.config.sh');
              return fs.existsSync(p) ? fs.readFileSync(p, 'utf8') : '';
            } catch { return ''; }
          })();

          // US-315: Active status from .spiral/_active_status.json
          let activeStatus: { phase: string; iteration: number; started_at: number; pct_done: number; story_id?: string; story_title?: string } | null = null;
          try {
            const activeStatusPath = path.join(root, '.spiral', '_active_status.json');
            if (fs.existsSync(activeStatusPath)) {
              activeStatus = JSON.parse(fs.readFileSync(activeStatusPath, 'utf8')) as typeof activeStatus;
            }
          } catch { /* ignore */ }

          res.end(JSON.stringify({
            name,
            root,
            lastSeen,
            progress,
            config,
            configRaw,
            constitution,
            activity,
            progressHistory,
            tokenBurn,
            cacheStats,
            lastCompletedStory,
            recentlyCompleted,
            storyAttempts: storyAttemptsMap,
            checkpointTs,
            lastLogModified,
            activeStatus,
          }));
        } catch (e) {
          res.statusCode = 500;
          res.end(JSON.stringify({ error: String(e) }));
        }
      });

      // ── GET /api/active-story?name=X — currently active story being worked on ──
      // Parses .spiral/ralph-run.log to find the most recent [spawn] that has no
      // matching [done] or [fail] after it.
      server.middlewares.use('/api/active-story', (req, res, next) => {
        if (req.method !== 'GET') { next(); return; }
        const url = new URL(req.url ?? '', 'http://localhost');
        const name = url.searchParams.get('name') ?? '';

        res.setHeader('Access-Control-Allow-Origin', '*');
        res.setHeader('Content-Type', 'application/json');

        const reg = readRegistry();
        const root = name ? (reg[name] ?? null) : PROJECT_ROOT;
        if (!root) {
          res.end(JSON.stringify({ storyId: null }));
          return;
        }

        try {
          // Check _last_run.log first (current run), fall back to ralph-run.log
          const spiralDir = path.join(root, '.spiral');
          const logCandidates = [
            path.join(spiralDir, '_last_run.log'),
            path.join(spiralDir, 'ralph-run.log'),
          ];
          const stripAnsi = (s: string) => s.replace(/\x1b\[[0-9;]*[mGKHF]/g, '').replace(/\0/g, '');
          let logText = '';
          for (const lp of logCandidates) {
            if (fs.existsSync(lp)) {
              const t = stripAnsi(fs.readFileSync(lp, 'utf8'));
              if (/\[spawn\]/i.test(t)) { logText = t; break; }
              if (!logText) logText = t; // keep first existing as fallback
            }
          }
          if (!logText) {
            res.end(JSON.stringify({ storyId: null }));
            return;
          }
          const lines = logText.split('\n');

          // Walk lines in reverse to find the last [spawn] and check if [done]/[fail] follows it
          const spawnRe = /\[spawn\]\s+Fresh claude instance for\s+((?:US|UT)-\d+)/i;
          const doneRe = /\[done\]\s+Story completed/i;
          const failRe = /\[fail\]/i;

          // Find the last spawn line index and story ID
          let lastSpawnIdx = -1;
          let lastSpawnStoryId: string | null = null;
          for (let i = lines.length - 1; i >= 0; i--) {
            const m = lines[i].match(spawnRe);
            if (m) {
              lastSpawnIdx = i;
              lastSpawnStoryId = m[1].toUpperCase();
              break;
            }
          }

          if (lastSpawnIdx === -1 || !lastSpawnStoryId) {
            res.end(JSON.stringify({ storyId: null }));
            return;
          }

          // Check if any [done] or [fail] line appears AFTER the last spawn
          let isCompleted = false;
          for (let i = lastSpawnIdx + 1; i < lines.length; i++) {
            if (doneRe.test(lines[i]) || failRe.test(lines[i])) {
              isCompleted = true;
              break;
            }
          }

          if (isCompleted) {
            res.end(JSON.stringify({ storyId: null }));
            return;
          }

          // Look up the story title from prd.json
          let storyTitle: string | null = null;
          try {
            const prdPath = path.join(root, 'prd.json');
            if (fs.existsSync(prdPath)) {
              const prd = JSON.parse(fs.readFileSync(prdPath, 'utf8')) as {
                userStories?: Array<{ id: string; title: string }>;
              };
              const story = (prd.userStories ?? []).find(s => s.id === lastSpawnStoryId);
              storyTitle = story?.title ?? null;
            }
          } catch { /* ignore */ }

          res.end(JSON.stringify({ storyId: lastSpawnStoryId, title: storyTitle }));
        } catch (e) {
          res.end(JSON.stringify({ storyId: null, error: String(e) }));
        }
      });

      // ── DELETE /api/story?name=X&id=Y — remove a story from prd.json ───────
      server.middlewares.use('/api/story', (req, res, next) => {
        if (req.method !== 'DELETE' && req.method !== 'OPTIONS') { next(); return; }
        res.setHeader('Access-Control-Allow-Origin', '*');
        res.setHeader('Access-Control-Allow-Methods', 'DELETE, OPTIONS');
        res.setHeader('Content-Type', 'application/json');
        if (req.method === 'OPTIONS') { res.statusCode = 204; res.end(); return; }
        const url = new URL(req.url ?? '', 'http://localhost');
        const name = url.searchParams.get('name') ?? '';
        const storyId = url.searchParams.get('id') ?? '';
        if (!storyId) { res.statusCode = 400; res.end(JSON.stringify({ error: 'id required' })); return; }
        const reg = readRegistry();
        const root = name ? (reg[name] ?? null) : PROJECT_ROOT;
        if (!root) { res.statusCode = 404; res.end(JSON.stringify({ error: `Project "${name}" not found` })); return; }
        const prdPath = path.join(root, 'prd.json');
        try {
          const prd = JSON.parse(fs.readFileSync(prdPath, 'utf8')) as { userStories?: { id: string }[] };
          const before = (prd.userStories ?? []).length;
          prd.userStories = (prd.userStories ?? []).filter(s => s.id !== storyId);
          if (prd.userStories.length === before) {
            res.statusCode = 404; res.end(JSON.stringify({ error: `Story "${storyId}" not found` })); return;
          }
          const tmp = prdPath + '.tmp';
          fs.writeFileSync(tmp, JSON.stringify(prd, null, 2), 'utf8');
          fs.renameSync(tmp, prdPath);
          res.end(JSON.stringify({ ok: true, deleted: storyId }));
        } catch (e) {
          res.statusCode = 500; res.end(JSON.stringify({ error: String(e) }));
        }
      });

      // ── GET /api/system-memory — memory pressure / watchdog status ──────────
      server.middlewares.use('/api/system-memory', (req, res, next) => {
        if (req.method !== 'GET') { next(); return; }
        res.setHeader('Content-Type', 'application/json');
        res.setHeader('Access-Control-Allow-Origin', '*');

        const url = new URL(req.url ?? '/', 'http://localhost');
        const projName = url.searchParams.get('name');
        const root = projName ? (readRegistry()[projName] ?? PROJECT_ROOT) : PROJECT_ROOT;
        const pressureFile = path.join(root, '.spiral', '_memory_pressure.json');

        const levelLabels: Record<number, string> = { 0: 'Normal', 1: 'Elevated', 2: 'High', 3: 'Critical', 4: 'Emergency' };
        const perWorkerBudget = 1536;

        if (!fs.existsSync(pressureFile)) {
          res.end(JSON.stringify({
            watchdog_running: false, level: null, level_label: null,
            free_mb: null, total_mb: null, used_mb: null, free_pct: null,
            recommended_workers: null, per_worker_budget_mb: perWorkerBudget,
            config_hints: ['Memory watchdog not running — start SPIRAL to enable monitoring'],
          }));
          return;
        }

        try {
          const raw = JSON.parse(fs.readFileSync(pressureFile, 'utf8')) as {
            level?: number; free_mb?: number; total_mb?: number; node_procs?: number;
            recommended_workers?: number; recommended_model?: string; skip_phases?: string[]; ts?: string;
          };

          // Check staleness
          let stale = true;
          if (raw.ts) {
            const tsMs = new Date(raw.ts).getTime();
            stale = isNaN(tsMs) || (Date.now() - tsMs > 120_000);
          }

          const level = raw.level ?? 0;
          const freeMb = raw.free_mb ?? 0;
          const totalMb = raw.total_mb ?? null;
          const usedMb = totalMb != null ? totalMb - freeMb : null;
          const freePct = totalMb && totalMb > 0 ? Math.floor((freeMb / totalMb) * 100) : null;
          const recWorkers = raw.recommended_workers ?? 0;

          const hints: string[] = [];
          if (freeMb > 0) {
            const capacity = Math.max(1, Math.floor(freeMb / perWorkerBudget));
            hints.push(`Free RAM supports ~${capacity} workers at ${perWorkerBudget} MB each`);
          }
          if (level >= 2) hints.push('Consider reducing SPIRAL_RALPH_WORKERS or closing other applications');
          if (level >= 3) hints.push('Model routing forced to haiku — reduce memory pressure for better models');
          if (raw.recommended_model) hints.push(`Recommended model: ${raw.recommended_model}`);
          if (raw.skip_phases?.length) hints.push(`Phases skipped due to pressure: ${raw.skip_phases.join(', ')}`);
          if (stale) hints.unshift('Memory watchdog data is stale (>120s) — watchdog may have stopped');

          res.end(JSON.stringify({
            watchdog_running: !stale, level, level_label: levelLabels[level] ?? 'Unknown',
            free_mb: freeMb, total_mb: totalMb, used_mb: usedMb, free_pct: freePct,
            recommended_workers: recWorkers, per_worker_budget_mb: perWorkerBudget,
            config_hints: hints,
          }));
        } catch (e) {
          res.statusCode = 500;
          res.end(JSON.stringify({ error: String(e) }));
        }
      });

      // ── GET /api/workers/:id/queue — task queue for a specific worker ────────
      // ── GET /api/workers?name=X — list worker log files for a project ──────
      // Both handled by the same middleware (connect strips /api/workers prefix from req.url)
      server.middlewares.use('/api/workers', (req, res, next) => {
        if (req.method !== 'GET') { next(); return; }

        res.setHeader('Access-Control-Allow-Origin', '*');
        res.setHeader('Content-Type', 'application/json');

        // Detect /api/workers/:id/queue requests (req.url = "/<id>/queue" after prefix strip)
        const queueMatch = (req.url ?? '').match(/^\/(\d+)\/queue(?:\?|$)/);
        if (queueMatch) {
          const workerId = parseInt(queueMatch[1]);
          const urlParsed = new URL(req.url ?? '', 'http://localhost');
          const name = urlParsed.searchParams.get('name') ?? '';
          const reg = readRegistry();
          const root = name ? (reg[name] ?? PROJECT_ROOT) : PROJECT_ROOT;
          const workersDir = path.join(root, '.spiral', 'workers');
          const jsonFile = path.join(workersDir, `worker_${workerId}.json`);

          if (!fs.existsSync(jsonFile)) {
            res.statusCode = 404;
            res.end(JSON.stringify({ error: `Worker ${workerId} not found`, error_code: 'WORKER_NOT_FOUND' }));
            return;
          }

          try {
            const raw = JSON.parse(fs.readFileSync(jsonFile, 'utf8')) as {
              current_task?: { story_id: string; started_at: string };
              queue?: { story_id: string }[];
              uptime?: number;
              worker_id?: string | number;
            };
            res.end(JSON.stringify({
              worker_id: `worker-${workerId}`,
              current_task: raw.current_task ?? null,
              queue: raw.queue ?? [],
              uptime: raw.uptime ?? 0,
            }));
          } catch (e) {
            res.statusCode = 500;
            res.end(JSON.stringify({ error: String(e), error_code: 'READ_ERROR' }));
          }
          return;
        }

        // Detect /api/workers/:id (worker details without /queue)
        const workerIdMatch = (req.url ?? '').match(/^\/(\d+)(?:\?|$)/);
        if (workerIdMatch) {
          const workerId = parseInt(workerIdMatch[1]);
          const urlParsed = new URL(req.url ?? '', 'http://localhost');
          const name = urlParsed.searchParams.get('name') ?? '';
          const reg = readRegistry();
          const root = name ? (reg[name] ?? PROJECT_ROOT) : PROJECT_ROOT;
          const workersDir = path.join(root, '.spiral', 'workers');
          const jsonFile = path.join(workersDir, `worker_${workerId}.json`);

          if (!fs.existsSync(jsonFile) && !fs.existsSync(path.join(workersDir, `worker_${workerId}.log`))) {
            res.statusCode = 404;
            res.end(JSON.stringify({ error: `Worker ${workerId} not found`, error_code: 'WORKER_NOT_FOUND' }));
            return;
          }

          try {
            let queueDepth = 0;
            let status = 'unknown';
            let currentTask: { story_id: string; started_at: string } | null = null;
            if (fs.existsSync(jsonFile)) {
              const raw = JSON.parse(fs.readFileSync(jsonFile, 'utf8')) as {
                current_task?: { story_id: string; started_at: string };
                queue?: unknown[];
                status?: string;
              };
              queueDepth = (raw.queue ?? []).length;
              status = raw.current_task ? 'running' : (raw.status ?? 'idle');
              currentTask = raw.current_task ?? null;
            }
            res.end(JSON.stringify({
              id: workerId,
              worker_id: `worker-${workerId}`,
              hasLog: fs.existsSync(path.join(workersDir, `worker_${workerId}.log`)),
              hasHeartbeat: fs.existsSync(path.join(workersDir, `worker_${workerId}.heartbeat`)),
              hasJson: fs.existsSync(jsonFile),
              queue_depth: queueDepth,
              status,
              current_task: currentTask,
            }));
          } catch (e) {
            res.statusCode = 500;
            res.end(JSON.stringify({ error: String(e) }));
          }
          return;
        }

        // Default: list all workers — merges data from .spiral/workers/ (queue/log)
        // and .spiral-workers/worker-N/.heartbeat (live metrics)
        const url = new URL(req.url ?? '', 'http://localhost');
        const name = url.searchParams.get('name') ?? '';

        const reg = readRegistry();
        const root = name ? (reg[name] ?? null) : PROJECT_ROOT;
        if (!root) {
          res.statusCode = 404;
          res.end(JSON.stringify({ error: `Project "${name}" not found` }));
          return;
        }

        interface EnrichedWorker {
          id: number;
          hasLog: boolean;
          hasHeartbeat: boolean;
          hasJson: boolean;
          queue_depth: number;
          status: string;
          // Heartbeat fields
          mem_mb: number | null;
          node_mem_mb: number | null;
          pid: number | null;
          node_pid: number | null;
          phase: string | null;
          completed: number;
          current_story: string | null;
          heartbeat_ts: number | null;
          heartbeat_age_sec: number | null;
          last_progress_time: number | null;
          state: string;
          paused: boolean;
          status_reason: string;
          // Queue fields
          current_task: { story_id: string; started_at: string } | null;
          queued_stories: string[];
          uptime: number | null;
          started_at: string | null;
        }

        const workersDir = path.join(root, '.spiral', 'workers');
        const worktreeDir = path.join(root, '.spiral-workers');
        const scratchDir = path.join(root, '.spiral');
        const nowSec = Date.now() / 1000;
        const workerMap = new Map<number, EnrichedWorker>();

        const makeDefault = (id: number): EnrichedWorker => ({
          id, hasLog: false, hasHeartbeat: false, hasJson: false,
          queue_depth: 0, status: 'unknown',
          mem_mb: null, node_mem_mb: null, pid: null, node_pid: null,
          phase: null, completed: 0, current_story: null,
          heartbeat_ts: null, heartbeat_age_sec: null, last_progress_time: null,
          state: 'queued', paused: false, status_reason: '',
          current_task: null, queued_stories: [], uptime: null, started_at: null,
        });

        try {
          // 1. Scan .spiral/workers/ for log and queue JSON files
          if (fs.existsSync(workersDir)) {
            for (const f of fs.readdirSync(workersDir)) {
              const mLog = f.match(/^worker_(\d+)\.log$/);
              const mJson = f.match(/^worker_(\d+)\.json$/);
              if (mLog) {
                const id = parseInt(mLog[1]);
                const w = workerMap.get(id) ?? makeDefault(id);
                w.hasLog = true;
                w.hasHeartbeat = fs.existsSync(path.join(workersDir, `worker_${id}.heartbeat`));
                workerMap.set(id, w);
              } else if (mJson) {
                const id = parseInt(mJson[1]);
                const w = workerMap.get(id) ?? makeDefault(id);
                w.hasJson = true;
                try {
                  const raw = JSON.parse(fs.readFileSync(path.join(workersDir, f), 'utf8')) as {
                    current_task?: { story_id: string; started_at: string } | null;
                    queue?: { story_id: string }[];
                    uptime?: number;
                    phase?: string;
                  };
                  w.current_task = raw.current_task ?? null;
                  w.queued_stories = (raw.queue ?? []).map(q => q.story_id);
                  w.queue_depth = w.queued_stories.length;
                  w.uptime = raw.uptime ?? null;
                  w.status = raw.current_task ? 'running' : 'idle';
                  if (raw.current_task?.started_at) w.started_at = raw.current_task.started_at;
                  if (raw.phase) w.phase = raw.phase;
                } catch { /* ignore */ }
                workerMap.set(id, w);
              }
            }
          }

          // 2. Scan .spiral-workers/ for heartbeat files (live metrics)
          if (fs.existsSync(worktreeDir)) {
            for (const subdir of fs.readdirSync(worktreeDir)) {
              const idMatch = subdir.match(/^worker-(\d+)$/);
              if (!idMatch) continue;
              const id = parseInt(idMatch[1]);
              const hbFile = path.join(worktreeDir, subdir, '.heartbeat');
              if (!fs.existsSync(hbFile)) {
                // Worktree exists but no heartbeat — queued
                const w = workerMap.get(id) ?? makeDefault(id);
                if (w.state === 'unknown' || !w.hasHeartbeat) w.state = 'queued';
                workerMap.set(id, w);
                continue;
              }
              try {
                const hb = JSON.parse(fs.readFileSync(hbFile, 'utf8')) as {
                  pid?: number; storyId?: string; ts?: number; completed?: number;
                  phase?: string; memMb?: number; nodeMemMb?: number; nodePid?: number;
                  last_progress_time?: number;
                };
                const w = workerMap.get(id) ?? makeDefault(id);
                w.hasHeartbeat = true;
                w.pid = hb.pid ?? null;
                w.node_pid = hb.nodePid ?? null;
                w.mem_mb = hb.memMb ?? null;
                w.node_mem_mb = hb.nodeMemMb ?? null;
                w.phase = hb.phase ?? w.phase;
                w.completed = hb.completed ?? 0;
                w.current_story = hb.storyId ?? null;
                w.heartbeat_ts = hb.ts ?? null;
                w.last_progress_time = hb.last_progress_time ?? null;
                if (hb.ts) {
                  w.heartbeat_age_sec = Math.floor(nowSec - hb.ts);
                  // Check pause state
                  const pauseFile = path.join(scratchDir, `_worker_pause_${id}`);
                  if (fs.existsSync(pauseFile)) {
                    w.state = 'paused';
                    w.paused = true;
                    w.status_reason = 'Paused — memory pressure';
                  } else if (w.heartbeat_age_sec > 300) {
                    w.state = 'timeout';
                    w.status_reason = `No heartbeat for ${w.heartbeat_age_sec}s`;
                  } else {
                    w.state = 'alive';
                    w.status = 'running';
                  }
                }
                workerMap.set(id, w);
              } catch { /* ignore */ }
            }
          }
        } catch { /* ignore */ }

        const workers = [...workerMap.values()];
        workers.sort((a, b) => a.id - b.id);
        res.end(JSON.stringify({ workers }));
      });

      // ── GET /api/worker-stream/<id> — SSE stream of a worker's log file ───
      // Connect strips the '/api/worker-stream' prefix, so req.url = '/<id>'
      server.middlewares.use('/api/worker-stream', (req, res, next) => {
        if (req.method !== 'GET') { next(); return; }

        // Parse worker_id from URL (handles stripped or un-stripped prefix)
        const idMatch = (req.url ?? '').match(/\/(\d+)(?:\?|$)/);
        if (!idMatch) { next(); return; }
        const workerId = parseInt(idMatch[1]);

        // Resolve project root via optional ?name= query param
        const urlParsed = new URL(req.url ?? '', 'http://localhost');
        const name = urlParsed.searchParams.get('name') ?? '';
        const reg = readRegistry();
        const root = name ? (reg[name] ?? PROJECT_ROOT) : PROJECT_ROOT;

        const logFile = path.join(root, '.spiral', 'workers', `worker_${workerId}.log`);
        if (!fs.existsSync(logFile)) {
          res.statusCode = 404;
          res.setHeader('Content-Type', 'application/json');
          res.setHeader('Access-Control-Allow-Origin', '*');
          res.end(JSON.stringify({ error: `Worker ${workerId} log not found` }));
          return;
        }

        // SSE headers
        res.setHeader('Content-Type', 'text/event-stream');
        res.setHeader('Cache-Control', 'no-cache');
        res.setHeader('Connection', 'keep-alive');
        res.setHeader('Access-Control-Allow-Origin', '*');

        const sendEvent = (data: object) => {
          try { res.write(`data: ${JSON.stringify(data)}\n\n`); } catch { /* closed */ }
        };

        let offset = 0;
        let lastSizeChange = Date.now();
        let isDone = false;

        const finish = (status: string) => {
          if (isDone) return;
          isDone = true;
          sendEvent({ type: 'done', worker_id: workerId, status });
          fs.unwatchFile(logFile, watcher);
          clearInterval(staleTimer);
          try { res.end(); } catch { /* already closed */ }
        };

        const readNewContent = () => {
          if (isDone) return;
          try {
            const stat = fs.statSync(logFile);
            if (stat.size > offset) {
              const buf = Buffer.alloc(stat.size - offset);
              const fd = fs.openSync(logFile, 'r');
              fs.readSync(fd, buf, 0, buf.length, offset);
              fs.closeSync(fd);
              offset = stat.size;
              lastSizeChange = Date.now();

              const lines = buf.toString('utf8').split('\n');
              for (const line of lines) {
                if (!line.trim()) continue;
                sendEvent({ type: 'line', worker_id: workerId, data: line });
                // Detect Ralph session summary footer → worker finished
                if (line.includes('\u255a')) {
                  const tail = tailFile(logFile, 15);
                  const status = /Status:\s+ALL COMPLETE/.test(tail) ? 'passed'
                    : /Status:\s+\d+ stories remaining/.test(tail) ? 'failed'
                    : 'unknown';
                  setTimeout(() => finish(status), 100);
                  return;
                }
              }
            }
          } catch { /* file locked or deleted */ }
        };

        // Stale-detection fallback: if no content change for 30s, close stream
        const staleTimer = setInterval(() => {
          if (isDone) return;
          const heartbeatFile = path.join(root, '.spiral', 'workers', `worker_${workerId}.heartbeat`);
          if (Date.now() - lastSizeChange > 30_000 && !fs.existsSync(heartbeatFile)) {
            const tail = tailFile(logFile, 15);
            const status = /Status:\s+ALL COMPLETE/.test(tail) ? 'passed'
              : /Status:\s+\d+ stories remaining/.test(tail) ? 'failed'
              : 'unknown';
            finish(status);
          }
        }, 5_000);

        // Watch file for changes (500ms poll)
        const watcher = () => readNewContent();
        fs.watchFile(logFile, { interval: 500, persistent: false }, watcher);

        // Send existing content immediately
        readNewContent();

        // Clean up on client disconnect
        req.on('close', () => {
          isDone = true;
          fs.unwatchFile(logFile, watcher);
          clearInterval(staleTimer);
        });
      });

      // ── GET /api/events?name=X — SSE stream of new spiral_events.jsonl lines ──
      // US-374: Pushes each new JSONL line as an SSE data event using fs.watchFile.
      server.middlewares.use('/api/events', (req, res, next) => {
        if (req.method !== 'GET') { next(); return; }
        const url = new URL(req.url ?? '', 'http://localhost');
        const name = url.searchParams.get('name') ?? '';

        const reg = readRegistry();
        const root = name ? (reg[name] ?? PROJECT_ROOT) : PROJECT_ROOT;

        // Try .spiral/spiral_events.jsonl first, then root-level fallback
        const candidates = [
          path.join(root, '.spiral', 'spiral_events.jsonl'),
          path.join(root, 'spiral_events.jsonl'),
        ];
        const eventsFile = candidates.find(p => fs.existsSync(p)) ?? candidates[0];

        // SSE headers
        res.setHeader('Content-Type', 'text/event-stream');
        res.setHeader('Cache-Control', 'no-cache');
        res.setHeader('Connection', 'keep-alive');
        res.setHeader('Access-Control-Allow-Origin', '*');
        res.flushHeaders();

        let offset = 0;
        let closed = false;

        // Initialize offset to current file size (only stream NEW lines)
        try {
          if (fs.existsSync(eventsFile)) {
            offset = fs.statSync(eventsFile).size;
          }
        } catch { /* file doesn't exist yet, offset stays 0 */ }

        const sendEvent = (parsed: unknown) => {
          if (closed) return;
          try { res.write(`data: ${JSON.stringify(parsed)}\n\n`); } catch { /* closed */ }
        };

        const readNewLines = () => {
          if (closed) return;
          try {
            if (!fs.existsSync(eventsFile)) return;
            const stat = fs.statSync(eventsFile);
            if (stat.size <= offset) return;

            const buf = Buffer.alloc(stat.size - offset);
            const fd = fs.openSync(eventsFile, 'r');
            fs.readSync(fd, buf, 0, buf.length, offset);
            fs.closeSync(fd);
            offset = stat.size;

            for (const line of buf.toString('utf8').split('\n')) {
              if (!line.trim()) continue;
              try {
                const parsed = JSON.parse(line);
                sendEvent(parsed);
              } catch { /* skip malformed lines */ }
            }
          } catch { /* file locked or deleted */ }
        };

        // Watch file for changes (500ms poll interval, same as worker-stream)
        const watcher = () => readNewLines();
        fs.watchFile(eventsFile, { interval: 500, persistent: false }, watcher);

        // Send a heartbeat comment every 15s to keep connection alive through proxies
        const heartbeat = setInterval(() => {
          if (closed) return;
          try { res.write(': heartbeat\n\n'); } catch { /* closed */ }
        }, 15_000);

        // Clean up on client disconnect
        req.on('close', () => {
          closed = true;
          fs.unwatchFile(eventsFile, watcher);
          clearInterval(heartbeat);
        });
      });

      // ── GET /api/token-stats?name=X — aggregated token analytics ─────────────
      // Reads token_metrics.jsonl, story_costs.json, and results.tsv
      // Returns: { total, byModel, byStory[], byPhase[], trend[] }
      server.middlewares.use('/api/token-stats', (req: IncomingMessage, res: ServerResponse, next: () => void) => {
        if (req.method !== 'GET') { next(); return; }
        const url = new URL(req.url ?? '', 'http://localhost');
        const name = url.searchParams.get('name') ?? '';

        res.setHeader('Access-Control-Allow-Origin', '*');
        res.setHeader('Content-Type', 'application/json');

        const reg = readRegistry();
        const root = name ? (reg[name] ?? null) : PROJECT_ROOT;
        if (!root) {
          res.end(JSON.stringify({ error: 'Project not found' }));
          return;
        }

        try {
          // ── 1. Parse token_metrics.jsonl ─────────────────────────────────────
          interface TokenMetricRec {
            ts?: string;
            story_id?: string;
            phase?: string;
            model?: string;
            input_tokens?: number;
            output_tokens?: number;
            total_tokens?: number;
            duration_ms?: number;
          }
          const rawMetrics = readJsonl(path.join(root, '.spiral', 'token_metrics.jsonl')) as TokenMetricRec[];

          // Aggregate by story_id
          interface StoryAgg {
            story_id: string;
            input: number;
            output: number;
            total: number;
            calls: number;
            models: Set<string>;
            phases: Set<string>;
            ts: string;
          }
          const storyAgg: Record<string, StoryAgg> = {};
          const phaseAgg: Record<string, { input: number; output: number; total: number }> = {};
          const modelAgg: Record<string, { input: number; output: number; total: number; stories: number }> = {};
          const trendPoints: Array<{ ts: string; input: number; output: number; total: number; cumTotal: number }> = [];
          let cumTotal = 0;

          for (const r of rawMetrics) {
            const sid = r.story_id ?? 'unknown';
            const phase = r.phase ?? 'I';
            const model = r.model ?? 'unknown';
            const inp = r.input_tokens ?? 0;
            const out = r.output_tokens ?? 0;
            const tot = r.total_tokens ?? (inp + out);
            const ts = r.ts ?? '';

            // Per-story
            if (!storyAgg[sid]) storyAgg[sid] = { story_id: sid, input: 0, output: 0, total: 0, calls: 0, models: new Set(), phases: new Set(), ts };
            storyAgg[sid].input += inp;
            storyAgg[sid].output += out;
            storyAgg[sid].total += tot;
            storyAgg[sid].calls += 1;
            if (model !== 'unknown') storyAgg[sid].models.add(model);
            storyAgg[sid].phases.add(phase);

            // Per-phase
            if (!phaseAgg[phase]) phaseAgg[phase] = { input: 0, output: 0, total: 0 };
            phaseAgg[phase].input += inp;
            phaseAgg[phase].output += out;
            phaseAgg[phase].total += tot;

            // Per-model
            if (!modelAgg[model]) modelAgg[model] = { input: 0, output: 0, total: 0, stories: 0 };
            modelAgg[model].input += inp;
            modelAgg[model].output += out;
            modelAgg[model].total += tot;
            modelAgg[model].stories += 1;

            // Trend (cumulative)
            cumTotal += tot;
            trendPoints.push({ ts, input: inp, output: out, total: tot, cumTotal });
          }

          // ── 2. Enrich with story_costs.json (USD estimates) ──────────────────
          interface StoryCostRec { tokens_input?: number; tokens_output?: number; estimated_usd?: number }
          const storyCostsPath = path.join(root, '.spiral', 'story_costs.json');
          const storyCosts: Record<string, StoryCostRec> = (() => {
            try {
              if (fs.existsSync(storyCostsPath)) return JSON.parse(fs.readFileSync(storyCostsPath, 'utf8')) as Record<string, StoryCostRec>;
            } catch { /* ignore */ }
            return {};
          })();

          // ── 3. Enrich with results.tsv (model/status per story) ──────────────
          const tsvPath = path.join(root, 'results.tsv');
          const tsvModelMap: Record<string, string> = {};
          const tsvStatusMap: Record<string, string> = {};
          const tsvTitleMap: Record<string, string> = {};
          if (fs.existsSync(tsvPath)) {
            try {
              const tsvLines = fs.readFileSync(tsvPath, 'utf8').split('\n').filter(Boolean);
              // Header: timestamp(0) spiral_iter(1) ralph_iter(2) story_id(3) story_title(4) status(5) duration_sec(6) model(7)
              for (let i = 1; i < tsvLines.length; i++) {
                const cols = tsvLines[i].split('\t');
                const sid = cols[3] ?? '';
                if (!sid) continue;
                const mdl = cols[7] ?? '';
                const sts = cols[5] ?? '';
                const ttl = cols[4] ?? '';
                if (mdl) tsvModelMap[sid] = mdl;
                if (sts) tsvStatusMap[sid] = sts;
                if (ttl) tsvTitleMap[sid] = ttl;
              }
            } catch { /* ignore */ }
          }

          // ── 3b. Parse prd.json for passes status ────────────────────────────
          interface PrdStoryMin { id: string; passes?: boolean; title?: string }
          const prdPath = path.join(root, 'prd.json');
          const passedSet = new Set<string>();
          const prdTitleMap: Record<string, string> = {};
          if (fs.existsSync(prdPath)) {
            try {
              const prdData = JSON.parse(fs.readFileSync(prdPath, 'utf8')) as { userStories?: PrdStoryMin[] };
              for (const s of prdData.userStories ?? []) {
                if (s.passes) passedSet.add(s.id);
                if (s.title) prdTitleMap[s.id] = s.title;
              }
            } catch { /* ignore */ }
          }

          // ── 4. Build output structures ────────────────────────────────────────

          // Helper: extract model tier from full model name
          const modelTier = (m: string): string => {
            if (!m || m === 'unknown') return 'unknown';
            const lm = m.toLowerCase();
            if (lm.includes('haiku')) return 'haiku';
            if (lm.includes('sonnet')) return 'sonnet';
            if (lm.includes('opus')) return 'opus';
            return m.split('-').slice(-1)[0] ?? m;
          };

          // byStory: merge storyAgg + storyCosts
          const byStory = Object.values(storyAgg).map(s => {
            const costRec = storyCosts[s.story_id];
            const usd = costRec?.estimated_usd ?? 0;
            const primaryModel = (() => {
              // Prefer TSV model, else first from Set
              if (tsvModelMap[s.story_id]) return tsvModelMap[s.story_id];
              const arr = Array.from(s.models);
              return arr[0] ?? 'unknown';
            })();
            return {
              story_id: s.story_id,
              title: tsvTitleMap[s.story_id] ?? '',
              input: s.input,
              output: s.output,
              total: s.total,
              calls: s.calls,
              usd,
              model: primaryModel,
              model_tier: modelTier(primaryModel),
              status: tsvStatusMap[s.story_id] ?? 'unknown',
            };
          }).sort((a, b) => b.total - a.total);

          // Also add stories from story_costs that might not be in token_metrics
          for (const [sid, costRec] of Object.entries(storyCosts)) {
            if (!storyAgg[sid] && (costRec.estimated_usd ?? 0) > 0) {
              const inp = costRec.tokens_input ?? 0;
              const out = costRec.tokens_output ?? 0;
              byStory.push({
                story_id: sid,
                title: tsvTitleMap[sid] ?? '',
                input: inp,
                output: out,
                total: inp + out,
                calls: 1,
                usd: costRec.estimated_usd ?? 0,
                model: tsvModelMap[sid] ?? 'unknown',
                model_tier: modelTier(tsvModelMap[sid] ?? ''),
                status: tsvStatusMap[sid] ?? 'unknown',
              });
            }
          }

          // byPhase
          const byPhase = Object.entries(phaseAgg).map(([phase, v]) => ({ phase, ...v }));

          // byModel
          const byModel = Object.entries(modelAgg).map(([model, v]) => ({
            model,
            tier: modelTier(model),
            ...v,
          }));

          // Summary totals
          const totalInput = byStory.reduce((s, r) => s + r.input, 0);
          const totalOutput = byStory.reduce((s, r) => s + r.output, 0);
          const totalTokens = byStory.reduce((s, r) => s + r.total, 0);
          const totalUsd = byStory.reduce((s, r) => s + r.usd, 0)
            || Object.values(storyCosts).reduce((s, r) => s + (r.estimated_usd ?? 0), 0);
          const avgPerStory = byStory.length > 0 ? Math.round(totalTokens / byStory.length) : 0;
          const mostExpensive = [...byStory].sort((a, b) => b.usd - a.usd)[0] ?? null;

          // ── 5. Recently completed stories with per-call breakdown ────────────
          // Group raw metric records by story_id, filter for passed stories,
          // sort by most recent timestamp descending
          const callsByStory = new Map<string, Array<{ ts: string; model: string; tier: string; input: number; output: number; total: number }>>();
          for (const r of rawMetrics) {
            const sid = r.story_id ?? 'unknown';
            const model = r.model ?? 'unknown';
            if (model === 'unknown' || !r.total_tokens) continue; // skip zero-token "unknown" rows
            if (!callsByStory.has(sid)) callsByStory.set(sid, []);
            callsByStory.get(sid)!.push({
              ts: r.ts ?? '',
              model,
              tier: modelTier(model),
              input: r.input_tokens ?? 0,
              output: r.output_tokens ?? 0,
              total: r.total_tokens ?? 0,
            });
          }

          const recentlyCompleted = [...callsByStory.entries()]
            .filter(([sid]) => passedSet.has(sid))
            .map(([sid, calls]) => {
              const models = [...new Set(calls.map(c => c.tier))];
              const totalInput = calls.reduce((s, c) => s + c.input, 0);
              const totalOutput = calls.reduce((s, c) => s + c.output, 0);
              const totalTokens = calls.reduce((s, c) => s + c.total, 0);
              const lastTs = calls.reduce((latest, c) => c.ts > latest ? c.ts : latest, '');
              const costRec = storyCosts[sid];
              return {
                story_id: sid,
                title: prdTitleMap[sid] ?? tsvTitleMap[sid] ?? '',
                models,
                input: totalInput,
                output: totalOutput,
                total: totalTokens,
                usd: costRec?.estimated_usd ?? 0,
                callCount: calls.length,
                lastTs,
                calls: calls.sort((a, b) => a.ts.localeCompare(b.ts)),
              };
            })
            .sort((a, b) => b.lastTs.localeCompare(a.lastTs))
            .slice(0, 15);

          res.end(JSON.stringify({
            total: { input: totalInput, output: totalOutput, tokens: totalTokens, usd: totalUsd },
            avgPerStory,
            mostExpensive: mostExpensive ? { story_id: mostExpensive.story_id, title: mostExpensive.title, usd: mostExpensive.usd } : null,
            byModel,
            byStory: byStory.slice(0, 20), // top 20
            byPhase,
            trend: trendPoints,
            recentlyCompleted,
          }));
        } catch (e) {
          res.statusCode = 500;
          res.end(JSON.stringify({ error: String(e) }));
        }
      });

      // ── GET /api/analytics?name=X — aggregated analytics for dashboard ──────
      server.middlewares.use('/api/analytics', (req: IncomingMessage, res: ServerResponse, next: () => void) => {
        if (req.method !== 'GET') { next(); return; }
        const url = new URL(req.url ?? '', 'http://localhost');
        const name = url.searchParams.get('name') ?? '';

        res.setHeader('Access-Control-Allow-Origin', '*');
        res.setHeader('Content-Type', 'application/json');

        const reg = readRegistry();
        const root = name ? (reg[name] ?? null) : PROJECT_ROOT;
        if (!root) {
          res.end(JSON.stringify({ error: 'Project not found' }));
          return;
        }

        handleAnalytics(root, res);
      });

      // ── GET /api/dashboard/overview — unified cross-project metrics ─────────
      // Aggregates results.tsv from all registered projects (or a single project
      // if ?name=X is given). Returns {totalCost, storiesPassed, avgPhaseTime,
      // blockerCount, slowestSubProject}. Re-reads files on every request so
      // metrics reflect the latest results.tsv state.
      server.middlewares.use('/api/dashboard/overview', (req: IncomingMessage, res: ServerResponse, next: () => void) => {
        if (req.method !== 'GET') { next(); return; }
        res.setHeader('Access-Control-Allow-Origin', '*');
        res.setHeader('Content-Type', 'application/json');

        try {
          const url = new URL(req.url ?? '', 'http://localhost');
          const filterName = url.searchParams.get('name') ?? '';
          const reg = readRegistry();

          // Build list of (projectKey, results.tsv path) pairs
          const projectPaths: Array<{ key: string; tsvPath: string }> = filterName
            ? [{ key: filterName, tsvPath: path.join(reg[filterName] ?? PROJECT_ROOT, 'results.tsv') }]
            : Object.entries(reg).map(([name, root]) => ({ key: name, tsvPath: path.join(root, 'results.tsv') }));

          // Cost rate table (USD per 1M tokens) — mirrors Python aggregator
          const COST_PER_M: Record<string, number> = { haiku: 0.25, sonnet: 3.0, opus: 15.0 };

          const estimateCost = (row: Record<string, string>): number => {
            const model = (row['model'] ?? 'sonnet').toLowerCase();
            const rate = COST_PER_M[model] ?? 3.0;
            const inputTok = (parseFloat(row['cache_read_tokens'] ?? '0') || 0) + (parseFloat(row['cache_creation_tokens'] ?? '0') || 0);
            const outputTok = parseFloat(row['review_tokens'] ?? '0') || 0;
            return (inputTok + outputTok) / 1_000_000 * rate;
          };

          const readTsv = (tsvPath: string): Array<Record<string, string>> => {
            if (!fs.existsSync(tsvPath)) return [];
            try {
              const lines = fs.readFileSync(tsvPath, 'utf8').split('\n').filter(Boolean);
              if (lines.length < 2) return [];
              const headers = lines[0].split('\t');
              return lines.slice(1).map(line => {
                const cols = line.split('\t');
                const row: Record<string, string> = {};
                for (let j = 0; j < headers.length; j++) row[headers[j]] = cols[j] ?? '';
                return row;
              });
            } catch { return []; }
          };

          let totalCost = 0.0;
          let storiesPassed = 0;
          let blockerCount = 0;
          const allDurations: number[] = [];
          const projectAvgDurations: Record<string, number[]> = {};
          let allRows: Array<Record<string, string>> = [];

          for (const { key, tsvPath } of projectPaths) {
            const rows = readTsv(tsvPath);
            projectAvgDurations[key] = [];
            for (const row of rows) {
              totalCost += estimateCost(row);
              const dur = parseFloat(row['duration_sec'] ?? '0') || 0;
              allDurations.push(dur);
              projectAvgDurations[key].push(dur);
              if ((row['status'] ?? '').toLowerCase() === 'keep') storiesPassed++;
              else blockerCount++;
            }
            allRows = allRows.concat(rows);
          }

          const avgPhaseTime = allDurations.length > 0
            ? allDurations.reduce((s, d) => s + d, 0) / allDurations.length
            : 0.0;

          let slowestSubProject = '';
          let slowestAvg = -1;
          for (const [key, durs] of Object.entries(projectAvgDurations)) {
            if (durs.length > 0) {
              const avg = durs.reduce((s, d) => s + d, 0) / durs.length;
              if (avg > slowestAvg) { slowestAvg = avg; slowestSubProject = key; }
            }
          }

          res.end(JSON.stringify({
            totalCost: Math.round(totalCost * 1_000_000) / 1_000_000,
            storiesPassed,
            avgPhaseTime: Math.round(avgPhaseTime * 1000) / 1000,
            blockerCount,
            slowestSubProject,
          }));
        } catch (e) {
          res.statusCode = 500;
          res.end(JSON.stringify({ error: String(e) }));
        }
      });

      // ── GET /api/dashboard/cross-project-dependency-graph ───────────────────
      server.middlewares.use('/api/dashboard/cross-project-dependency-graph', (req: IncomingMessage, res: ServerResponse, next: () => void) => {
        if (req.method !== 'GET') { next(); return; }
        res.setHeader('Access-Control-Allow-Origin', '*');
        res.setHeader('Content-Type', 'application/json');
        const url = new URL(req.url ?? '', 'http://localhost');
        const name = url.searchParams.get('name') ?? '';
        const reg = readRegistry();
        const root = name ? (reg[name] ?? PROJECT_ROOT) : PROJECT_ROOT;
        try {
          interface PS { id: string; title?: string; passes?: boolean; sub_project?: string; dependencies?: string[]; }
          const prdPath = path.join(root, 'prd.json');
          if (!fs.existsSync(prdPath)) { res.end(JSON.stringify({ sub_projects: [], nodes: [], edges: [] })); return; }
          const stories: PS[] = (JSON.parse(fs.readFileSync(prdPath, 'utf8')) as { userStories?: PS[] }).userStories ?? [];
          const sm = new Map(stories.map(s => [s.id, s]));
          const nodes = stories.filter(s => s.sub_project).map(s => ({ id: s.id, title: s.title ?? s.id, sub_project: s.sub_project as string, passes: s.passes ?? false }));
          const edges: Array<{ from: string; to: string; from_project: string; to_project: string; reason: string }> = [];
          for (const s of stories) {
            const sp = s.sub_project;
            if (!sp) continue;
            for (const dep of (s.dependencies ?? [])) {
              const d = sm.get(dep);
              if (d?.sub_project && d.sub_project !== sp) {
                edges.push({ from: dep, to: s.id, from_project: d.sub_project, to_project: sp, reason: `${s.id} requires ${dep}` });
              }
            }
          }
          const sub_projects = [...new Set(nodes.map(n => n.sub_project))];
          res.end(JSON.stringify({ sub_projects, nodes, edges }));
        } catch (e) {
          res.statusCode = 500;
          res.end(JSON.stringify({ error: String(e) }));
        }
      });

      // ── GET /api/dashboard/worker-resources — worker CPU/memory metrics ────────
      server.middlewares.use('/api/dashboard/worker-resources', (req: IncomingMessage, res: ServerResponse, next: () => void) => {
        if (req.method !== 'GET') { next(); return; }
        res.setHeader('Access-Control-Allow-Origin', '*');
        res.setHeader('Content-Type', 'application/json');
        const name = new URL(req.url ?? '', 'http://localhost').searchParams.get('name') ?? '';
        const root = name ? (readRegistry()[name] ?? PROJECT_ROOT) : PROJECT_ROOT;
        const sd = path.join(root, '.spiral');
        try {
          interface WH { worker_id?: string; memory_peak_mb?: number; avg_cpu_percent?: number; stories_completed?: number; uptime_seconds?: number; }
          const hbFile = path.join(sd, 'worker_heartbeats.json');
          const metrics = fs.existsSync(hbFile)
            ? Object.entries(JSON.parse(fs.readFileSync(hbFile, 'utf8')) as Record<string, WH>).map(([wid, d]) => ({
                worker_id: String(d.worker_id ?? wid), memory_peak_mb: Number(d.memory_peak_mb ?? 0),
                avg_cpu_percent: Number(d.avg_cpu_percent ?? 0), stories_completed: Number(d.stories_completed ?? 0),
                uptime_seconds: Number(d.uptime_seconds ?? 0),
              }))
            : [];
          const histFile = path.join(sd, 'worker-resources-history.json');
          let hist: Array<{ timestamp: string; workers: typeof metrics }> = [];
          if (fs.existsSync(histFile)) { try { hist = JSON.parse(fs.readFileSync(histFile, 'utf8')) as typeof hist; } catch { /* */ } }
          hist.push({ timestamp: new Date().toISOString(), workers: metrics });
          try { fs.writeFileSync(histFile, JSON.stringify(hist, null, 2)); } catch { /* */ }
          res.end(JSON.stringify(metrics));
        } catch (e) { res.statusCode = 500; res.end(JSON.stringify({ error: String(e) })); }
      });

      // ── GET /api/tests?name=X — list all pytest test IDs ────────────────────
      server.middlewares.use('/api/tests', (req: IncomingMessage, res: ServerResponse, next: () => void) => {
        if (req.method !== 'GET') { next(); return; }
        const url = new URL(req.url ?? '', 'http://localhost');
        const name = url.searchParams.get('name') ?? '';
        res.setHeader('Access-Control-Allow-Origin', '*');
        res.setHeader('Content-Type', 'application/json');
        const reg = readRegistry();
        const root = name ? (reg[name] ?? PROJECT_ROOT) : PROJECT_ROOT;
        try {
          const result = spawnSync(
            'uv',
            ['run', 'pytest', 'tests/', '--collect-only', '-q', '--no-header', '--color=no', '--ignore=tests/bats-core'],
            { cwd: root, timeout: 30_000, encoding: 'utf8' }
          );
          interface TItem { id: string; cls: string; name: string; }
          interface TFile { name: string; path: string; tests: TItem[]; }
          const fileMap = new Map<string, TFile>();
          const stdout: string = (result.stdout as string) ?? '';
          for (const rawLine of stdout.split('\n')) {
            const line = rawLine.trim();
            if (!line.includes('::')) continue;
            const parts = line.split('::');
            const filePath = parts[0];
            const fileName = filePath.split(/[/\\]/).pop() ?? filePath;
            const cls = parts.length === 3 ? parts[1] : '';
            const testName = parts[parts.length - 1];
            if (!fileMap.has(filePath)) fileMap.set(filePath, { name: fileName, path: filePath, tests: [] });
            fileMap.get(filePath)!.tests.push({ id: line, cls, name: testName });
          }
          const files = Array.from(fileMap.values());
          const total = files.reduce((s, f) => s + f.tests.length, 0);
          res.end(JSON.stringify({ files, total }));
        } catch (e) {
          res.statusCode = 500;
          res.end(JSON.stringify({ error: String(e) }));
        }
      });

      // ── POST /api/run-tests — run selected pytest tests ──────────────────────
      server.middlewares.use('/api/run-tests', (req: IncomingMessage, res: ServerResponse, next: () => void) => {
        if (req.method !== 'POST') { next(); return; }
        res.setHeader('Access-Control-Allow-Origin', '*');
        res.setHeader('Content-Type', 'application/json');
        let body = '';
        req.on('data', (chunk: Buffer) => { body += chunk.toString(); });
        req.on('end', () => {
          try {
            interface RunBody { name?: string; testIds?: string[]; }
            const parsed = JSON.parse(body || '{}') as RunBody;
            const name = parsed.name ?? '';
            const testIds: string[] = parsed.testIds ?? [];
            const reg = readRegistry();
            const root = name ? (reg[name] ?? PROJECT_ROOT) : PROJECT_ROOT;
            const args = ['run', 'pytest', '--tb=short', '-v', '--no-header', '--color=no'];
            if (testIds.length > 0) {
              args.push(...testIds);
            } else {
              args.push('tests/', '--ignore=tests/bats-core');
            }
            const result = spawnSync('uv', args, {
              cwd: root,
              timeout: 300_000,
              encoding: 'utf8',
            });
            const stdout: string = (result.stdout as string) ?? '';
            const stderr: string = (result.stderr as string) ?? '';
            const output = stdout + (stderr ? `\n--- stderr ---\n${stderr}` : '');
            // Parse summary: "X passed, Y failed in Zs" or "X passed in Zs"
            const sumMatch = output.match(/(\d+)\s+passed(?:,\s*(\d+)\s+failed)?(?:,\s*(\d+)\s+error(?:s)?)?/);
            const passed = sumMatch ? parseInt(sumMatch[1]) : 0;
            const failed = sumMatch ? parseInt(sumMatch[2] ?? '0') : 0;
            const errors = sumMatch ? parseInt(sumMatch[3] ?? '0') : 0;
            // Parse per-test results from verbose output
            const testResults: Record<string, string> = {};
            for (const line of output.split('\n')) {
              const m = line.match(/^(PASSED|FAILED|ERROR)\s+(.+?)(?:\s+-\s+.*)?$/);
              if (m) testResults[m[2].trim()] = m[1].toLowerCase();
            }
            res.end(JSON.stringify({ output, passed, failed, errors, total: passed + failed + errors, testResults }));
          } catch (e) {
            res.statusCode = 500;
            res.end(JSON.stringify({ error: String(e) }));
          }
        });
      });
    },
  };
}

export default defineConfig({
  server: {
    port: 5299,
    strictPort: false, // auto-increment if 5299 is taken
  },
  plugins: [
    tailwindcss(),
    react(),
    spiralApiPlugin(),
  ],
})
