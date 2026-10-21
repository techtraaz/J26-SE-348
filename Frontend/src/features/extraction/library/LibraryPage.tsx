import { FileSearch, Files, FolderPlus, Folders, LayoutGrid, List, Upload, UploadCloud, X } from 'lucide-react'
import { useState } from 'react'
import { Link, NavLink, useParams, useSearchParams } from 'react-router-dom'
import clsx from 'clsx'

import {
  useCreateFolder,
  useDeleteFolder,
  useDocuments,
  useFolder,
  useFolders,
  useRenameFolder,
  useRetryDocument,
} from '@/features/extraction/api/hooks'
import { UNFILED, extractionPaths } from '@/features/extraction/paths'
import type { FolderOut } from '@/features/extraction/api/types'
import { errorMessage } from '@/features/extraction/api/errors'
import { Button } from '@/features/extraction/components/Button'
import { EmptyState } from '@/features/extraction/components/EmptyState'
import { pluralize } from '@/features/extraction/format'
import { DropOverlay } from '../upload/DropOverlay'
import { UploadQueue } from '../upload/UploadQueue'
import { useUploadDropzone } from '../upload/useUploadDropzone'
import { useUploadQueue } from '../upload/useUploadQueue'
import { Breadcrumbs } from './Breadcrumbs'
import { DocumentGrid } from './DocumentGrid'
import { DocumentList } from './DocumentList'
import { DeleteFolderDialog, FolderNameDialog } from './FolderDialogs'
import { FolderCard, UnfiledCard } from './FolderCard'
import { STATUS_FILTERS, matchesFilter, parseStatusFilter } from './status'
import { useDocumentActions } from './useDocumentActions'
import { useViewMode } from './useViewMode'

type Dialog =
  | { type: 'create' }
  | { type: 'rename'; folder: FolderOut }
  | { type: 'delete'; folder: FolderOut }
  | null

/** The Library's two tabs.
 *  - "all":     every document, wherever it is filed (with its folder).
 *  - "folders": folder cards with Unfiled first; inside a folder, its subfolders
 *               and documents; Unfiled lists the documents in no folder.
 * Uploads go into the folder you are in, anywhere else into Unfiled. */
