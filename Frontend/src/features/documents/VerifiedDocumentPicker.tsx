import { useState } from "react";
import clsx from "clsx";
import { BadgeCheck, ChevronRight, CircleAlert, Folder, LoaderCircle, Search } from "lucide-react";
import { useDocuments, useFolder, useFolders } from "@/features/extraction/api/hooks";
import { Button } from "@/features/extraction/components/Button";
import { Modal } from "@/features/extraction/components/Modal";
import { pluralize } from "@/features/extraction/format";
import { ReviewPanel } from "@/features/documents/ReviewPanel";
import { useVerifiedIntake } from "./useVerifiedIntake";

/** Add verified Component-01 documents to a case (M5.4). Nothing is uploaded
 * or typed: documents are picked from the library, C3 reads their fields, and
 * a person reviews only what C3 could not settle. */
export function VerifiedDocumentPicker({ caseId, onClose }: { caseId: string; onClose: () => void }) {
  const intake = useVerifiedIntake(caseId);
  const [picked, setPicked] = useState<Map<string, string>>(() => new Map()); // id -> filename
  const started = intake.items.length > 0;

  return (
    <Modal title={started ? `Adding to ${caseId}` : `Add verified documents to ${caseId}`} onClose={onClose} wide>
      {started ? (
        <Results intake={intake} caseId={caseId} onClose={onClose} />
      ) : (
        <>
          <Browser picked={picked} onPickedChange={setPicked} />
          <div className="mt-5 flex items-center justify-end gap-2">
            <span className="mr-auto text-[13px] text-ink-muted">
              {picked.size ? `${pluralize(picked.size, "document")} selected` : "Select verified documents"}
            </span>
            <Button onClick={onClose}>Cancel</Button>
            <Button
              variant="primary"
              disabled={picked.size === 0}
              onClick={() => intake.add([...picked].map(([id, filename]) => ({ id, filename })))}
            >
              Add to case
            </Button>
          </div>
        </>
      )}
    </Modal>
  );
}

