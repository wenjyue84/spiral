"""Debug script for git worktree remove path issue."""
import subprocess, pathlib, os, tempfile

tmp = pathlib.Path(tempfile.mkdtemp())
repo = tmp / 'repo'
wtree = tmp / 'spiral-worker-1'
repo.mkdir()

def posix(p):
    return str(p).replace('\\', '/')

subprocess.run(['git', 'init', '-b', 'main', posix(repo)], capture_output=True, check=True)
subprocess.run(['git', '-C', posix(repo), 'config', 'user.email', 't@t.com'], capture_output=True, check=True)
subprocess.run(['git', '-C', posix(repo), 'config', 'user.name', 'T'], capture_output=True, check=True)
(repo / 'f').write_text('init')
subprocess.run(['git', '-C', posix(repo), 'add', '.'], capture_output=True, check=True)
subprocess.run(['git', '-C', posix(repo), 'commit', '-m', 'init'], capture_output=True, check=True)
r = subprocess.run(['git', '-C', posix(repo), 'worktree', 'add', posix(wtree), '-b', 'spiral-worker-1', 'HEAD'], capture_output=True)
print('worktree add returncode:', r.returncode, 'stderr:', r.stderr.decode())
print('wtree exists:', wtree.is_dir())

# Show worktree list
r2 = subprocess.run(['git', '-C', posix(repo), 'worktree', 'list'], capture_output=True, text=True)
print('worktree list:', r2.stdout)

rp = posix(repo)
wp = posix(wtree)

lines = [
    'REPO_ROOT="{}"'.format(rp),
    'wtree_path="{}"'.format(wp),
    'branch="spiral-worker-1"',
    'echo "=== unlock ==="',
    'git -C "$REPO_ROOT" worktree unlock "$wtree_path" 2>&1 || true',
    'echo "=== remove ==="',
    'git -C "$REPO_ROOT" worktree remove "$wtree_path" --force 2>&1 && echo REMOVED || echo FAILED',
    'echo "=== branch ==="',
    'git -C "$REPO_ROOT" branch -D "$branch" 2>&1 && echo BRANCH_REMOVED || echo BRANCH_FAILED',
]
script = '\n'.join(lines)
print('Script:\n', script)

result = subprocess.run(['bash', '-c', script], capture_output=True, text=True)
print('stdout:', result.stdout)
print('stderr:', result.stderr)
print('wtree_gone:', not wtree.is_dir())
