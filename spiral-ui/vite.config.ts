import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import fs from 'node:fs'
import path from 'node:path'
import os from 'node:os'
import type { IncomingMessage, ServerResponse } from 'node:http'

// ── Spiral API plugin ──────────────────────────────────────────────────────────
// Provides endpoints for config saving and the project dashboard:
//   GET  /api/project                → { projectRoot }
//   POST /api/save-config            → writes spiral.config.sh
//   GET  /api/projects               → list of registered projects
//   POST /api/register-project       → register { name, root }
//   GET  /api/project-live?name=X    → full live data for dashboard

const PROJECTS_FILE = path.join(os.homedir(), '.spiral', 'ui-projects.json');

function readRegistry(): Record<string, string> {
  try {
    if (fs.existsSync(PROJECTS_FILE)) {
      return JSON.parse(fs.readFileSync(PROJECTS_FILE, 'utf8')) as Record<string, string>;
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
            const { content } = JSON.parse(body) as { content: string };
            const configPath = path.join(PROJECT_ROOT, 'spiral.config.sh');
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

      // ── GET /api/projects — list registered projects ─────────────────────
      server.middlewares.use('/api/projects', (req, res, next) => {
        if (req.method !== 'GET') { next(); return; }
        res.setHeader('Content-Type', 'application/json');
        res.setHeader('Access-Control-Allow-Origin', '*');
        const reg = readRegistry();
        const projects = Object.entries(reg).map(([name, root]) => ({ name, root }));
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
          // Parse _last_run.log into iterations and phases
          const logPath = path.join(root, '.spiral', '_last_run.log');
          const logText = fs.existsSync(logPath)
            ? fs.readFileSync(logPath, 'utf8').replace(/\0/g, '')
            : '';

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

          type PhaseEvent = { event?: string; type?: string; phase?: string; iteration?: number; duration_s?: number; ts?: string; [k: string]: unknown };
          const phaseEvents = (rawEvents as PhaseEvent[]).filter(
            e => e.event === 'phase_start' || e.event === 'phase_end' ||
                 e.type === 'phase_start' || e.type === 'phase_end'
          );

          // Parse iterations from the log
          type IterPhase = { phase: string; label: string; lines: string[]; lineStart: number; lineEnd: number; substeps: { id: string; label: string; lines: string[]; lineStart: number; lineEnd: number }[] };
          type Iteration = { iter: number; phases: IterPhase[]; lineStart: number; lineEnd: number };

          const iterations: Iteration[] = [];
          const lines = logText.split('\n');

          // Pattern: "SPIRAL Iteration N / M"
          const iterRe = /SPIRAL Iteration (\d+)\s*\/\s*(\d+)/;
          // Pattern: "[Phase X] LABEL" or "[Phase X / sub] LABEL" — X can be A-Z or 0
          const phaseRe = /\[Phase ([A-Z0-9])\]\s*(.*?)(?:\s*[—–-]\s*(.*))?$/;
          // Pattern: "[Phase X / substep] text" — sub-stages within a phase
          const subStepRe = /\[Phase ([A-Z0-9])\s*\/\s*(\w+)\]\s*(.*)/;
          // Pattern: "[Phase X.N] text" — numbered sub-phases (e.g. I.5)
          const subPhaseRe = /\[Phase ([A-Z0-9])\.(\d+)\]\s*(.*)/;
          // Pattern: "[0-A] text" through "[0-E] text" — Phase 0 sub-phases
          const phase0SubRe = /\[0-([A-E])\]\s*(.*)/;
          // Pattern: "[X] short text" — short-form markers
          const phaseShortRe = /\[([A-Z0-9])\]\s+(Looping back|All current|Not done|Skipping|Pushed|WARNING|Velocity)/;
          // Pattern: "[tag]", "[test-ratchet]", "[security-scan]", "[CAPACITY]" — quality gates
          const qualityGateRe = /\[(test-ratchet|security-scan|tag|CAPACITY)\]\s*(.*)/;
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
          const dedupedIterations = [...iterMap.values()].sort((a, b) => a.iter - b.iter);

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

          // prd.json
          let progress = null;
          const prdPath = path.join(root, 'prd.json');
          if (fs.existsSync(prdPath)) {
            try {
              const prd = JSON.parse(fs.readFileSync(prdPath, 'utf8')) as {
                productName?: string;
                overview?: string;
                userStories?: Array<{ id: string; title: string; passes: boolean; priority?: string; complexity?: string; _failureReason?: string; dependencies?: string[]; _status?: string }>;
              };
              const stories = (prd.userStories ?? []).map(s => ({
                id: s.id,
                title: s.title,
                passes: s.passes,
                priority: s.priority,
                complexity: s.complexity,
                failureReason: s._failureReason,
                dependencies: s.dependencies,
                status: s._status,
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

          // Last completed story from results.tsv (last row with status=pass)
          let lastCompletedStory: { id: string; title: string; timestamp: string; model: string; duration: number } | null = null;
          const tsvPath = path.join(root, 'results.tsv');
          if (fs.existsSync(tsvPath)) {
            try {
              const tsvLines = fs.readFileSync(tsvPath, 'utf8').split('\n').filter(Boolean);
              for (let i = 1; i < tsvLines.length; i++) {
                const cols = tsvLines[i].split('\t');
                if (cols[5] === 'pass') {
                  lastCompletedStory = { id: cols[3], title: cols[4], timestamp: cols[0], model: cols[7] ?? '', duration: parseInt(cols[6]) || 0 };
                }
              }
            } catch { /* ignore */ }
          }

          // Fallback: check story_passed events from spiral_events.jsonl
          if (!lastCompletedStory) {
            const storyEvents = [...rawEvents, ...readJsonl(path.join(root, 'spiral_events.jsonl'))];
            for (const ev of storyEvents) {
              const e = ev as { event?: string; storyId?: string; ts?: string; model?: string };
              if (e.event === 'story_passed' && e.ts) {
                if (!lastCompletedStory || e.ts > lastCompletedStory.timestamp) {
                  lastCompletedStory = { id: e.storyId ?? '', title: '', timestamp: e.ts, model: e.model ?? '', duration: 0 };
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

          res.end(JSON.stringify({
            name,
            root,
            lastSeen,
            progress,
            config,
            constitution,
            activity,
            progressHistory,
            tokenBurn,
            cacheStats,
            lastCompletedStory,
            checkpointTs,
            lastLogModified,
          }));
        } catch (e) {
          res.statusCode = 500;
          res.end(JSON.stringify({ error: String(e) }));
        }
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
