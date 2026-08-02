import assert from 'node:assert/strict'
import test from 'node:test'

import { nextTick, ref } from 'vue'
import { useMaterialUploads } from '../../src/materialUploads.ts'

async function flush() {
  await new Promise((resolve) => setTimeout(resolve, 0))
}

function setup(options: {
  meetingId?: () => string | undefined
  uploadAttachment?: (meetingId: string, file: File) => Promise<unknown>
  openMeeting?: (meetingId: string) => Promise<unknown>
  openMaterialsTab?: () => void
} = {}) {
  const meetingId = ref<string | undefined>('meeting-a')
  const uploaded: Array<{ meetingId: string; file: File }> = []
  const refreshed: string[] = []
  const composable = useMaterialUploads({
    meetingId: () => meetingId.value,
    uploadAttachment: async (id, file) => {
      uploaded.push({ meetingId: id, file })
      await options.uploadAttachment?.(id, file)
    },
    openMeeting: async (id) => {
      refreshed.push(id)
      await options.openMeeting?.(id)
    },
    openMaterialsTab: options.openMaterialsTab,
  })
  return {
    ...composable,
    setMeetingId: (next: string | undefined) => { meetingId.value = next },
    uploaded,
    refreshed,
  }
}

test('onPickedFiles routes a binary file to startUpload and refreshes the meeting on success', async () => {
  const { uploads, uploaded, refreshed, onPickedFiles } = setup()
  onPickedFiles([new File(['binary-bytes'], 'photo.png', { type: 'image/png' })])
  await flush()

  assert.equal(uploaded.length, 1)
  assert.equal(uploaded[0].meetingId, 'meeting-a')
  assert.equal(uploaded[0].file.name, 'photo.png')
  assert.deepEqual(refreshed, ['meeting-a'])
  assert.equal(uploads.value.length, 1)
  assert.equal(uploads.value[0].status, 'done')
  assert.equal(uploads.value[0].filename, 'photo.png')
})

test('onPickedFiles routes .txt and .md files to textDraft and opens the materials tab', async () => {
  const opened: string[] = []
  const { textDraft, onPickedFiles } = setup({ openMaterialsTab: () => opened.push('opened') })

  onPickedFiles([new File(['這是文字摘要內容'], '摘要.txt', { type: 'text/plain' })])
  await flush()
  onPickedFiles([new File(['# 大綱'], '大綱.md', { type: 'text/markdown' })])
  await flush()

  assert.deepEqual(opened, ['opened', 'opened'])
  assert.deepEqual(textDraft.value, { filename: '大綱', content: '# 大綱' })
})

test('onPickedFiles never uploads a text file through the attachment boundary', async () => {
  const { uploaded, onPickedFiles } = setup()
  onPickedFiles([new File(['文字'], 'notes.txt', { type: 'text/plain' })])
  await flush()
  assert.equal(uploaded.length, 0)
})

test('startUpload marks an entry failed when the boundary rejects', async () => {
  const { uploads, onPickedFiles } = setup({
    uploadAttachment: async () => { throw new Error('disk full') },
  })
  onPickedFiles([new File(['bytes'], 'bundle.zip')])
  await flush()

  assert.equal(uploads.value.length, 1)
  assert.equal(uploads.value[0].status, 'error')
  assert.match(uploads.value[0].error ?? '', /disk full/)
  assert.equal(uploads.value[0].retryFile?.name, 'bundle.zip')
})

test('retryUpload re-runs a failed upload through the same boundary', async () => {
  let fail = true
  let calls = 0
  const { uploads, onPickedFiles, retryUpload } = setup({
    uploadAttachment: async () => {
      calls += 1
      if (fail) throw new Error('boom')
    },
  })
  onPickedFiles([new File(['bytes'], 'retry.zip')])
  await flush()
  assert.equal(uploads.value[0].status, 'error')

  fail = false
  retryUpload(uploads.value[0])
  await flush()
  assert.equal(calls, 2)
  assert.equal(uploads.value[0].status, 'done')
  assert.equal(uploads.value[0].error, undefined)
})

test('dismissUpload removes a failed entry from the list', async () => {
  const { uploads, onPickedFiles, dismissUpload } = setup({
    uploadAttachment: async () => { throw new Error('boom') },
  })
  onPickedFiles([new File(['bytes'], 'drop.zip')])
  await flush()
  assert.equal(uploads.value.length, 1)

  dismissUpload(uploads.value[0])
  assert.equal(uploads.value.length, 0)
})

test('switching meetingId clears uploads and textDraft', async () => {
  const { uploads, textDraft, onPickedFiles, setMeetingId } = setup()
  onPickedFiles([new File(['bytes'], 'one.zip')])
  await flush()
  onPickedFiles([new File(['文字'], 'one.txt')])
  await flush()
  assert.equal(uploads.value.length, 1)
  assert.ok(textDraft.value)

  setMeetingId('meeting-b')
  await nextTick()
  assert.equal(uploads.value.length, 0)
  assert.equal(textDraft.value, null)
})

test('startUpload is a no-op when there is no meeting or no retry file', async () => {
  const { uploaded, startUpload, setMeetingId } = setup()
  setMeetingId(undefined)
  await startUpload({ key: 'x', filename: 'x.zip', status: 'uploading', retryFile: new File(['b'], 'x.zip') })
  assert.equal(uploaded.length, 0)

  await startUpload({ key: 'x', filename: 'x.zip', status: 'uploading' })
  assert.equal(uploaded.length, 0)
})
