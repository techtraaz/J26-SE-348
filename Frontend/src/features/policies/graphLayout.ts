import type { GraphNode, KgChanges } from "@/types/policies";

// Radial picture of one run: the standard in the middle, its paragraphs (Sections) on
// a ring, and what was extracted from each paragraph on an outer ring.

export interface Placed {
  node: GraphNode;
  x: number;
  y: number;
  ring: 0 | 1 | 2;
}

export interface Edge {
  from: Placed;
  to: Placed;
  fresh: boolean; // leads to a new node
}

export interface Layout {
  center: Placed | null;
  nodes: Placed[];
  edges: Edge[];
  hiddenSections: number;
  hiddenChildren: number;
}

export const KG_COLORS: Record<string, string> = {
  Standard: "var(--kg-standard)",
  Document: "var(--kg-standard)",
  Section: "var(--kg-section)",
  Requirement: "var(--kg-requirement)",
  Definition: "var(--kg-definition)",
  Equation: "var(--kg-equation)",
};

export const SIZE = 640;
const R1 = 155;
const R2 = 265;

export function sectionNumber(key: string): string {
  return key.includes(":") ? key.slice(key.lastIndexOf(":") + 1) : key;
}

export function layoutChanges(graph: KgChanges["graph"], title: string, maxSections = 24,
                              maxChildren = 8): Layout {
  const byId = new Map(graph.nodes.map((n) => [n.id, n]));
  const children = new Map<string, string[]>();
  const own: string[] = [];
  for (const l of graph.links) {
    if (l.type === "HAS_SECTION") own.push(l.target);
    const pair = l.type === "HAS_REQUIREMENT" || l.type === "DEFINES" ? [l.source, l.target]
      : l.type === "DERIVED_FROM" ? [l.target, l.source] : null;
    if (!pair || !pair[0].startsWith("Section:")) continue;
    const list = children.get(pair[0]) ?? [];
    if (!list.includes(pair[1])) list.push(pair[1]);
    children.set(pair[0], list);
  }
  // an Act has no Standard node: then every Section of the plan is its own
  const sections = (own.length ? own : graph.nodes.filter((n) => n.label === "Section" && n.caption !== n.key)
    .map((n) => n.id)).filter((id, i, all) => byId.has(id) && all.indexOf(id) === i);

  const isNew = (id: string) => byId.get(id)?.new ?? false;
  const score = (id: string) => {
    const kids = children.get(id) ?? [];
    return kids.filter(isNew).length * 100 + kids.length * 10 + (isNew(id) ? 1 : 0);
  };
  const order = new Map(sections.map((id, i) => [id, i]));
  const shown = [...sections].sort((a, b) => score(b) - score(a) || order.get(a)! - order.get(b)!)
    .slice(0, maxSections).sort((a, b) => order.get(a)! - order.get(b)!);

  const c = SIZE / 2;
  const standard = graph.nodes.find((n) => n.label === "Standard");
  const center: Placed = {
    node: standard ?? { id: "doc", label: "Document", key: title, caption: title, new: false },
    x: c, y: c, ring: 0,
  };
  const nodes: Placed[] = [center];
  const edges: Edge[] = [];
  let hiddenChildren = 0;
  const slice = (2 * Math.PI) / Math.max(shown.length, 1);

  shown.forEach((sid, i) => {
    const angle = -Math.PI / 2 + i * slice;
    const sec: Placed = { node: byId.get(sid)!, x: c + R1 * Math.cos(angle), y: c + R1 * Math.sin(angle), ring: 1 };
    nodes.push(sec);
    edges.push({ from: center, to: sec, fresh: sec.node.new });

    const all = (children.get(sid) ?? []).filter((id) => byId.has(id));
    const kids = [...all].sort((a, b) => Number(isNew(b)) - Number(isNew(a))).slice(0, maxChildren);
    hiddenChildren += all.length - kids.length;
    const span = Math.min(slice * 0.8, kids.length * 0.13);
    kids.forEach((kid, j) => {
      const a = kids.length === 1 ? angle : angle - span / 2 + (j * span) / (kids.length - 1);
      const placed: Placed = { node: byId.get(kid)!, x: c + R2 * Math.cos(a), y: c + R2 * Math.sin(a), ring: 2 };
      nodes.push(placed);
      edges.push({ from: sec, to: placed, fresh: placed.node.new });
    });
  });
  return { center, nodes, edges, hiddenSections: sections.length - shown.length, hiddenChildren };
}
