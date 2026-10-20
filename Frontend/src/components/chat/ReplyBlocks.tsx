import { FindingCard } from "@/components/audit/FindingCard";
import type { Finding, ListItem, ReplyBlock, Tone } from "@/types/audit";
import { Markdown } from "./Markdown";

const VERDICT: Record<string, { label: string; tone: Tone }> = {
  clean: { label: "Clean", tone: "passed" },
  issues_found: { label: "Issues found", tone: "failed" },
  needs_review: { label: "Needs review", tone: "review" },
  not_auditable: { label: "Not auditable", tone: "skipped" },
};
const TONE_LABEL: Partial<Record<Tone, string>> = {
  passed: "passed", failed: "failed", review: "needs confirmation", skipped: "not checked",
  high: "high", medium: "medium", low: "low",
};

/** A Copilot reply drawn from its blocks: one component per block type, so every
 *  intent looks alike and a new intent needs no UI work. */
export function ReplyBlocks({ blocks, findings, onPick, disabled }: {
  blocks: ReplyBlock[];
  findings: Finding[]; // the message's findings, for finding cards
  onPick: (text: string) => void; // a choice is sent back as the user's next message
  disabled: boolean;
}) {
  const byId = new Map(findings.map((f) => [f.finding_id, f]));
  return (
    <div className="reply-blocks">
      {blocks.map((b, i) => {
        switch (b.type) {
          case "text":
            return <Markdown key={i} text={b.text} />;
          case "list":
            return <ItemList key={i} title={b.title} items={b.items} more={b.more} />;
          case "table":
            return <Table key={i} title={b.title} columns={b.columns} rows={b.rows} />;
          case "findings":
            return <FindingList key={i} title={b.title} ids={b.finding_ids} lines={b.lines} more={b.more} byId={byId} />;
          case "verdict":
            return <Verdict key={i} {...b} />;
          case "question":
            return <Question key={i} text={b.text} choices={b.choices} onPick={onPick} disabled={disabled} />;
          case "link":
            return <a key={i} className="reply-link" href={b.url} target="_blank" rel="noreferrer">{b.label}</a>;
        }
      })}
    </div>
  );
}

export function ToneChip({ tone }: { tone: Tone }) {
  const label = TONE_LABEL[tone];
  return label ? <span className={`tone-chip tone-${tone}`}>{label}</span> : null;
}

function ItemList({ title, items, more }: { title: string; items: ListItem[]; more: number }) {
  return (
    <section className="reply-section">
      {title && <h4>{title}</h4>}
      <ul className="reply-list">
        {items.map((item, i) => (
          <li key={i}>
            <div className="reply-item-head">
              <span className="reply-item-label">{item.label}</span>
              <ToneChip tone={item.tone} />
            </div>
            {item.text && <Markdown text={item.text} />}
            {item.details.length > 0 && (
              <ul className="reply-details">{item.details.map((d, j) => <li key={j}>{d}</li>)}</ul>
            )}
          </li>
        ))}
      </ul>
      {more > 0 && <p className="reply-more">…and {more} more</p>}
    </section>
  );
}

function Table({ title, columns, rows }: { title: string; columns: string[]; rows: string[][] }) {
  return (
    <section className="reply-section">
      {title && <h4>{title}</h4>}
      <div className="md-table">
        <table>
          <thead><tr>{columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
          <tbody>{rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j}>{c}</td>)}</tr>)}</tbody>
        </table>
      </div>
    </section>
  );
}

function FindingList({ title, ids, lines, more, byId }: {
  title: string; ids: string[]; lines: string[]; more: number; byId: Map<string, Finding>;
}) {
  return (
    <section className="reply-section">
      {title && <h4>{title}</h4>}
      <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
        {ids.map((id, i) => {
          const f = byId.get(id);
          return f ? <FindingCard key={id} f={f} /> : <p key={id} className="reply-more">{lines[i]}</p>;
        })}
      </div>
      {more > 0 && <p className="reply-more">…and {more} more</p>}
    </section>
  );
}

function Verdict({ verdict, score, summary, case_id, version }: {
  verdict: string; score: number | null; summary: string; case_id: string; version: number;
}) {
  const v = VERDICT[verdict] ?? { label: verdict, tone: "neutral" as Tone };
  return (
    <div className={`verdict-card tone-border-${v.tone}`}>
      <div className="verdict-head">
        <span className={`tone-chip tone-${v.tone}`}>{v.label}</span>
        {score !== null && <span className="verdict-score">{score}<small>/100</small></span>}
      </div>
      {summary && <p>{summary}</p>}
      <p className="reply-more">Case {case_id} · version {version}</p>
    </div>
  );
}

function Question({ text, choices, onPick, disabled }: {
  text: string; choices: string[]; onPick: (t: string) => void; disabled: boolean;
}) {
  return (
    <section className="reply-section">
      <Markdown text={text} />
      {choices.length > 0 && (
        <div className="reply-choices">
          {choices.map((c) => (
            <button key={c} type="button" onClick={() => onPick(c)} disabled={disabled}>{c}</button>
          ))}
        </div>
      )}
    </section>
  );
}
