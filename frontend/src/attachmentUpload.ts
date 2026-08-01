export type UploadStatus = 'uploading' | 'done' | 'error'

export type UploadEntry = {
  key: string
  filename: string
  status: UploadStatus
  error?: string
  retryFile?: File
}

export function createUploadEntry(file: File): UploadEntry {
  return {
    key: `${file.name}-${Date.now()}-${Math.random().toString(36).slice(2)}`,
    filename: file.name,
    status: 'uploading',
    retryFile: file,
  }
}

export function uploadStarted(entry: UploadEntry): UploadEntry {
  return { ...entry, status: 'uploading', error: undefined }
}

export function uploadSucceeded(entry: UploadEntry): UploadEntry {
  return { ...entry, status: 'done', error: undefined }
}

export function uploadFailed(entry: UploadEntry, message: string): UploadEntry {
  return { ...entry, status: 'error', error: message }
}

export function uploadStatusLabel(status: UploadStatus): string {
  if (status === 'uploading') return '上傳中…'
  if (status === 'done') return '已上傳'
  return '上傳失敗'
}
