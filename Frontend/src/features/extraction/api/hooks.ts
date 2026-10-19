import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { POLL_INTERVAL_MS } from '@/features/extraction/config'
import { api, call, callVoid } from './client'
import { isActiveStatus } from './types'

// Every Component-01 key starts with 'c1', so these queries never mix with the
// rest of the app's and get their own defaults (see app/providers.tsx).
export const queryKeys = {
  all: ['c1'] as const,
  allFolders: ['c1', 'folders'] as const,
  allDocuments: ['c1', 'documents'] as const,
  folders: (parentId: string | null) => ['c1', 'folders', 'list', parentId ?? 'root'] as const,
  folder: (id: string) => ['c1', 'folders', 'detail', id] as const,
  documents: (scope: string) => ['c1', 'documents', 'list', scope] as const,
  document: (id: string) => ['c1', 'documents', 'detail', id] as const,
  extraction: (id: string) => ['c1', 'documents', 'extraction', id] as const,
  review: (id: string) => ['c1', 'documents', 'review', id] as const,
  verified: (id: string) => ['c1', 'documents', 'verified', id] as const,
}

export function useFolders(parentId: string | null, enabled = true) {
  return useQuery({
    queryKey: queryKeys.folders(parentId),
    enabled,
    queryFn: () =>
      call(api.GET('/api/v1/folders', { params: { query: { parent_id: parentId } } })),
  })
}

export function useFolder(folderId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.folder(folderId ?? ''),
    enabled: !!folderId,
    queryFn: () =>
      call(api.GET('/api/v1/folders/{folder_id}', { params: { path: { folder_id: folderId! } } })),
  })
}

export interface DocumentScope {
  /** A folder id, 'root' for documents outside any folder, or 'all' (search). */
  folder: string
  q?: string
}

/** Documents in one place. Polls while any of them is still being processed. */
export function useDocuments({ folder, q }: DocumentScope) {
  return useQuery({
    queryKey: queryKeys.documents(`${folder}|${q ?? ''}`),
    placeholderData: keepPreviousData,
    queryFn: () =>
      call(
        api.GET('/api/v1/documents', {
          params: {
            query: {
              folder_id: folder !== 'root' && folder !== 'all' ? folder : undefined,
              root_only: folder === 'root' ? true : undefined,
              q: q || undefined,
              limit: 200,
            },
          },
        }),
      ),
    refetchInterval: (query) =>
      query.state.data?.items.some((d) => isActiveStatus(d.status)) ? POLL_INTERVAL_MS : false,
  })
}

export function useDocument(documentId: string) {
  return useQuery({
    queryKey: queryKeys.document(documentId),
    queryFn: () =>
      call(
        api.GET('/api/v1/documents/{document_id}', { params: { path: { document_id: documentId } } }),
      ),
    refetchInterval: (query) =>
      query.state.data && isActiveStatus(query.state.data.status) ? POLL_INTERVAL_MS : false,
  })
}

export function useExtraction(documentId: string, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.extraction(documentId),
    enabled,
    queryFn: () =>
      call(
        api.GET('/api/v1/documents/{document_id}/extraction', {
          params: { path: { document_id: documentId } },
        }),
      ),
  })
}

/** The reviewer's draft (seeded from the latest run until the first save). */
export function useReviewDraft(documentId: string, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.review(documentId),
    enabled,
    queryFn: () =>
      call(
        api.GET('/api/v1/documents/{document_id}/review', {
          params: { path: { document_id: documentId } },
        }),
      ),
  })
}

/** The latest verified version of a document. */
export function useVerifiedRecord(documentId: string, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.verified(documentId),
    enabled,
    queryFn: () =>
      call(
        api.GET('/api/v1/documents/{document_id}/verified', {
          params: { path: { document_id: documentId } },
        }),
      ),
  })
}

/** Freeze the draft at `version` as the next verified version. */
export function useConfirmDocument(documentId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (version: number) =>
      call(
        api.POST('/api/v1/documents/{document_id}/confirm', {
          params: { path: { document_id: documentId } },
          body: { version },
        }),
      ),
    onSuccess: (record) => {
      // The response is the new verified version: show it at once, not a cached older one.
      queryClient.setQueryData(queryKeys.verified(documentId), record)
      return queryClient.invalidateQueries({ queryKey: queryKeys.allDocuments })
    },
  })
}

/** Return a verified document to review (the next confirm makes a new version). */
export function useReopenDocument(documentId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () =>
      callVoid(
        api.POST('/api/v1/documents/{document_id}/reopen', {
          params: { path: { document_id: documentId } },
        }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.allDocuments }),
  })
}

export function useCreateFolder() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: { name: string; parentId: string | null }) =>
      call(api.POST('/api/v1/folders', { body: { name: input.name, parent_id: input.parentId } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.allFolders }),
  })
}

export function useRenameFolder() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: { id: string; name: string }) =>
      call(
        api.PATCH('/api/v1/folders/{folder_id}', {
          params: { path: { folder_id: input.id } },
          body: { name: input.name },
        }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.allFolders }),
  })
}

export function useDeleteFolder() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      callVoid(api.DELETE('/api/v1/folders/{folder_id}', { params: { path: { folder_id: id } } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.allFolders }),
  })
}

export function useRetryDocument() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      call(
        api.POST('/api/v1/documents/{document_id}/retry', {
          params: { path: { document_id: id } },
        }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.allDocuments }),
  })
}
