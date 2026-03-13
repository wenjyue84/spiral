# lib/validate_code.py
import subprocess
import sys

def validate_code(file_path):
    """
    Runs pylint on a given file and returns a score.
    A score of 10.0 is perfect.
    """
    if not file_path.endswith(".py"):
        print(f"[validator] Skipping non-python file: {file_path}")
        return 10.0

    print(f"[validator] Running pylint on {file_path}...")
    try:
        result = subprocess.run(
            ["pylint", file_path],
            capture_output=True,
            text=True,
            timeout=60,
        )
        output = result.stdout
        # Pylint outputs a score like "Your code has been rated at 9.85/10"
        for line in output.splitlines():
            if "rated at" in line:
                score_str = line.split("rated at")[1].split("/")[0].strip()
                return float(score_str)
        return 0.0
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"[validator] Pylint failed: {e}")
        return 0.0

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python lib/validate_code.py <file_path>")
        sys.exit(1)
    file_path = sys.argv[1]
    score = validate_code(file_path)
    print(f"Pylint score: {score}")
    if score < 8.0:
        sys.exit(1)
    sys.exit(0)
