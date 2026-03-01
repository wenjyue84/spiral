#!/usr/bin/env node
/**
 * Ralph Stream Formatter
 * Reads Claude's stream-json output from stdin and displays
 * a human-readable real-time view of what Claude is doing.
 */

import { createInterface } from 'readline';

const rl = createInterface({ input: process.stdin });

const COLORS = {
  reset: '\x1b[0m',
  dim: '\x1b[2m',
  bold: '\x1b[1m',
  cyan: '\x1b[36m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
  red: '\x1b[31m',
  magenta: '\x1b[35m',
  blue: '\x1b[34m',
  white: '\x1b[37m',
  bgBlue: '\x1b[44m',
};

const TOOL_ICONS = {
  Read: '📖',
  Write: '✏️',
  Edit: '🔧',
  Glob: '🔍',
  Grep: '🔎',
  Bash: '💻',
  Skill: '⚡',
  Task: '🚀',
};

let toolCallCount = 0;
let startTime = Date.now();

function elapsed() {
  const secs = Math.floor((Date.now() - startTime) / 1000);
  const mins = Math.floor(secs / 60);
  const s = secs % 60;
  return `${mins}:${String(s).padStart(2, '0')}`;
}

function truncate(str, max = 80) {
  if (!str) return '';
  str = str.replace(/\n/g, ' ').trim();
  return str.length > max ? str.slice(0, max) + '...' : str;
}

rl.on('line', (line) => {
  try {
    const event = JSON.parse(line);

    // Handle different event types from Claude's stream-json
    if (event.type === 'assistant' && event.message?.content) {
      for (const block of event.message.content) {
        if (block.type === 'tool_use') {
          toolCallCount++;
          const icon = TOOL_ICONS[block.name] || '🔨';
          const name = block.name;
          let detail = '';

          // Extract useful info from tool inputs
          if (block.input) {
            if (block.input.file_path) {
              detail = block.input.file_path.replace(/.*[/\\]/, '');
            } else if (block.input.command) {
              detail = truncate(block.input.command, 60);
            } else if (block.input.pattern) {
              detail = `"${block.input.pattern}"`;
            } else if (block.input.query) {
              detail = truncate(block.input.query, 60);
            } else if (block.input.old_string) {
              detail = truncate(block.input.old_string, 40) + ' → ...';
            } else if (block.input.skill) {
              detail = block.input.skill;
            } else if (block.input.prompt) {
              detail = truncate(block.input.prompt, 60);
            }
          }

          console.log(
            `${COLORS.dim}[${elapsed()}]${COLORS.reset} ` +
            `${icon} ${COLORS.cyan}${name}${COLORS.reset} ` +
            `${COLORS.dim}${detail}${COLORS.reset}`
          );
        } else if (block.type === 'text') {
          // Claude's thinking/response text — show a preview
          const text = truncate(block.text, 100);
          if (text.length > 0) {
            console.log(
              `${COLORS.dim}[${elapsed()}]${COLORS.reset} ` +
              `${COLORS.white}${text}${COLORS.reset}`
            );
          }
        }
      }
    } else if (event.type === 'result') {
      // Final result
      console.log('');
      console.log(
        `${COLORS.green}${COLORS.bold}✓ Claude finished${COLORS.reset} ` +
        `${COLORS.dim}(${toolCallCount} tool calls in ${elapsed()})${COLORS.reset}`
      );
    } else if (event.type === 'error') {
      console.log(
        `${COLORS.red}✗ Error: ${event.error?.message || JSON.stringify(event)}${COLORS.reset}`
      );
    }
  } catch {
    // Non-JSON lines — pass through
    if (line.trim()) {
      console.log(`${COLORS.dim}${line}${COLORS.reset}`);
    }
  }
});

rl.on('close', () => {
  console.log(
    `\n${COLORS.dim}Stream ended (${toolCallCount} tool calls, ${elapsed()} elapsed)${COLORS.reset}`
  );
});
