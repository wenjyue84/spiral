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
