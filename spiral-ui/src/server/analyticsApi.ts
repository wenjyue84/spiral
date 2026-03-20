import fs from 'node:fs';
import path from 'node:path';
import type { ServerResponse } from 'node:http';

// ── Types ──────────────────────────────────────────────────────────────────────

interface TsvRow {
  timestamp: string; spiral_iter: number; ralph_iter: number;
  story_id: string; story_title: string; status: string;
  duration_sec: number; model: string; retry_num: number;
  commit_sha: string; run_id: string; cache_hit: number;
  cache_read_tokens: number; cache_creation_tokens: number;
  review_tokens: number; wall_seconds: number;
  user_cpu_s: number; sys_cpu_s: number; peak_rss_kb: number;
  batch_id: string; input_tokens: number; output_tokens: number;
}

interface PrdStory {
  id: string; title?: string; passes?: boolean; _decomposed?: boolean;
  _decomposedFrom?: string; _decomposedInto?: string[];
  _skipped?: boolean; _failureReason?: string; _scopeCreep?: boolean;
  epicId?: string; last_attempted?: string; completedAt?: string;
  dependencies?: string[]; model?: string; _source?: string;
  estimatedComplexity?: string; priority?: string;
}

interface PrdData { userStories?: PrdStory[]; epics?: Array<{ id: string; title?: string }>; }

type FailureCategory = 'cost_ceiling' | 'dependency_blocked' | 'too_large' | 'rejected' | 'never_attempted' | 'pending_retry';

interface EnrichedFailure {
  id: string; title: string; reason: string; category: FailureCategory;
  retryCount: number; model: string; source: string; complexity: string;
  priority: string; dependencies: string[]; depsStatus: Array<{ id: string; met: boolean }>;
  lastAttempted: string | null; attemptCount: number;
  lastModel: string | null; lastStatus: string | null; lastDurationSec: number | null;
  scopeCreep: boolean; recommendation: string;
}

type ResolvedStatus = 'passed' | 'skipped' | 'decomposed';

interface ResolvedFailure {
  id: string; title: string; reason: string; category: FailureCategory;
  retryCount: number; model: string; source: string;
  resolvedAs: ResolvedStatus;
}

interface AgentTelemetryEntry {
  ts: string; workerId: string; storyId: string;
  fromPhase: string; toPhase: string;
  durationMs: number; qualityScore: number; retryCount: number;
}

interface PhaseTiming {
  phase: string; durationSec: number; label: string;
}

// ── Helpers ────────────────────────────────────────────────────────────────────

const percentile = (arr: number[], p: number): number => {
  if (arr.length === 0) return 0;
  const sorted = [...arr].sort((a, b) => a - b);
  const idx = Math.max(0, Math.ceil(sorted.length * p) - 1);
  return sorted[idx];
};

const COST_PER_HOUR: Record<string, number> = { haiku: 0.04, sonnet: 0.24, opus: 2.40 };

const modelTier = (m: string): string => {
  if (!m) return 'unknown';
  const lm = m.toLowerCase();
  if (lm.includes('haiku')) return 'haiku';
  if (lm.includes('sonnet')) return 'sonnet';
  if (lm.includes('opus')) return 'opus';
  return 'unknown';
};

const PHASE_LABELS: Record<string, string> = {
  R: 'Research', T: 'Test Synth', S: 'Story Valid',
  M: 'Merge', I: 'Implement', V: 'Validate', C: 'Check Done',
};

// ── Main handler ───────────────────────────────────────────────────────────────

