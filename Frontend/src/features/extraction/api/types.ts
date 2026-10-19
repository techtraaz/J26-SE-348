import type { components } from './generated/schema'

type Schemas = components['schemas']

export type DocumentOut = Schemas['DocumentOut']
export type DocumentDetail = Schemas['DocumentDetail']
export type FolderOut = Schemas['FolderOut']
export type FolderDetail = Schemas['FolderDetail']
export type ExtractionOut = Schemas['ExtractionOut']
export type RegionOut = Schemas['RegionOut']
export type RunSummary = Schemas['RunSummary']
export type PageOut = Schemas['PageOut']
export type ReviewDraft = Schemas['ReviewDraftOut']
export type DraftLine = Schemas['DraftLine']
export type VerifiedRecord = Schemas['VerifiedRecordOut']

/** The API returns status as a plain string; these are its known values. */
export type DocumentStatus = 'uploaded' | 'processing' | 'needs_review' | 'verified' | 'failed'

export function isActiveStatus(status: string): boolean {
  return status === 'uploaded' || status === 'processing'
}
