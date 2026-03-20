#!/usr/bin/env python3
"""
lib/cost_alert_emitter.py — Detect cost thresholds and emit WebSocket alerts

Checks cumulative SPIRAL cost against SPIRAL_COST_CEILING and emits alerts
when thresholds (80% warning, 95% critical) are crossed.

Uses file-based queue (.spiral/alerts.jsonl) for inter-process communication
with the WebSocket server.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, os.path.dirname(__file__))

from budget_analyzer import calculate_current_spend


def get_alerts_queue_path() -> Path:
    """Get path to alerts queue file."""
    spiral_dir = Path('.spiral')
    spiral_dir.mkdir(exist_ok=True)
    return spiral_dir / 'alerts.jsonl'


def emit_cost_alert(
    current_cost: float,
    ceiling: float,
    severity: str = 'warning',
) -> bool:
    """
    Emit a cost alert to the WebSocket queue.

    Args:
        current_cost: Current cumulative spend in USD
        ceiling: SPIRAL_COST_CEILING in USD
        severity: 'warning' (80%) or 'critical' (95%)

    Returns:
        True if alert was emitted successfully
    """
    if not ceiling or ceiling <= 0:
        return False

    percent_used = (current_cost / ceiling) * 100

    alert = {
        'type': 'cost_alert',
        'severity': severity,
        'current_cost': round(current_cost, 4),
        'ceiling': round(ceiling, 4),
        'percent_used': round(percent_used, 2),
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }

    try:
        queue_path = get_alerts_queue_path()
        with open(queue_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(alert) + '\n')
        return True
    except Exception as e:
        print(f'[cost_alert_emitter] Failed to emit alert: {e}', file=sys.stderr)
        return False


def check_and_emit_cost_alerts(ceiling_usd: Optional[float] = None) -> dict[str, Any]:
    """
    Check current spend and emit alerts if thresholds are crossed.

    Args:
        ceiling_usd: SPIRAL_COST_CEILING (if None, reads from env)

    Returns:
        Dict with current_cost, ceiling, alerts_emitted
    """
    # Get ceiling from arg or environment
    if ceiling_usd is None:
        ceiling_str = os.environ.get('SPIRAL_COST_CEILING', '0')
        try:
            ceiling_usd = float(ceiling_str)
        except ValueError:
            ceiling_usd = 0.0

    if not ceiling_usd or ceiling_usd <= 0:
        return {
            'current_cost': 0.0,
            'ceiling': 0.0,
            'alerts_emitted': [],
            'error': 'SPIRAL_COST_CEILING not set or invalid',
        }

    # Calculate current spend
    spend_result = calculate_current_spend()
    current_cost = spend_result['total_cost_usd']
    percent_used = (current_cost / ceiling_usd) * 100

    alerts_emitted = []

    # Check critical threshold (95%)
    if percent_used >= 95:
        if emit_cost_alert(current_cost, ceiling_usd, severity='critical'):
            alerts_emitted.append('critical')
    # Check warning threshold (80%)
    elif percent_used >= 80:
        if emit_cost_alert(current_cost, ceiling_usd, severity='warning'):
            alerts_emitted.append('warning')

    return {
        'current_cost': round(current_cost, 4),
        'ceiling': round(ceiling_usd, 4),
        'percent_used': round(percent_used, 2),
        'alerts_emitted': alerts_emitted,
    }


if __name__ == '__main__':
    result = check_and_emit_cost_alerts()
    print(json.dumps(result, indent=2))
