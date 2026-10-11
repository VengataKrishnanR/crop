"""
Patch google-adk so literal curly braces in agent prompts don't throw KeyError.
Run once after `pip install -r requirements.txt`. Safe to run multiple times.

ADK 1.x kept state injection in google/adk/utils/instructions_utils.py and raised
on any unresolvable {name}. ADK 2.x moved it to
google/adk/flows/llm_flows/prompt/_instructions_utils.py; there, braces that are
not valid identifiers (JSON examples, expressions) already pass through, and
only a bare {identifier} raises. This script patches whichever layout is present.
The server also applies an in-process patch (server/app.py), so this is
belt-and-braces for `adk web`.
"""
import sys
from pathlib import Path

adk_root = Path(sys.executable).parent.parent / "Lib" / "site-packages" / "google" / "adk"
if not adk_root.exists():  # POSIX venv layout
    matches = list((Path(sys.executable).parent.parent / "lib").glob("python3*/site-packages/google/adk"))
    adk_root = matches[0] if matches else adk_root

candidates = [
    adk_root / "utils" / "instructions_utils.py",                        # ADK 1.x
    adk_root / "flows" / "llm_flows" / "prompt" / "_instructions_utils.py",  # ADK 2.x
]

OLD_1X = "raise KeyError(f'Context variable not found: `{var_name}`.')"
NEW = "return match.group(0)  # pass through unresolvable vars"
OLD_2X = (
    "          raise KeyError(\n"
    "              f'Context variable not found: `{var_name}` in agent'\n"
    "              f\" '{readonly_context.agent_name}'.\"\n"
    "          )"
)
NEW_2X = "          return str(match.group())  # pass through unresolvable vars"

if not adk_root.exists():
    print(f"ERROR: {adk_root} not found - is the venv activated?")
    sys.exit(1)

for target in candidates:
    if not target.exists():
        continue
    text = target.read_text(encoding="utf-8")
    if NEW in text or NEW_2X in text:
        print(f"Already patched: {target.name} - nothing to do.")
        sys.exit(0)
    for old, new in ((OLD_1X, NEW), (OLD_2X, NEW_2X)):
        if old in text:
            target.write_text(text.replace(old, new), encoding="utf-8")
            print(f"Patched: {target}")
            print("ADK will now pass through unresolvable template variables.")
            sys.exit(0)

print("ADK state injection already tolerates literal braces in this version - nothing to patch.")
sys.exit(0)
