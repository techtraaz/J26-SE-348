from pathlib import Path

from app.ontology.diagram import markdown
from app.ontology.model import load_ontology

DOC = Path("docs/ontology.md")
START, END = "<!-- generated:start -->", "<!-- generated:end -->"


def render(text: str) -> str:
    head, _, rest = text.partition(START)
    _, _, tail = rest.partition(END)
    return f"{head}{START}\n{markdown(load_ontology())}\n{END}{tail}"


if __name__ == "__main__":
    DOC.write_text(render(DOC.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"Updated {DOC}")
