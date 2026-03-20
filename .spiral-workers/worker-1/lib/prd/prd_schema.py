"""PRD JSON Schema validation.

Validates prd.json against prd.schema.json using jsonschema.
This module is used by the pre-commit hook to ensure prd.json structure is valid.
"""

import json
import sys
from pathlib import Path


def validate_prd(prd_path: str, quiet: bool = False) -> bool:
    """Validate prd.json against schema.

    Args:
        prd_path: Path to prd.json file to validate
        quiet: If True, suppress output on success

    Returns:
        True if validation passes, False otherwise
    """
    try:
        import jsonschema
    except ImportError:
        if not quiet:
            print("jsonschema not installed, skipping validation", file=sys.stderr)
        return True

    try:
        # Load prd.json with UTF-8 encoding
        with open(prd_path, encoding='utf-8') as f:
            prd_data = json.load(f)

        # Find schema file (look relative to this script)
        script_dir = Path(__file__).parent.parent.parent
        schema_path = script_dir / "prd.schema.json"

        if not schema_path.exists():
            if not quiet:
                print(f"Schema file not found: {schema_path}", file=sys.stderr)
            return True  # Silently pass if schema doesn't exist

        with open(schema_path) as f:
            schema = json.load(f)

        # Validate
        jsonschema.validate(instance=prd_data, schema=schema)

        if not quiet:
            print(f"✓ prd.json is valid", file=sys.stderr)
        return True

    except json.JSONDecodeError as e:
        print(f"JSON decode error in {prd_path}: {e}", file=sys.stderr)
        return False
    except jsonschema.ValidationError as e:
        print(f"Schema validation error: {e.message}", file=sys.stderr)
        print(f"  at path: {' -> '.join(str(p) for p in e.path)}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"Error during validation: {e}", file=sys.stderr)
        return False


if __name__ == "__main__":
    # CLI interface for pre-commit hook
    import argparse

    parser = argparse.ArgumentParser(description="Validate prd.json against schema")
    parser.add_argument("prd_file", help="Path to prd.json file")
    parser.add_argument("--quiet", action="store_true", help="Suppress output on success")

    args = parser.parse_args()

    success = validate_prd(args.prd_file, quiet=args.quiet)
    sys.exit(0 if success else 1)
