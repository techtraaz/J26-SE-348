import { FileSearch, FolderPlus, LayoutGrid, List, Upload, UploadCloud, X } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
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
import { extractionPaths } from '@/features/extraction/paths'
import type { FolderOut } from '@/features/extraction/api/types'
import { errorMessage } from '@/features/extraction/api/errors'
import { Button } from '@/features/extraction/components/Button'
import { EmptyState } from '@/features/extraction/components/EmptyState'
import { DropOverlay } from '../upload/DropOverlay'
import { UploadQueue } from '../upload/UploadQueue'
import { useUploadDropzone } from '../upload/useUploadDropzone'
import { useUploadQueue } from '../upload/useUploadQueue'
import { Breadcrumbs } from './Breadcrumbs'
import { DocumentGrid } from './DocumentGrid'
import { DocumentList } from './DocumentList'
import { DeleteFolderDialog, FolderNameDialog } from './FolderDialogs'
import { FolderCard } from './FolderCard'
import { STATUS_FILTERS, matchesFilter, parseStatusFilter } from './status'
import { useViewMode } from './useViewMode'

type Dialog =
  | { type: 'create' }
  | { type: 'rename'; folder: FolderOut }
  | { type: 'delete'; folder: FolderOut }
  | null

export function LibraryPage() {
  const { folderId } = useParams()
  const [params, setParams] = useSearchParams()
  const query = (params.get('q') ?? '').trim()
  const filter = parseStatusFilter(params.get('status'))
  const searching = query.length > 0

  const folder = useFolder(folderId)
  const subfolders = useFolders(folderId ?? null, !searching)
  const documents = useDocuments({ folder: searching ? 'all' : (folderId ?? 'root'), q: query })

  const queue = useUploadQueue(searching ? null : (folderId ?? null))
  const dropzone = useUploadDropzone(queue)
  const [view, setView] = useViewMode()
  const [dialog, setDialog] = useState<Dialog>(null)

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
      <div className="px-8 py-6">
        <EmptyState
          icon={<FileSearch size={22} />}
          title="Folder not found"
          description={errorMessage(folder.error)}
          action={
            <Link to={extractionPaths.library} className="text-sm font-medium text-indigo-600 hover:underline">
              Back to all documents
            </Link>
          }
        />
      </div>
    )
  }

  const allDocuments = documents.data?.items ?? []
  const visibleDocuments = allDocuments.filter((d) => matchesFilter(d.status, filter))
  const folders = subfolders.data?.items ?? []
  const where = folder.data?.name ?? 'Documents'

  return (
    <div {...dropzone.getRootProps({ className: 'relative min-h-full px-8 py-6 outline-none' })}>
      <input {...dropzone.getInputProps()} />
      {dropzone.isDragActive && <DropOverlay folderName={searching ? 'Documents' : where} />}

      <header className="mb-6 flex flex-wrap items-center justify-between gap-3">
        {searching ? (
          <div className="flex items-center gap-3">
            <h1 className="text-xl font-semibold text-slate-900">Results for “{query}”</h1>
            <Link to={extractionPaths.library} className="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-900">
              <X size={14} aria-hidden /> Clear search
            </Link>
          </div>
        ) : (
          <Breadcrumbs crumbs={folder.data?.breadcrumbs ?? []} />
        )}
        <div className="flex items-center gap-2">
          <div role="group" aria-label="View" className="flex rounded-md ring-1 ring-inset ring-slate-300">
            {(['list', 'grid'] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                aria-label={`${mode} view`}
                aria-pressed={view === mode}
                onClick={() => setView(mode)}
                className={clsx(
                  'flex h-9 w-9 items-center justify-center first:rounded-l-md last:rounded-r-md',
                  view === mode ? 'bg-slate-100 text-slate-900' : 'bg-white text-slate-500 hover:bg-slate-50',
                )}
              >
                {mode === 'list' ? <List size={17} /> : <LayoutGrid size={17} />}
              </button>
            ))}
          </div>
          {!searching && (
            <Button onClick={() => setDialog({ type: 'create' })}>
              <FolderPlus size={16} aria-hidden /> New folder
            </Button>
          )}
          <Button variant="primary" onClick={dropzone.open}>
            <Upload size={16} aria-hidden /> Upload
          </Button>
        </div>
      </header>

      {!searching && folders.length > 0 && (
        <section aria-label="Folders" className="mb-8">
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Folders</h2>
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
          <h2 className="mr-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Documents</h2>
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
                  'rounded-full px-3 py-1 text-xs font-medium transition-colors',
                  active
                    ? 'bg-indigo-600 text-white'
                    : 'bg-white text-slate-600 ring-1 ring-inset ring-slate-300 hover:bg-slate-50',
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
          (view === 'list' ? (
            <DocumentList
              documents={visibleDocuments}
              onRetry={(id) => retryDocument.mutate(id)}
              retrying={retryDocument.isPending}
            />
          ) : (
            <DocumentGrid documents={visibleDocuments} />
          ))}
      </section>

      <UploadQueue items={queue.items} onDismiss={queue.dismiss} onClearFinished={queue.clearFinished} />

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

function LoadingRows() {
  return (
    <div role="status" aria-label="Loading documents" className="space-y-2">
      {[0, 1, 2].map((i) => (
        <div key={i} className="h-14 animate-pulse rounded-xl bg-white ring-1 ring-slate-200" />
      ))}
    </div>
  )
}
