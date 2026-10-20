import { routes } from '@/config/routes'

// URLs of the extraction pages. They live in the Library tab (routes.documents).
export const extractionPaths = {
  library: routes.documents,
  folder: (folderId: string) => `${routes.documents}/folders/${folderId}`,
  document: (documentId: string) => `${routes.documents}/${documentId}`,
}

/** True on the library (root or a folder), where search results are shown. */
export function isLibraryPath(pathname: string): boolean {
  return pathname === routes.documents || pathname.startsWith(`${routes.documents}/folders/`)
}
