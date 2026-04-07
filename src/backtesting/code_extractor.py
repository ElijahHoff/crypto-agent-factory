"""
Code Extractor v0.9.2 — Handles every format Claude might return.

Tested formats:
1. Clean JSON: {"signal_code": "def generate_signals(prices):\n    ..."}
2. JSON in markdown fence: ```json\n{...}\n```
3. Python code block: ```python\ndef generate_signals...\n```
4. Multiple code blocks (picks the one with generate_signals)
5. Escaped newlines in JSON string (\\n → \n)
6. Mixed text + code blocks
7. Code inside a class definition
8. Function named differently (compute_signals, etc.)
9. Raw text with def statement (no fences)
"""

import json
import re
from loguru import logger


def extract_code(text: str) -> str | None:
    """
    Extract signal generation code from any Claude response format.
    Returns clean Python code string or None.
    """
    if not text or len(text.strip()) < 30:
        return None

    # Strategy 1: Parse as JSON (handles clean JSON and JSON in markdown)
    code = _try_json(text)
    if code and _has_function(code):
        return code

    # Strategy 2: Extract from ```python ... ``` blocks
    code = _try_code_blocks(text)
    if code and _has_function(code):
        return code

    # Strategy 3: Find bare function definition in text
    code = _try_bare_function(text)
    if code and _has_function(code):
        return code

    # Strategy 4: Find ANY def statement that could be a signal function
    code = _try_any_def(text)
    if code:
        return code

    logger.debug(f"Code extraction failed. Response starts with: {text[:200]}...")
    return None


def _try_json(text: str) -> str | None:
    """Try to extract signal_code from JSON response."""
    # Try multiple JSON extraction approaches
    candidates = []

    # Raw text
    candidates.append(text.strip())

    # Inside markdown fence
    for match in re.finditer(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL):
        candidates.append(match.group(1).strip())

    # Sometimes Claude puts JSON without fences but with leading text
    # Find first { and last }
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace >= 0 and last_brace > first_brace:
        candidates.append(text[first_brace:last_brace + 1])

    for candidate in candidates:
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                for key in ["signal_code", "code", "python_code",
                            "trading_logic", "implementation"]:
                    code = data.get(key, "")
                    if code and isinstance(code, str):
                        # Unescape
                        code = code.replace("\\n", "\n").replace("\\t", "    ")
                        code = code.replace("\\\"", "\"").replace("\\'", "'")
                        if "def " in code or "signals" in code:
                            return code.strip()
        except (json.JSONDecodeError, TypeError, AttributeError):
            continue

    return None


def _try_code_blocks(text: str) -> str | None:
    """Extract from markdown code blocks. Prefer blocks with generate_signals."""
    blocks = []
    for match in re.finditer(r'```(?:python)?\s*\n(.*?)\n```', text, re.DOTALL):
        block = match.group(1).strip()
        if len(block) > 20:
            blocks.append(block)

    if not blocks:
        return None

    # Prefer block with generate_signals
    for block in blocks:
        if "def generate_signals" in block:
            return block

    # Then any block with a def and signals
    for block in blocks:
        if "def " in block and "signal" in block.lower():
            return block

    # Then any block with def
    for block in blocks:
        if "def " in block:
            return block

    return None


def _try_bare_function(text: str) -> str | None:
    """Extract function definition from raw text (no code fences)."""
    # Find def generate_signals
    for func_name in ["generate_signals", "compute_signals", "gen_signals",
                      "get_signals", "trading_signals"]:
        pattern = f"def {func_name}"
        idx = text.find(pattern)
        if idx < 0:
            continue

        # Collect imports before the function
        pre_lines = text[:idx].split("\n")
        imports = []
        for line in pre_lines:
            stripped = line.strip()
            if stripped.startswith("import ") or stripped.startswith("from "):
                imports.append(stripped)

        # Collect the function body
        func_text = text[idx:]
        lines = func_text.split("\n")
        func_lines = [lines[0]]  # def line

        for line in lines[1:]:
            # Stop at next top-level def, class, or non-indented non-empty line
            if line.strip() == "":
                func_lines.append(line)
            elif line[0:1] in (" ", "\t"):
                func_lines.append(line)
            elif line.strip().startswith("#"):
                func_lines.append(line)
            else:
                break

        # Remove trailing blank lines
        while func_lines and not func_lines[-1].strip():
            func_lines.pop()

        if len(func_lines) < 3:
            continue

        result = "\n".join(imports + [""]) + "\n".join(func_lines) if imports else "\n".join(func_lines)
        return result.strip()

    return None


def _try_any_def(text: str) -> str | None:
    """Last resort: find any function that looks like it generates signals."""
    # Find all def statements
    for match in re.finditer(r'(def \w+\([^)]*\):)', text):
        func_start = match.start()
        func_header = match.group(1)

        # Skip known non-signal functions
        skip = ["__init__", "__str__", "__repr__", "setUp", "tearDown",
                "helper", "validate", "plot", "save", "load"]
        if any(s in func_header for s in skip):
            continue

        # Check if function body mentions signals
        func_end = _find_function_end(text, func_start)
        func_body = text[func_start:func_end]

        if "signal" in func_body.lower() and ("return" in func_body):
            # Collect imports
            pre = text[:func_start]
            imports = [line.strip() for line in pre.split("\n")
                       if line.strip().startswith("import ") or line.strip().startswith("from ")]

            # Rename to generate_signals
            func_body = re.sub(r'def \w+\(', 'def generate_signals(', func_body, count=1)
            # Remove self param
            func_body = func_body.replace("(self, ", "(").replace("(self,", "(")

            result = "\n".join(imports + [""]) + func_body if imports else func_body
            return result.strip()

    return None


def _find_function_end(text: str, start: int) -> int:
    """Find where a function definition ends."""
    lines = text[start:].split("\n")
    if not lines:
        return start

    # First line is def ...:
    end_pos = start + len(lines[0]) + 1

    for line in lines[1:]:
        if not line.strip():
            end_pos += len(line) + 1
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 0 and line.strip() and not line.strip().startswith("#"):
            break
        end_pos += len(line) + 1

    return end_pos


def _has_function(code: str) -> bool:
    """Check if code contains a usable function definition."""
    return bool(code and "def " in code and ("return" in code or "signal" in code.lower()))
