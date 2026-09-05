import re
from pathlib import Path

BANNED = re.compile(r"\b(requests|httpx)\b|datetime\.now\(|time\.time\(|\brandom\b")


def test_no_io_clocks_or_randomness_in_workflows():
    offenders = []
    for path in Path("python/workflows").rglob("*.py"):
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if line.strip().startswith("#"):
                continue
            if BANNED.search(line):
                offenders.append(f"{path}:{lineno}: {line.strip()}")
    assert not offenders, (
        "workflow code must not do I/O, read clocks, or use randomness "
        "(§16.6). Use workflow.now() and workflow.uuid4().\n" + "\n".join(offenders))
