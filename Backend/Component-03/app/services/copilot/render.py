"""Reply blocks as Markdown: the one place a reply's text layout is decided.

Handlers build blocks (app.schemas.copilot); every reply's `reply` text comes from
here, so all intents read alike and a new intent needs no formatting of its own.
"""
from app.schemas.copilot import (
    Block,
    FindingsBlock,
    LinkBlock,
    ListBlock,
    QuestionBlock,
    TableBlock,
    TextBlock,
    VerdictBlock,
)

VERDICT_WORDS = {"clean": "Clean", "issues_found": "Issues found", "needs_review": "Needs review",
                 "not_auditable": "Not auditable"}
TONE_WORDS = {"passed": "passed", "failed": "failed", "review": "needs confirmation",
              "skipped": "not checked", "high": "high", "medium": "medium", "low": "low"}


def _cell(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _more(n: int) -> list[str]:
    return [f"- …and {n} more"] if n else []


def _list(b: ListBlock) -> list[str]:
    out = [f"**{b.title}**"] if b.title else []
    for item in b.items:
        tone = f" ({TONE_WORDS[item.tone]})" if item.tone in TONE_WORDS else ""
        text = f": {item.text}" if item.text else ""
        out.append(f"- **{item.label}**{tone}{text}")
        out += [f"  - {d}" for d in item.details]
    return out + _more(b.more)


def _table(b: TableBlock) -> list[str]:
    out = [f"**{b.title}**", ""] if b.title else []
    out.append("| " + " | ".join(_cell(c) for c in b.columns) + " |")
    out.append("|" + "|".join(" --- " for _ in b.columns) + "|")
    out += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in b.rows]
    return out


def _findings(b: FindingsBlock) -> list[str]:
    out = [f"**{b.title}**"] if b.title else []
    return out + [f"- {line}" for line in b.lines] + _more(b.more)


def _verdict(b: VerdictBlock) -> list[str]:
    score = f" · score {b.score}/100" if b.score is not None else ""
    head = f"**{VERDICT_WORDS.get(b.verdict, b.verdict)}**{score} · case {b.case_id}, version {b.version}"
    return [head] + ([b.summary] if b.summary else [])


def _question(b: QuestionBlock) -> list[str]:
    return [b.text] + [f"- {c}" for c in b.choices]


def _link(b: LinkBlock) -> list[str]:
    return [f"[{b.label}]({b.url})"]


_RENDER = {TextBlock: lambda b: [b.text], ListBlock: _list, TableBlock: _table,
           FindingsBlock: _findings, VerdictBlock: _verdict, QuestionBlock: _question,
           LinkBlock: _link}


def to_markdown(blocks: list[Block]) -> str:
    """Blocks in order, separated by a blank line."""
    return "\n\n".join("\n".join(_RENDER[type(b)](b)) for b in blocks).strip()
