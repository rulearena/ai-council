import { ref, watch, type Ref } from 'vue'
import {
  createUploadEntry,
  uploadFailed,
  uploadStarted,
  uploadSucceeded,
  type UploadEntry,
} from './attachmentUpload.ts'

export type TextDraft = { filename: string; content: string } | null

export type MaterialUploadsBoundary = {
  meetingId: () => string | undefined
  uploadAttachment: (meetingId: string, file: File) => Promise<unknown>
  openMeeting: (meetingId: string) => Promise<unknown>
  openMaterialsTab?: () => void
  /**
   * 文字檔是否導向 case-files 表單分流（非聊天室＝true 預設）。聊天室傳
   * () => !isChatroom（false）時，.txt/.md 也直接走附件上傳。
   */
  routeTextToCaseFiles?: () => boolean
}

function textExtension(filename: string): boolean {
  return /\.(txt|md)$/i.test(filename)
}

function caughtMessage(caught: unknown): string {
  if (caught instanceof Error && typeof (caught as Error & { detail?: unknown }).detail === 'string') {
    return (caught as Error & { detail: string }).detail
  }
  return caught instanceof Error ? caught.message : String(caught)
}

/**
 * 附件上傳狀態機（聊天室 composer／ActionBar 快速選單共用的 composable）。
 * - 二進位檔：進入 uploads 並立即 startUpload（uploadAttachment → openMeeting 刷新）。
 * - .txt/.md：routeTextToCaseFiles() 為 true（非聊天室預設）時進入 textDraft
 *   （標題＝去副檔名檔名、內容＝檔案文字），並呼叫 openMaterialsTab() 開啟側欄
 *   資料頁讓使用者預填確認；為 false（聊天室）時直接 startUpload（後端自動成
 *   為 case-files）。
 * boundary（uploadAttachment、openMeeting、openMaterialsTab、routeTextToCaseFiles）
 * 由父層注入，unit 可注入 fake 不碰網路。
 * 跨會議切換時清空 uploads 與 textDraft，沿用原本 CaseMaterialsModal 的行為。
 */
export function useMaterialUploads(boundary: MaterialUploadsBoundary) {
  const uploads: Ref<UploadEntry[]> = ref([])
  const textDraft: Ref<TextDraft> = ref(null)

  watch(
    () => boundary.meetingId(),
    () => {
      uploads.value = []
      textDraft.value = null
    },
  )

  function replaceUpload(entry: UploadEntry, next: UploadEntry) {
    uploads.value = uploads.value.map((item) => (item.key === entry.key ? next : item))
  }

  async function startUpload(entry: UploadEntry) {
    const meetingId = boundary.meetingId()
    const file = entry.retryFile
    if (!file || !meetingId) return
    replaceUpload(entry, uploadStarted(entry))
    try {
      await boundary.uploadAttachment(meetingId, file)
      replaceUpload(entry, uploadSucceeded(entry))
      // The meeting payload carries attachments_summary + the new attachment event,
      // so the count and the feed bubble both come from one refresh.
      await boundary.openMeeting(meetingId)
    } catch (caught) {
      replaceUpload(entry, uploadFailed(entry, caughtMessage(caught)))
    }
  }

  function retryUpload(entry: UploadEntry) {
    void startUpload(entry)
  }

  function dismissUpload(entry: UploadEntry) {
    uploads.value = uploads.value.filter((item) => item.key !== entry.key)
  }

  function onPickedFiles(files: File[]) {
    for (const file of files) {
      if (
        textExtension(file.name) &&
        (boundary.routeTextToCaseFiles?.() ?? true)
      ) {
        // Set the draft only once the file text is read, so the materials panel never
        // sees — and consumes — a draft whose content is still empty.
        const filename = file.name.replace(/\.(txt|md)$/i, '')
        boundary.openMaterialsTab?.()
        void file.text().then((content) => {
          textDraft.value = { filename, content }
        })
      } else {
        const entry = createUploadEntry(file)
        uploads.value = [...uploads.value, entry]
        void startUpload(entry)
      }
    }
  }

  return { uploads, textDraft, startUpload, retryUpload, dismissUpload, onPickedFiles }
}
