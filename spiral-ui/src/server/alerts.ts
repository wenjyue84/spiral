#!/usr/bin/env node
/**
 * spiral-ui/src/server/alerts.ts — Cost ceiling alert emission module
 *
 * Provides functions to check SPIRAL cost against ceiling and emit WebSocket alerts
 * when thresholds (80% warning, 95% critical) are crossed.
 *
 * This module acts as a bridge between Phase I cost checks and the WebSocket server.
 */

import { readFileSync, appendFileSync } from 'fs';
import { join, resolve } from 'path';
import { existsSync, mkdirSync } from 'fs';

interface CostAlert {
  type: 'cost_alert';
  severity: 'warning' | 'critical';
  current_cost: number;
  ceiling: number;
  percent_used: number;
  timestamp: string;
}

/**
 * Get the path to the alerts queue file.
 */
function getAlertsQueuePath(): string {
  const spiralDir = join(resolve('.'), '.spiral');
  if (!existsSync(spiralDir)) {
    mkdirSync(spiralDir, { recursive: true });
  }
  return join(spiralDir, 'alerts.jsonl');
}

/**
 * Emit a cost alert to the WebSocket queue.
 *
 * @param current_cost - Current cumulative spend in USD
 * @param ceiling - SPIRAL_COST_CEILING in USD
 * @param severity - 'warning' (80%) or 'critical' (95%)
 * @returns True if alert was emitted successfully
 */
export function emitCostAlert(
  current_cost: number,
  ceiling: number,
  severity: 'warning' | 'critical' = 'warning'
): boolean {
  if (!ceiling || ceiling <= 0) {
    return false;
  }

  const percentUsed = (current_cost / ceiling) * 100;

  const alert: CostAlert = {
    type: 'cost_alert',
    severity,
    current_cost: Math.round(current_cost * 10000) / 10000,
    ceiling: Math.round(ceiling * 10000) / 10000,
    percent_used: Math.round(percentUsed * 100) / 100,
    timestamp: new Date().toISOString(),
  };

  try {
    const queuePath = getAlertsQueuePath();
    appendFileSync(queuePath, JSON.stringify(alert) + '\n', 'utf-8');
    return true;
  } catch (e) {
    console.error(
      `[alerts.ts] Failed to emit alert: ${e instanceof Error ? e.message : String(e)}`
    );
    return false;
  }
}

/**
 * Check current spend and emit alerts if thresholds are crossed.
 *
 * Reads .spiral/results.tsv to calculate cumulative spend, then checks against
 * SPIRAL_COST_CEILING environment variable.
 *
 * @param ceilingUsd - SPIRAL_COST_CEILING (if undefined, reads from env)
 * @returns Object with current_cost, ceiling, percent_used, and alerts_emitted array
 */
export function checkAndEmitCostAlerts(ceilingUsd?: number): {
  current_cost: number;
  ceiling: number;
  percent_used: number;
  alerts_emitted: ('warning' | 'critical')[];
  error?: string;
} {
  // Get ceiling from arg or environment
  if (ceilingUsd === undefined) {
    const ceilingStr = process.env.SPIRAL_COST_CEILING || '0';
    try {
      ceilingUsd = parseFloat(ceilingStr);
    } catch {
      ceilingUsd = 0;
    }
  }

  if (!ceilingUsd || ceilingUsd <= 0) {
    return {
      current_cost: 0,
      ceiling: 0,
      percent_used: 0,
      alerts_emitted: [],
      error: 'SPIRAL_COST_CEILING not set or invalid',
    };
  }

  // Calculate current spend from results.tsv
  let currentCost = 0;
  try {
    const resultsPath = join(resolve('.'), '.spiral', 'results.tsv');
    if (existsSync(resultsPath)) {
      const content = readFileSync(resultsPath, 'utf-8');
      const lines = content.split('\n');

      if (lines.length > 1) {
        // Parse header line
        const header = lines[0].split('\t');
        const costIndex = header.findIndex(
          (col) =>
            col === 'estimated_cost_usd' ||
            col === 'cost_usd' ||
            col === 'cost'
        );

        if (costIndex >= 0) {
          // Parse data lines
          for (let i = 1; i < lines.length; i++) {
            const line = lines[i].trim();
            if (!line) continue;

            const cols = line.split('\t');
            if (cols[costIndex]) {
              try {
                currentCost += parseFloat(cols[costIndex]);
              } catch {
                // Skip rows with non-numeric costs
              }
            }
          }
        }
      }
    }
  } catch (e) {
    console.error(
      `[alerts.ts] Error reading results.tsv: ${e instanceof Error ? e.message : String(e)}`
    );
    // Continue with 0 cost
  }

  const percentUsed = (currentCost / ceilingUsd) * 100;
  const alertsEmitted: ('warning' | 'critical')[] = [];

  // Check critical threshold (95%)
  if (percentUsed >= 95) {
    if (emitCostAlert(currentCost, ceilingUsd, 'critical')) {
      alertsEmitted.push('critical');
    }
  }
  // Check warning threshold (80%)
  else if (percentUsed >= 80) {
    if (emitCostAlert(currentCost, ceilingUsd, 'warning')) {
      alertsEmitted.push('warning');
    }
  }

  return {
    current_cost: Math.round(currentCost * 10000) / 10000,
    ceiling: Math.round(ceilingUsd * 10000) / 10000,
    percent_used: Math.round(percentUsed * 100) / 100,
    alerts_emitted: alertsEmitted,
  };
}

/**
 * Main entry point for CLI usage.
 */
if (require.main === module) {
  const result = checkAndEmitCostAlerts();
  console.log(JSON.stringify(result, null, 2));
}
