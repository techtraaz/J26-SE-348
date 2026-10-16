from pathlib import Path

from app.construction.context import SeedReader
from app.construction.llm import FakeLLM
from app.construction.pipeline import KGPipeline
from app.ontology.diagram import markdown
from app.ontology.model import load_ontology

ONTOLOGY_DOC = Path("docs/ontology.md")
KG_DOC = Path("docs/kg_construction.md")
START, END = "<!-- generated:start -->", "<!-- generated:end -->"


def _replace(text: str, block: str) -> str:
    head, _, rest = text.partition(START)
    _, _, tail = rest.partition(END)
    return f"{head}{START}\n{block}\n{END}{tail}"


def render(text: str) -> str:
    return _replace(text, markdown(load_ontology()))


def render_kg(text: str) -> str:
    diagram = KGPipeline(FakeLLM(), SeedReader()).mermaid().strip()
    return _replace(text, f"```mermaid\n{diagram}\n```")


if __name__ == "__main__":
    for doc, fn in ((ONTOLOGY_DOC, render), (KG_DOC, render_kg)):
        doc.write_text(fn(doc.read_text(encoding="utf-8")), encoding="utf-8")
        print(f"Updated {doc}")