export function LibraryPage({ view }: { view: 'all' | 'folders' }) {
  const { folderId: param } = useParams()
  const [params, setParams] = useSearchParams()
  const query = (params.get('q') ?? '').trim()
  const filter = parseStatusFilter(params.get('status'))
  const searching = query.length > 0

  const unfiled = view === 'folders' && param === UNFILED
  const folderId = view === 'folders' && param && !unfiled ? param : undefined
  const foldersHome = view === 'folders' && !param && !searching

  const folder = useFolder(folderId)
  const subfolders = useFolders(folderId ?? null, view === 'folders' && !unfiled && !searching)
  const scope = searching || view === 'all' ? 'all' : (folderId ?? 'root')
  // On the Folders home only Unfiled's count is needed, so one document is enough.
  const documents = useDocuments({ folder: scope, q: query, limit: foldersHome ? 1 : 200 })

  const queue = useUploadQueue(folderId ?? null)
  const dropzone = useUploadDropzone(queue)
  const [mode, setMode] = useViewMode()
  const [dialog, setDialog] = useState<Dialog>(null)
  const actions = useDocumentActions()

  const createFolder = useCreateFolder()
  const renameFolder = useRenameFolder()
  const deleteFolder = useDeleteFolder()
  const retryDocument = useRetryDocument()

  const setFilter = (id: string) => {
    const next = new URLSearchParams(params)
    if (id === 'all') next.delete('status')
    else next.set('status', id)
    setParams(next, { replace: true })
  }

  if (folderId && folder.isError) {
    return (
      <div className="px-8 pb-12">
        <LibraryTabs />
        <EmptyState
          icon={<FileSearch size={22} />}
          title="Folder not found"
          description={errorMessage(folder.error)}
          action={
            <Link to={extractionPaths.folders} className="text-sm font-medium text-ink-h underline-offset-2 hover:underline">
              Back to folders
            </Link>
          }
        />
      </div>
    )
  }

  const allDocuments = documents.data?.items ?? []
  const visibleDocuments = allDocuments.filter((d) => matchesFilter(d.status, filter))
  const folders = subfolders.data?.items ?? []
  const where = folderId ? (folder.data?.name ?? 'this folder') : 'Unfiled'
  const showFolder = searching || view === 'all'
  const canCreateFolder = view === 'folders' && !unfiled && !searching

  const crumbs = [
    { name: 'Folders', to: extractionPaths.folders },
    ...(unfiled ? [{ name: 'Unfiled' }] : []),
    ...(folder.data?.breadcrumbs ?? []).map((c) => ({ name: c.name, to: extractionPaths.folder(c.id) })),
  ]

  return (
    <div {...dropzone.getRootProps({ className: 'relative min-h-full px-8 pb-12 outline-none' })}>
      <input {...dropzone.getInputProps()} />
      {dropzone.isDragActive && <DropOverlay folderName={where} />}

      <LibraryTabs />

      <header className="mb-6 flex flex-wrap items-center justify-between gap-3 border-b border-line-light pb-4">
        {searching ? (
          <div className="flex items-center gap-3">
            <h2 className="text-[15px] font-medium text-ink-h">Results for “{query}”</h2>
            <Link
              to={view === 'all' ? extractionPaths.library : extractionPaths.folders}
              className="inline-flex items-center gap-1 text-sm text-ink-muted hover:text-ink-h"
            >
              <X size={14} aria-hidden /> Clear search
            </Link>
          </div>
        ) : view === 'all' ? (
          <h2 className="text-[15px] font-medium text-ink-h">
            All documents
            {documents.data && <span className="ml-2 font-normal text-ink-muted">{documents.data.total}</span>}
          </h2>
        ) : (
          <Breadcrumbs crumbs={crumbs} />
        )}
        <div className="flex items-center gap-2">
          {!foldersHome && (
            <div role="group" aria-label="View" className="flex rounded-full border border-line bg-surface p-0.5">
              {(['list', 'grid'] as const).map((m) => (
                <button
                  key={m}
                  type="button"
                  aria-label={`${m} view`}
                  aria-pressed={mode === m}
                  onClick={() => setMode(m)}
                  className={clsx(
                    'flex size-8 items-center justify-center rounded-full transition-colors',
                    mode === m ? 'bg-surface-muted text-ink-h' : 'text-ink-muted hover:text-ink-h',
                  )}
                >
                  {m === 'list' ? <List size={17} /> : <LayoutGrid size={17} />}
                </button>
              ))}
            </div>
          )}
          {canCreateFolder && (
            <Button onClick={() => setDialog({ type: 'create' })}>
              <FolderPlus size={16} aria-hidden /> New folder
            </Button>
          )}
          <Button variant="primary" onClick={dropzone.open} title={`Upload into ${where}`}>
            <Upload size={16} aria-hidden /> Upload
          </Button>
        </div>
      </header>

      {foldersHome ? (
        <section aria-label="Folders">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            <UnfiledCard count={documents.data?.total} />
            {folders.map((f) => (
              <FolderCard
                key={f.id}
                folder={f}
                onRename={(target) => setDialog({ type: 'rename', folder: target })}
                onDelete={(target) => setDialog({ type: 'delete', folder: target })}
              />
            ))}
          </div>
          {subfolders.isSuccess && folders.length === 0 && (
            <p className="mt-4 text-[13px] text-ink-muted">
              No folders yet. Create one with New folder, then move documents into it from their ⋯ menu.
            </p>
          )}
        </section>
      ) : (
        <>
          {!searching && !unfiled && view === 'folders' && folders.length > 0 && (
            <section aria-label="Folders" className="mb-8">
              <h2 className="mb-3 text-[15px] font-semibold text-ink-h">Folders</h2>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                {folders.map((f) => (
                  <FolderCard
                    key={f.id}
                    folder={f}
                    onRename={(target) => setDialog({ type: 'rename', folder: target })}
                    onDelete={(target) => setDialog({ type: 'delete', folder: target })}
                  />
                ))}
              </div>
            </section>
          )}

          <section aria-label="Documents">
            <div className="mb-3 flex flex-wrap items-center gap-2">
              {/* Inside a folder, this separates documents from subfolders; elsewhere the title says it. */}
              {folderId && <h2 className="mr-2 text-[15px] font-semibold text-ink-h">Documents</h2>}
              {STATUS_FILTERS.map(({ id, label }) => {
                const count = allDocuments.filter((d) => matchesFilter(d.status, id)).length
                const active = filter === id
                return (
                  <button
                    key={id}
                    type="button"
                    aria-pressed={active}
                    onClick={() => setFilter(id)}
                    className={clsx(
                      'rounded-full border px-3 py-1 text-xs font-medium transition-colors',
                      active
                        ? 'border-transparent bg-primary text-canvas'
                        : 'border-line bg-surface text-ink hover:bg-surface-muted',
                    )}
                  >
                    {label}
                    {id !== 'all' && count > 0 && <span className="ml-1.5 opacity-70">{count}</span>}
                  </button>
                )
              })}
            </div>

            {documents.isPending && <LoadingRows />}

            {documents.isError && (
              <EmptyState
                icon={<FileSearch size={22} />}
                title="Could not load documents"
                description={errorMessage(documents.error)}
                action={<Button onClick={() => void documents.refetch()}>Try again</Button>}
              />
            )}

            {documents.isSuccess && visibleDocuments.length === 0 && (
              <EmptyState
                icon={<UploadCloud size={22} />}
                title={
                  searching
                    ? 'No documents match your search'
                    : allDocuments.length > 0
                      ? 'No documents with this status'
                      : unfiled
                        ? 'Nothing unfiled: every document is in a folder'
                        : 'No documents here yet'
                }
                description={
                  searching || allDocuments.length > 0
                    ? undefined
                    : 'Drag files onto this page or use Upload. PDF, PNG, JPEG, TIFF, BMP and WebP are supported.'
                }
                action={
                  !searching && allDocuments.length === 0 ? (
                    <Button variant="primary" onClick={dropzone.open}>
                      <Upload size={16} aria-hidden /> Upload documents
                    </Button>
                  ) : undefined
                }
              />
            )}

            {documents.isSuccess &&
              visibleDocuments.length > 0 &&
              (mode === 'list' ? (
                <DocumentList
                  documents={visibleDocuments}
                  onRetry={(id) => retryDocument.mutate(id)}
                  retrying={retryDocument.isPending}
                  onAction={actions.open}
                  showFolder={showFolder}
                />
              ) : (
                <DocumentGrid documents={visibleDocuments} onAction={actions.open} showFolder={showFolder} />
              ))}
            {documents.data && documents.data.total > allDocuments.length && (
              <p className="mt-3 text-xs text-ink-soft">
                Showing the newest {allDocuments.length} of {pluralize(documents.data.total, 'document')}. Search by
                name to find older ones.
              </p>
            )}
          </section>
        </>
      )}

      <UploadQueue items={queue.items} onDismiss={queue.dismiss} onClearFinished={queue.clearFinished} />
      {actions.dialog}

      {dialog?.type === 'create' && (
        <FolderNameDialog
          title="New folder"
          submitLabel="Create"
          onSubmit={(name) => createFolder.mutateAsync({ name, parentId: folderId ?? null })}
          onClose={() => setDialog(null)}
        />
      )}
      {dialog?.type === 'rename' && (
        <FolderNameDialog
          title="Rename folder"
          initialName={dialog.folder.name}
          submitLabel="Rename"
          onSubmit={(name) => renameFolder.mutateAsync({ id: dialog.folder.id, name })}
          onClose={() => setDialog(null)}
        />
      )}
      {dialog?.type === 'delete' && (
        <DeleteFolderDialog
          folderName={dialog.folder.name}
          onConfirm={() => deleteFolder.mutateAsync(dialog.folder.id)}
          onClose={() => setDialog(null)}
        />
      )}
    </div>
  )
}

/** "All documents" | "Folders": tabs inside the Library, kept by URL. */
function LibraryTabs() {
  const tab = ({ isActive }: { isActive: boolean }) =>
    clsx(
      '-mb-px inline-flex items-center gap-2 border-b-2 px-1 pb-2.5 text-sm font-medium transition-colors',
      isActive ? 'border-primary text-ink-h' : 'border-transparent text-ink-muted hover:text-ink-h',
    )
  return (
    <nav aria-label="Library" className="mb-5 flex gap-6 border-b border-line-light">
      <NavLink to={extractionPaths.library} end className={tab}>
        <Files size={16} aria-hidden /> All documents
      </NavLink>
      <NavLink to={extractionPaths.folders} className={tab}>
        <Folders size={16} aria-hidden /> Folders
      </NavLink>
    </nav>
  )
}

function LoadingRows() {
  return (
    <div role="status" aria-label="Loading documents" className="space-y-2">
      {[0, 1, 2].map((i) => (
        <div key={i} className="h-14 animate-pulse rounded-lg border border-line-light bg-surface" />
      ))}
    </div>
  )
}
