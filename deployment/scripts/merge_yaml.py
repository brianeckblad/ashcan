#!/usr/bin/env python3
"""
Merge YAML configuration files intelligently.
Preserves existing values while adding new keys from templates.
"""

import sys
import re
import os

def parse_yaml_simple(content):
    """Parse simple YAML (key: value format without complex structures)"""
    data = {}
    for line in content.split('\n'):
        # Skip comments and empty lines
        if line.strip().startswith('#') or not line.strip():
            continue

        # Extract key: value pairs
        match = re.match(r'^([a-z0-9_]+):\s*(.+?)(?:\s*#.*)?$', line)
        if match:
            key = match.group(1)
            value = match.group(2).strip()
            data[key] = value

    return data

def merge_yaml_files(template_path, existing_path, output_path):
    """
    Merge existing YAML values into template.

    Args:
        template_path: Path to template file (.example)
        existing_path: Path to existing file to merge from
        output_path: Path to write merged file
    """

    # Read template
    with open(template_path, 'r') as f:
        template_content = f.read()

    # Read existing
    with open(existing_path, 'r') as f:
        existing_content = f.read()

    # Parse both
    existing_data = parse_yaml_simple(existing_content)

    # Build output by processing template line by line
    output_lines = []

    for line in template_content.split('\n'):
        # Skip comment-only lines and empty lines - keep as-is
        if line.strip().startswith('#') or not line.strip():
            output_lines.append(line)
            continue

        # Check if this is a key: value line
        match = re.match(r'^([a-z0-9_]+):\s*', line)
        if match:
            key = match.group(1)
            # If key exists in existing config, use that value
            if key in existing_data:
                # Reconstruct the line with existing value, preserving trailing comments
                template_match = re.match(r'^([a-z0-9_]+):\s*(.+?)(?:\s*(#.*))?$', line)
                trailing_comment = template_match.group(3) if template_match and template_match.group(3) else ""
                new_line = f"{key}: {existing_data[key]}"
                if trailing_comment:
                    # Preserve column alignment from the template
                    comment_col = line.index('#')
                    if len(new_line) < comment_col:
                        new_line += ' ' * (comment_col - len(new_line))
                    else:
                        new_line += ' '
                    new_line += trailing_comment
                output_lines.append(new_line)
            else:
                output_lines.append(line)
        else:
            output_lines.append(line)

    # Write output
    with open(output_path, 'w') as f:
        f.write('\n'.join(output_lines))

    if not output_path.endswith('.merged'):
        # Replace original if not a temp file
        os.replace(output_path, output_path.replace('.merged', ''))

if __name__ == '__main__':
    if len(sys.argv) != 4:
        print("Usage: merge_yaml.py <template> <existing> <output>")
        sys.exit(1)

    template = sys.argv[1]
    existing = sys.argv[2]
    output = sys.argv[3]

    try:
        merge_yaml_files(template, existing, output)
        print(f"✅ Merged: {existing} into {output}")
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)