export function handleAnalytics(root: string, res: ServerResponse): void {
  try {
    // ── Parse results.tsv (header-based) ──────────────────────────────────
    const results: TsvRow[] = [];
    const tsvPath = path.join(root, 'results.tsv');
    if (fs.existsSync(tsvPath)) {
      const lines = fs.readFileSync(tsvPath, 'utf8').split('\n').filter(Boolean);
      if (lines.length > 1) {
        const headers = lines[0].split('\t');
        for (let i = 1; i < lines.length; i++) {
          const cols = lines[i].split('\t');
          const row: Record<string, string> = {};
          for (let j = 0; j < headers.length; j++) {
            row[headers[j]] = cols[j] ?? '';
          }
          results.push({
            timestamp: row['timestamp'] ?? '',
            spiral_iter: parseInt(row['spiral_iter']) || 0,
            ralph_iter: parseInt(row['ralph_iter']) || 0,
            story_id: row['story_id'] ?? '',
            story_title: row['story_title'] ?? '',
            status: row['status'] ?? '',
            duration_sec: parseFloat(row['duration_sec']) || 0,
            model: row['model'] ?? '',
            retry_num: parseInt(row['retry_num']) || 0,
            commit_sha: row['commit_sha'] ?? '',
            run_id: row['run_id'] ?? '',
            cache_hit: parseInt(row['cache_hit']) || 0,
            cache_read_tokens: parseInt(row['cache_read_tokens']) || 0,
            cache_creation_tokens: parseInt(row['cache_creation_tokens']) || 0,
            review_tokens: parseInt(row['review_tokens']) || 0,
            wall_seconds: parseFloat(row['wall_seconds']) || 0,
            user_cpu_s: parseFloat(row['user_cpu_s']) || 0,
            sys_cpu_s: parseFloat(row['sys_cpu_s']) || 0,
            peak_rss_kb: parseFloat(row['peak_rss_kb']) || 0,
            batch_id: row['batch_id'] ?? '',
            input_tokens: parseInt(row['input_tokens']) || 0,
            output_tokens: parseInt(row['output_tokens']) || 0,
          });
        }
      }
    }

    // ── Parse prd.json ────────────────────────────────────────────────────
    let prd: PrdData = {};
    const prdPath = path.join(root, 'prd.json');
    if (fs.existsSync(prdPath)) {
      try { prd = JSON.parse(fs.readFileSync(prdPath, 'utf8')) as PrdData; } catch { /* ignore */ }
    }
    const stories = prd.userStories ?? [];

    // ── Parse retry-counts.json ───────────────────────────────────────────
    let retryCounts: Record<string, number> = {};
    const retryPath = path.join(root, 'retry-counts.json');
    if (fs.existsSync(retryPath)) {
      try { retryCounts = JSON.parse(fs.readFileSync(retryPath, 'utf8')) as Record<string, number>; } catch { /* ignore */ }
    }

    // ── Parse _checkpoint.json for quality scores ─────────────────────────
    let qualityScores: Array<{ phase: string; avgScore: number; latest: number; n: number; rationale: string }> = [];
    const ckptPath = path.join(root, '.spiral', '_checkpoint.json');
    if (fs.existsSync(ckptPath)) {
      try {
        const ckpt = JSON.parse(fs.readFileSync(ckptPath, 'utf8')) as Record<string, unknown>;
        const qs = ckpt['_qualityScores'];
        if (qs && typeof qs === 'object') {
          for (const [phase, data] of Object.entries(qs as Record<string, unknown>)) {
            const d = data as { avgScore?: number; latest?: number; n?: number; rationale?: string };
            qualityScores.push({
              phase,
              avgScore: d.avgScore ?? 0,
              latest: d.latest ?? 0,
              n: d.n ?? 0,
              rationale: d.rationale ?? '',
            });
          }
        }
      } catch { /* ignore */ }
    }

    // ── 1. Overview ───────────────────────────────────────────────────────
    const passed = stories.filter(s => s.passes).length;
    const decomposed = stories.filter(s => s._decomposed).length;
    const skipped = stories.filter(s => s._skipped).length;
    const pending = stories.filter(s => !s.passes && !s._decomposed && !s._skipped).length;

    const timestamps = results
      .map(r => r.timestamp ? new Date(r.timestamp).getTime() : NaN)
      .filter(t => !isNaN(t));
    let elapsed = 'N/A';
    if (timestamps.length >= 2) {
      const delta = Math.max(...timestamps) - Math.min(...timestamps);
      const hrs = Math.floor(delta / 3600000);
      const mins = Math.floor((delta % 3600000) / 60000);
      elapsed = hrs > 0 ? `${hrs}h ${mins}m` : `${mins}m`;
    }
    const iterations = results.length > 0
      ? Math.max(...results.map(r => r.spiral_iter))
      : 0;
    const estimatedCost = results.reduce((sum, r) => {
      const tier = modelTier(r.model);
      const rate = COST_PER_HOUR[tier] ?? 0.24;
      return sum + (r.duration_sec / 3600) * rate;
    }, 0);

    const overview = {
      totalAttempts: results.length,
      estimatedCost: Math.round(estimatedCost * 100) / 100,
      elapsed,
      iterations,
      passed, pending, decomposed, skipped,
      total: stories.length,
    };

    // ── 2. Velocity ───────────────────────────────────────────────────────
    const byIter = new Map<number, TsvRow[]>();
    for (const r of results) {
      if (!byIter.has(r.spiral_iter)) byIter.set(r.spiral_iter, []);
      byIter.get(r.spiral_iter)!.push(r);
    }
    const velocity = [...byIter.entries()]
      .sort(([a], [b]) => a - b)
      .map(([iter, rows]) => {
        const kept = rows.filter(r => r.status === 'keep').length;
        const totalDur = rows.reduce((s, r) => s + r.duration_sec, 0);
        const durHours = totalDur / 3600 || 0.001;
        return { iter, kept, total: rows.length, durationHours: Math.round(durHours * 100) / 100, velocityPerHr: Math.round((kept / durHours) * 10) / 10 };
      });

    // ── 2b. PRD Velocity ────────────────────────────────────────────────
    const prdVelocity = (() => {
      const passedWithTs = stories
        .filter(s => s.passes && s.last_attempted)
        .map(s => ({ id: s.id, ts: new Date(s.last_attempted!).getTime() }))
        .filter(s => !isNaN(s.ts))
        .sort((a, b) => a.ts - b.ts);

      if (passedWithTs.length === 0) {
        return { storiesPerHour: 0, totalStories: passed, elapsedHours: 0, isProjected: false, label: 'No data', sessions: [] as Array<{ date: string; stories: number; hours: number; velocity: number }>, latestSessionVelocity: 0 };
      }

      const SESSION_GAP_MS = 2 * 3600 * 1000;
      const sessions: Array<{ start: number; end: number; count: number }> = [];
      let curSession = { start: passedWithTs[0].ts, end: passedWithTs[0].ts, count: 1 };

      for (let i = 1; i < passedWithTs.length; i++) {
        const gap = passedWithTs[i].ts - curSession.end;
        if (gap > SESSION_GAP_MS) {
          sessions.push(curSession);
          curSession = { start: passedWithTs[i].ts, end: passedWithTs[i].ts, count: 1 };
        } else {
          curSession.end = passedWithTs[i].ts;
          curSession.count++;
        }
      }
      sessions.push(curSession);

      const sessionData = sessions.map(s => {
        const hours = Math.max((s.end - s.start) / 3600000, 0.1);
        return {
          date: new Date(s.start).toISOString().slice(0, 10),
          stories: s.count,
          hours: Math.round(hours * 10) / 10,
          velocity: Math.round((s.count / hours) * 10) / 10,
        };
      });

      const totalActiveHours = sessions.reduce((sum, s) => sum + Math.max((s.end - s.start) / 3600000, 0.1), 0);
      const totalStories = passedWithTs.length;
      const latestSession = sessionData[sessionData.length - 1];
      const isProjected = latestSession.hours < 1;

      return {
        storiesPerHour: Math.round((totalStories / totalActiveHours) * 10) / 10,
        totalStories,
        elapsedHours: Math.round(totalActiveHours * 10) / 10,
        isProjected,
        label: isProjected ? 'Projected' : 'Actual',
        sessions: sessionData,
        latestSessionVelocity: latestSession.velocity,
      };
    })();

    // ── 3. Model Performance ──────────────────────────────────────────────
    const byModel = new Map<string, TsvRow[]>();
    for (const r of results) {
      const m = r.model || 'unknown';
      if (!byModel.has(m)) byModel.set(m, []);
      byModel.get(m)!.push(r);
    }
    const modelPerformance = [...byModel.entries()]
      .map(([model, rows]) => {
        const kept = rows.filter(r => r.status === 'keep').length;
        const durations = rows.map(r => r.duration_sec).filter(d => d > 0);
        const avgDur = durations.length > 0 ? durations.reduce((s, d) => s + d, 0) / durations.length : 0;
        return { model, total: rows.length, kept, successRate: rows.length > 0 ? Math.round((kept / rows.length) * 1000) / 10 : 0, avgDurationSec: Math.round(avgDur) };
      })
      .sort((a, b) => b.successRate - a.successRate);

    // ── 4. Retry Analysis ─────────────────────────────────────────────────
    const byAttempt = new Map<number, TsvRow[]>();
    for (const r of results) {
      const a = r.retry_num;
      if (!byAttempt.has(a)) byAttempt.set(a, []);
      byAttempt.get(a)!.push(r);
    }
    const retryAnalysis = [...byAttempt.entries()]
      .sort(([a], [b]) => a - b)
      .map(([attempt, rows]) => {
        const kept = rows.filter(r => r.status === 'keep').length;
        return { attempt: attempt + 1, total: rows.length, kept, successRate: rows.length > 0 ? Math.round((kept / rows.length) * 1000) / 10 : 0 };
      });

    // ── 5. Resource Usage ─────────────────────────────────────────────────
    const resourceUsage = [...byModel.entries()].map(([model, rows]) => {
      const wallVals = rows.map(r => r.wall_seconds).filter(v => v > 0);
      const rssVals = rows.map(r => r.peak_rss_kb).filter(v => v > 0);
      return {
        model, count: rows.length,
        wallP50: Math.round(percentile(wallVals, 0.5)),
        wallP95: Math.round(percentile(wallVals, 0.95)),
        rssP50: Math.round(percentile(rssVals, 0.5)),
        rssP95: Math.round(percentile(rssVals, 0.95)),
      };
    }).filter(r => r.wallP50 > 0 || r.rssP50 > 0);

    // ── 6. Bottlenecks ────────────────────────────────────────────────────
    const storyTitles: Record<string, string> = {};
    for (const s of stories) storyTitles[s.id] = s.title ?? '';
    const mostRetried = Object.entries(retryCounts)
      .filter(([, c]) => c > 0)
      .sort(([, a], [, b]) => b - a)
      .slice(0, 5)
      .map(([id, retries]) => ({ id, title: storyTitles[id] ?? '', retries }));
    const keptResults = results.filter(r => r.status === 'keep' && r.duration_sec > 0);
    keptResults.sort((a, b) => b.duration_sec - a.duration_sec);
    const longest = keptResults.slice(0, 5).map(r => ({
      id: r.story_id, title: r.story_title,
      durationMin: Math.round(r.duration_sec / 6) / 10,
    }));
    const bottlenecks = { mostRetried, longest };

    // ── 7. Iteration Velocity (for bar chart) ─────────────────────────────
    const iterationVelocity = [...byIter.entries()]
      .sort(([a], [b]) => a - b)
      .map(([iter, rows]) => ({ iter, kept: rows.filter(r => r.status === 'keep').length }));

    // ── 8. Status Breakdown ───────────────────────────────────────────────
    const statusBreakdown = { passed, pending, decomposed, skipped };

    // ── 9. Token Forecast ─────────────────────────────────────────────────
    let tokenForecast: { burnRatePerHour: number; hoursLeft: number; dailyLimit: number } | null = null;
    const now = Date.now();
    const oneHourAgo = now - 3600000;
    const recentTokenRows = results.filter(r => {
      if (!r.timestamp) return false;
      const ts = new Date(r.timestamp).getTime();
      return ts >= oneHourAgo && (r.input_tokens > 0 || r.output_tokens > 0);
    });
    if (recentTokenRows.length >= 3) {
      const burnRate = recentTokenRows.reduce((s, r) => s + r.input_tokens + r.output_tokens, 0);
      if (burnRate > 0) {
        const dailyLimit = 1_000_000;
        tokenForecast = { burnRatePerHour: burnRate, hoursLeft: Math.round((dailyLimit / burnRate) * 10) / 10, dailyLimit };
      }
    }

    // ── 10. Epics ─────────────────────────────────────────────────────────
    const epicsMeta = Array.isArray(prd.epics) ? prd.epics : [];
    const epicTitleMap: Record<string, string> = {};
    for (const e of epicsMeta) if (e.id) epicTitleMap[e.id] = e.title ?? e.id;
    const epicGroups = new Map<string, PrdStory[]>();
    for (const s of stories) {
      const eid = s.epicId || '';
      if (!eid) continue;
      if (!epicGroups.has(eid)) epicGroups.set(eid, []);
      epicGroups.get(eid)!.push(s);
    }
    const epics = [...epicGroups.entries()].map(([epicId, group]) => ({
      epicId,
      title: epicTitleMap[epicId] ?? epicId,
      total: group.length,
      done: group.filter(s => s.passes).length,
      pct: group.length > 0 ? Math.round((group.filter(s => s.passes).length / group.length) * 100) : 0,
    }));

    // ── 11. Decomposition ─────────────────────────────────────────────────
    const parents = stories.filter(s => s._decomposed);
    const children = stories.filter(s => s._decomposedFrom);
    const childrenPassed = children.filter(c => c.passes).length;
    const decompositionDetails = parents.map(p => {
      const childIds = p._decomposedInto ?? [];
      const childObjs = stories.filter(s => childIds.includes(s.id));
      return {
        id: p.id,
        children: childObjs.map(c => ({ id: c.id, passes: !!c.passes })),
      };
    });
    const decompositionData = {
      effectiveness: children.length > 0 ? Math.round((childrenPassed / children.length) * 100) : 0,
      parents: decompositionDetails,
    };

    // ── 12. Failure Reasons (enriched) ────────────────────────────────────
    const storyPassMap = new Map<string, boolean>();
    for (const s of stories) storyPassMap.set(s.id, !!s.passes);

    const categorize = (s: PrdStory): FailureCategory => {
      const r = (s._failureReason ?? '').toLowerCase();
      if (r.includes('cost_ceiling')) return 'cost_ceiling';
      if (r.includes('dependency')) return 'dependency_blocked';
      if (r.includes('too_large') || r.includes('decomposed')) return 'too_large';
      if (r) return 'rejected';
      const attempts = results.filter(row => row.story_id === s.id);
      if (attempts.length === 0) return 'never_attempted';
      return 'pending_retry';
    };

    const recommend = (cat: FailureCategory, s: PrdStory, retries: number): string => {
      switch (cat) {
        case 'cost_ceiling': return retries >= 3
          ? `Hit cost ceiling ${retries}x \u2014 increase SPIRAL_COST_CEILING or simplify story scope`
          : 'Increase SPIRAL_COST_CEILING in spiral.config.sh, or break into smaller stories';
        case 'dependency_blocked': {
          const deps = s.dependencies ?? [];
          const unmet = deps.filter(d => !storyPassMap.get(d));
          return unmet.length > 0
            ? `Blocked by ${unmet.join(', ')} \u2014 resolve ${unmet.length === 1 ? 'this dependency' : 'these dependencies'} first`
            : 'Dependencies appear met \u2014 check if _failureReason is stale and clear it';
        }
        case 'too_large': return 'Manually decompose into 3-4 atomic sub-stories with narrow acceptance criteria';
        case 'rejected': return retries >= 3
          ? 'Failed 3+ times \u2014 review acceptance criteria clarity, add technicalNotes, or decompose'
          : 'Will be retried \u2014 check acceptance criteria if it keeps failing';
        case 'never_attempted': {
          const deps = s.dependencies ?? [];
          const unmet = deps.filter(d => !storyPassMap.get(d));
          return unmet.length > 0
            ? `Waiting on dependencies: ${unmet.join(', ')}`
            : 'Queued \u2014 will be picked up in next SPIRAL iteration';
        }
        case 'pending_retry': return 'Previously rejected \u2014 will retry with model escalation';
      }
    };

    const allBlockedStories = stories.filter(s => !s.passes && !s._decomposed && !s._skipped);
    const failureReasons: EnrichedFailure[] = allBlockedStories.map(s => {
      const cat = categorize(s);
      const retries = retryCounts[s.id] ?? 0;
      const deps = (s.dependencies as string[] | undefined) ?? [];
      const depsStatus = deps.map(d => ({ id: d, met: !!storyPassMap.get(d) }));
      const attempts = results.filter(row => row.story_id === s.id);
      const lastAttempt = attempts.length > 0 ? attempts[attempts.length - 1] : null;
      return {
        id: s.id,
        title: s.title ?? '',
        reason: s._failureReason ?? (cat === 'never_attempted' ? 'Not yet attempted' : 'Pending retry'),
        category: cat,
        retryCount: retries,
        model: s.model ?? '',
        source: s._source ?? '',
        complexity: s.estimatedComplexity ?? '',
        priority: s.priority ?? '',
        dependencies: deps,
        depsStatus,
        lastAttempted: s.last_attempted ?? null,
        attemptCount: attempts.length,
        lastModel: lastAttempt?.model ?? null,
        lastStatus: lastAttempt?.status ?? null,
        lastDurationSec: lastAttempt ? Math.round(lastAttempt.duration_sec) : null,
        scopeCreep: !!s._scopeCreep,
        recommendation: recommend(cat, s, retries),
      };
    })
    .sort((a, b) => {
      const order: Record<FailureCategory, number> = { cost_ceiling: 0, too_large: 1, dependency_blocked: 2, rejected: 3, pending_retry: 4, never_attempted: 5 };
      const diff = order[a.category] - order[b.category];
      if (diff !== 0) return diff;
      return b.retryCount - a.retryCount;
    });

    // ── 12b. Resolved failures ────────────────────────────────────────────
    const resolvedFailures: ResolvedFailure[] = stories
      .filter(s => s._failureReason && (s.passes || s._skipped || s._decomposed))
      .map(s => {
        const cat = categorize(s);
        const resolved: ResolvedStatus = s.passes ? 'passed' : s._decomposed ? 'decomposed' : 'skipped';
        return {
          id: s.id,
          title: s.title ?? '',
          reason: s._failureReason!,
          category: cat,
          retryCount: retryCounts[s.id] ?? 0,
          model: s.model ?? '',
          source: s._source ?? '',
          resolvedAs: resolved,
        };
      })
      .sort((a, b) => {
        const order: Record<FailureCategory, number> = { cost_ceiling: 0, too_large: 1, dependency_blocked: 2, rejected: 3, pending_retry: 4, never_attempted: 5 };
        return order[a.category] - order[b.category];
      });

    // ── 13. Insights ──────────────────────────────────────────────────────
    const insights: string[] = [];
    if (modelPerformance.length >= 2) {
      const best = modelPerformance[0];
      const worst = modelPerformance[modelPerformance.length - 1];
      const gap = best.successRate - worst.successRate;
      if (gap > 20 && worst.total >= 3) {
        insights.push(`${best.model} has ${gap.toFixed(0)}% higher success rate than ${worst.model} (${best.successRate}% vs ${worst.successRate}%) \u2014 consider routing more stories to ${best.model}`);
      }
    }
    if (retryAnalysis.length > 0 && retryAnalysis[0].successRate < 50 && retryAnalysis[0].total >= 5) {
      insights.push(`First-attempt success rate is only ${retryAnalysis[0].successRate}% \u2014 consider improving story clarity or prompt quality`);
    }
    for (const b of bottlenecks.mostRetried) {
      if (b.retries >= 3) {
        insights.push(`Story ${b.id} consumed ${b.retries} retries \u2014 consider manual decomposition or intervention`);
        break;
      }
    }

    // ── 14. Latest Screenshot ─────────────────────────────────────────────
    let latestScreenshot: string | null = null;
    const screenshotsDir = path.join(root, '.spiral', 'screenshots');
    if (fs.existsSync(screenshotsDir)) {
      try {
        const pngs = fs.readdirSync(screenshotsDir)
          .filter(f => f.endsWith('.png'))
          .sort()
          .reverse();
        if (pngs.length > 0) {
          const imgData = fs.readFileSync(path.join(screenshotsDir, pngs[0]));
          latestScreenshot = `data:image/png;base64,${imgData.toString('base64')}`;
        }
      } catch { /* ignore */ }
    }

    // ── 15. Agent Phase Telemetry (last 50 transitions) ───────────────────
    const agentTelemetry: AgentTelemetryEntry[] = [];
    const telemetryPath = path.join(root, '.spiral', 'agent-telemetry.jsonl');
    if (fs.existsSync(telemetryPath)) {
      try {
        const lines = fs.readFileSync(telemetryPath, 'utf8').split('\n').filter(Boolean);
        const recent = lines.slice(-50);
        for (const line of recent) {
          try {
            const entry = JSON.parse(line) as Partial<AgentTelemetryEntry>;
            agentTelemetry.push({
              ts: entry.ts ?? '',
              workerId: entry.workerId ?? '0',
              storyId: entry.storyId ?? '',
              fromPhase: entry.fromPhase ?? '',
              toPhase: entry.toPhase ?? '',
              durationMs: entry.durationMs ?? 0,
              qualityScore: entry.qualityScore ?? 0,
              retryCount: entry.retryCount ?? 0,
            });
          } catch { /* skip malformed lines */ }
        }
      } catch { /* ignore */ }
    }

    // ── 16. Phase Timings (last iteration from spiral_events.jsonl) ───────
    const phaseTimings: PhaseTiming[] = [];
    const eventsPath = path.join(root, 'spiral_events.jsonl');
    if (fs.existsSync(eventsPath)) {
      try {
        const lines = fs.readFileSync(eventsPath, 'utf8').split('\n').filter(Boolean);
        interface PhaseEvent {
          event_type: string; timestamp: string;
          phase?: string; iteration?: number;
        }
        const phaseEvents: PhaseEvent[] = [];
        for (const line of lines) {
          try {
            const evt = JSON.parse(line) as PhaseEvent;
            if (evt.event_type === 'phase_start' || evt.event_type === 'phase_end') {
              phaseEvents.push(evt);
            }
          } catch { /* skip */ }
        }
        if (phaseEvents.length > 0) {
          const maxIter = Math.max(...phaseEvents.map(e => e.iteration ?? 0));
          const iterEvents = phaseEvents.filter(e => e.iteration === maxIter);
          const starts = new Map<string, number>();
          const ends = new Map<string, number>();
          for (const e of iterEvents) {
            const ts = new Date(e.timestamp).getTime();
            if (isNaN(ts) || !e.phase) continue;
            if (e.event_type === 'phase_start') starts.set(e.phase, ts);
            if (e.event_type === 'phase_end') ends.set(e.phase, ts);
          }
          for (const phase of ['R', 'T', 'S', 'M', 'I', 'V', 'C']) {
            const s = starts.get(phase);
            const e = ends.get(phase);
            if (s !== undefined && e !== undefined && e > s) {
              phaseTimings.push({
                phase,
                durationSec: Math.round((e - s) / 1000),
                label: PHASE_LABELS[phase] ?? phase,
              });
            }
          }
        }
      } catch { /* ignore */ }
    }

    // ── 17. Stories List (per-story attempt history) ──────────────────────
    // Group results.tsv rows by story_id for the expandable accordion
    const attemptsByStory = new Map<string, TsvRow[]>();
    for (const r of results) {
      if (!r.story_id) continue;
      if (!attemptsByStory.has(r.story_id)) attemptsByStory.set(r.story_id, []);
      attemptsByStory.get(r.story_id)!.push(r);
    }
    const storiesList = stories.map(s => ({
      id: s.id,
      title: s.title ?? '',
      passes: !!s.passes,
      _decomposed: !!s._decomposed,
      _skipped: !!s._skipped,
      _failureReason: s._failureReason ?? '',
      epicId: s.epicId ?? '',
      priority: s.priority ?? '',
      source: s._source ?? '',
      attempts: (attemptsByStory.get(s.id) ?? []).map(r => ({
        timestamp: r.timestamp,
        model: r.model,
        status: r.status,
        durationSec: Math.round(r.duration_sec),
        retryNum: r.retry_num,
        commitSha: r.commit_sha,
        runId: r.run_id,
        inputTokens: r.input_tokens,
        outputTokens: r.output_tokens,
      })),
    }));

    // ── 18. Story Details + Attempts for bottleneck click-through ────────
    const bottleneckIds = new Set([
      ...bottlenecks.mostRetried.map(b => b.id),
      ...bottlenecks.longest.map(b => b.id),
    ]);
    const storyDetails: Record<string, {
      id: string; title: string; description?: string; passes: boolean;
      priority?: string; complexity?: string; failureReason?: string;
      dependencies?: string[]; source?: string; retryCount?: number;
      acceptanceCriteria?: string[]; filesTouch?: string[];
      completedAt?: string | null; scopeCreep?: boolean; lastAttempted?: string | null;
    }> = {};
    for (const s of stories) {
      if (!bottleneckIds.has(s.id)) continue;
      storyDetails[s.id] = {
        id: s.id,
        title: s.title ?? '',
        description: (s as Record<string, unknown>).description as string | undefined,
        passes: !!s.passes,
        priority: s.priority,
        complexity: s.estimatedComplexity,
        failureReason: s._failureReason,
        dependencies: s.dependencies,
        source: s._source,
        retryCount: retryCounts[s.id] ?? 0,
        acceptanceCriteria: (s as Record<string, unknown>).acceptanceCriteria as string[] | undefined,
        filesTouch: (s as Record<string, unknown>).filesTouch as string[] | undefined,
        completedAt: s.completedAt ?? null,
        scopeCreep: !!s._scopeCreep,
        lastAttempted: s.last_attempted ?? null,
      };
    }
    const storyAttempts: Record<string, Array<{ timestamp: string; status: string; model: string; duration: number; commitSha: string }>> = {};
    for (const sid of bottleneckIds) {
      const rows = (attemptsByStory.get(sid) ?? [])
        .sort((a, b) => b.timestamp.localeCompare(a.timestamp))
        .slice(0, 10);
      if (rows.length > 0) {
        storyAttempts[sid] = rows.map(r => ({
          timestamp: r.timestamp,
          status: r.status,
          model: r.model,
          duration: Math.round(r.duration_sec),
          commitSha: r.commit_sha,
        }));
      }
    }

    // ── Response ──────────────────────────────────────────────────────────
    res.end(JSON.stringify({
      overview, velocity, modelPerformance, retryAnalysis,
      resourceUsage, bottlenecks, iterationVelocity,
      statusBreakdown, tokenForecast, qualityScores,
      epics, decomposition: decompositionData, failureReasons, resolvedFailures,
      insights, latestScreenshot, prdVelocity,
      agentTelemetry, phaseTimings, storiesList,
      storyDetails, storyAttempts,
    }));
  } catch (e) {
    res.statusCode = 500;
    res.end(JSON.stringify({ error: String(e) }));
  }
}