function Browser({ picked, onPickedChange }: {
  picked: Map<string, string>;
  onPickedChange: (picked: Map<string, string>) => void;
}) {
  const [folderId, setFolderId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const q = query.trim();
  const folder = useFolder(folderId ?? undefined);
  const folders = useFolders(folderId, !q);
  const documents = useDocuments({ folder: q ? "all" : (folderId ?? "root"), q });

  const all = documents.data?.items ?? [];
  const verified = all.filter((d) => d.status === "verified");
  const notVerified = all.length - verified.length;
  const toggle = (id: string, filename: string) => {
    const next = new Map(picked);
    if (!next.delete(id)) next.set(id, filename);
    onPickedChange(next);
  };

  return (
    <div className="space-y-3">
      <div className="relative">
        <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-soft" aria-hidden />
        <input
          type="search"
          aria-label="Search verified documents"
          placeholder="Search all folders by name"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="h-9 w-full rounded-full border border-line bg-input pl-9 pr-3 text-sm text-ink-h placeholder:text-ink-soft focus:border-ink-muted focus:bg-surface focus:outline-none focus:ring-4 focus:ring-primary/10"
        />
      </div>

      {!q && (
        <nav aria-label="Folder" className="flex flex-wrap items-center gap-1 text-[13px]">
          <button type="button" onClick={() => setFolderId(null)} className={folderId ? "text-ink-muted hover:text-ink-h" : "font-medium text-ink-h"}>
            All documents
          </button>
          {(folder.data?.breadcrumbs ?? []).map((crumb, i, list) => (
            <span key={crumb.id} className="flex items-center gap-1">
              <ChevronRight size={14} className="text-ink-soft" aria-hidden />
              <button type="button" onClick={() => setFolderId(crumb.id)}
                      className={i === list.length - 1 ? "font-medium text-ink-h" : "text-ink-muted hover:text-ink-h"}>
                {crumb.name}
              </button>
            </span>
          ))}
        </nav>
      )}

      <ul className="max-h-[50vh] divide-y divide-line-light overflow-y-auto rounded-lg border border-line-light">
        {!q && (folders.data?.items ?? []).map((f) => (
          <li key={f.id}>
            <button type="button" onClick={() => setFolderId(f.id)}
                    className="flex w-full items-center gap-3 px-4 py-2.5 text-left text-sm hover:bg-canvas/60">
              <Folder size={17} strokeWidth={1.5} className="shrink-0 fill-surface-muted text-ink-muted" aria-hidden />
              <span className="min-w-0 flex-1 truncate text-ink-h">{f.name}</span>
              <ChevronRight size={15} className="text-ink-soft" aria-hidden />
            </button>
          </li>
        ))}
        {verified.map((d) => (
          <li key={d.id}>
            <label className="flex cursor-pointer items-center gap-3 px-4 py-2.5 text-sm hover:bg-canvas/60">
              <input type="checkbox" checked={picked.has(d.id)} onChange={() => toggle(d.id, d.filename)}
                     className="size-3.5 accent-primary" />
              <BadgeCheck size={16} className="shrink-0 text-success" aria-hidden />
              <span className="min-w-0 flex-1 truncate text-ink-h">{d.filename}</span>
              <span className="shrink-0 text-xs text-ink-soft">{d.page_count ? pluralize(d.page_count, "page") : ""}</span>
            </label>
          </li>
        ))}
        {documents.isPending && <li className="px-4 py-3 text-sm text-ink-muted">Loading…</li>}
        {documents.isError && <li className="px-4 py-3 text-sm text-danger">{(documents.error as Error).message}</li>}
        {documents.isSuccess && verified.length === 0 && (q || !(folders.data?.items ?? []).length) && (
          <li className="px-4 py-3 text-sm text-ink-muted">
            {q ? "No verified documents match." : "No verified documents here."}
          </li>
        )}
      </ul>
      {notVerified > 0 && (
        <p className="text-xs text-ink-soft">
          {pluralize(notVerified, "document")} here {notVerified === 1 ? "is" : "are"} not verified yet: review and
          confirm {notVerified === 1 ? "it" : "them"} in the Library first.
        </p>
      )}
    </div>
  );
}

function Results({ intake, caseId, onClose }: {
  intake: ReturnType<typeof useVerifiedIntake>;
  caseId: string;
  onClose: () => void;
}) {
  const { items } = intake;
  const reading = items.filter((i) => i.state === "reading").length;
  const added = items.filter((i) => i.state === "added").length;
  const waiting = items.filter((i) => i.state === "review").length;

  return (
    <div className="space-y-3">
      <ul className="space-y-2">
        {items.map((item) => (
          <li key={item.documentId}>
            {item.state === "review" && item.preview ? (
              <div>
                <p className="mb-1.5 text-[13px] text-warning">
                  <CircleAlert size={14} className="mr-1 inline -translate-y-px" aria-hidden />
                  Needs you: {item.message}
                </p>
                <ReviewPanel
                  name={item.name}
                  preview={item.preview}
                  parents={[]}
                  busy={Boolean(item.busy)}
                  onConfirm={(r) => void intake.confirmReview(item, r)}
                  onReread={(docType) => void intake.reread(item, docType)}
                  onDiscard={() => intake.discard(item.documentId)}
                />
              </div>
            ) : (
              <div className={clsx("flex items-start gap-2.5 rounded-lg border px-3 py-2.5 text-sm",
                item.state === "error" ? "border-danger/30 bg-danger/8" : "border-line-light")}>
                {item.state === "reading" && <LoaderCircle size={16} className="mt-0.5 shrink-0 animate-spin text-ink-muted" aria-hidden />}
                {item.state === "added" && <BadgeCheck size={16} className="mt-0.5 shrink-0 text-success" aria-hidden />}
                {item.state === "error" && <CircleAlert size={16} className="mt-0.5 shrink-0 text-danger" aria-hidden />}
                <div className="min-w-0 flex-1">
                  <p className="truncate font-medium text-ink-h">{item.name}</p>
                  <p className={clsx("text-[13px]", item.state === "error" ? "text-danger" : "text-ink-muted")}>
                    {item.state === "reading" && "Reading the fields…"}
                    {item.state === "added" && `Added to ${caseId}${item.message ? `. C3 notes: ${item.message}` : "."}`}
                    {item.state === "error" && item.message}
                  </p>
                </div>
              </div>
            )}
          </li>
        ))}
      </ul>
      <div className="flex items-center justify-end gap-2">
        <span className="mr-auto text-[13px] text-ink-muted" role="status">
          {reading ? `Reading ${reading}…` : `${added} added${waiting ? ` · ${waiting} waiting for you` : ""}`}
        </span>
        <Button variant={waiting || reading ? "secondary" : "primary"} onClick={onClose}>
          {added && !waiting && !reading ? "Done: audit from the chat" : "Close"}
        </Button>
      </div>
    </div>
  );
}
