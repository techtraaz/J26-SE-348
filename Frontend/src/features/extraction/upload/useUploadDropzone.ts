import { useDropzone } from 'react-dropzone'
import type { FileRejection } from 'react-dropzone'

import { ACCEPTED_TYPES, MAX_UPLOAD_BYTES } from '@/features/extraction/config'
import { formatBytes } from '@/features/extraction/format'

export function rejectionMessage(rejection: FileRejection): string {
  const code = rejection.errors[0]?.code
  if (code === 'file-invalid-type') return 'Unsupported file type. Use PDF, PNG, JPEG, TIFF, BMP or WebP.'
  if (code === 'file-too-large') return `File is larger than ${formatBytes(MAX_UPLOAD_BYTES)}.`
  return rejection.errors[0]?.message ?? 'This file cannot be uploaded.'
}

interface Queue {
  addFiles: (files: File[]) => void
  addRejected: (rejected: { file: File; message: string }[]) => void
}

/** Drag-and-drop plus a file picker. The whole page acts as the drop target;
 * clicking is disabled on it so only the Upload button opens the picker. */
export function useUploadDropzone(queue: Queue) {
  return useDropzone({
    accept: ACCEPTED_TYPES,
    maxSize: MAX_UPLOAD_BYTES,
    multiple: true,
    noClick: true,
    noKeyboard: true,
    onDropAccepted: (files) => queue.addFiles(files),
    onDropRejected: (rejections) =>
      queue.addRejected(rejections.map((r) => ({ file: r.file, message: rejectionMessage(r) }))),
  })
}
