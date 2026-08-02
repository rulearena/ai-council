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
}

function textExtension(filename: string): boolean {
  return /\.(txt|md)$/i.test(filename)
}

function caughtMessage(caught: unknown): string {
  return caught instanceof Error ? caught.message : String(caught)
}

/**
 * 附件上傳狀態機（聊天室 composer／ActionBar 快速選單共用的 composable）。
 * - 二進位檔：進入 uploads 並立即 startUpload（uploadAttachment → openMeeting 刷新）。
 * - .txt/.md：進入 textDraft（標題＝去副檔名檔名、內容＝檔案文字），並呼叫 openMaterialsTab()
 *   開啟側欄資料頁讓使用者預填確認。
 * boundary（uploadAttachment、openMeeting、openMaterialsTab）由父層注入，unit 可注入 fake 不碰網路。
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
      if (textExtension(file.name)) {
        const filename = file.name.replace(/\.(txt|md)$/i, '')
        textDraft.value = { filename, content: '' }
        void file.text().then((content) => {
          if (textDraft.value?.filename === filename) {
            textDraft.value = { filename, content }
          }
        })
        boundary.openMaterialsTab?.()
      } else {
        const entry = createUploadEntry(file)
        uploads.value = [...uploads.value, entry]
        void startUpload(entry)
      }
    }
  }

  return { uploads, textDraft, startUpload, retryUpload, dismissUpload, onPickedFiles }
}
