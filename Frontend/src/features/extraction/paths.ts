import { routes } from '@/config/routes'

/** The Unfiled view: documents in no folder (a view, not a real folder). */
export const UNFILED = 'unfiled'

// URLs of the extraction pages. They live in the Library tab (routes.documents):
// "All documents" is the tab's home, "Folders" its second tab.
export const extractionPaths = {
  library: routes.documents,
  folders: `${routes.documents}/folders`,
  unfiled: `${routes.documents}/folders/${UNFILED}`,
  folder: (folderId: string) => `${routes.documents}/folders/${folderId}`,
  document: (documentId: string) => `${routes.documents}/${documentId}`,
}

/** True on a library listing (All documents, Folders, a folder), where search results are shown. */
export function isLibraryPath(pathname: string): boolean {
  return (
    pathname === routes.documents ||
    pathname === extractionPaths.folders ||
    pathname.startsWith(`${extractionPaths.folders}/`)
  )
}
