import type { ProfileImportStatus } from '@/features/profile/types'

import { apiFetch, HttpError } from '@/services/http'

/**
 * Exports all of the authenticated user's profile data as a ZIP archive. The
 * timeout is disabled because a full export can take a while to stream.
 *
 * @param signal - Optional abort signal for cancellation.
 * @returns The export archive as a {@link Blob}.
 * @throws {HttpError} When the export fails.
 */
export function exportProfileData(signal?: AbortSignal): Promise<Blob> {
  return apiFetch<Blob>('/profile/export', { responseType: 'blob', timeoutMs: 0, signal })
}

/**
 * Queues a profile import from a ZIP archive. The file is sent as multipart form
 * data under the `file` field; the backend validates and stages it and a worker
 * imports it, so the caller's filename never builds a path and the request
 * returns at once. Follow the outcome with {@link fetchProfileImport}.
 *
 * @param file - The ZIP archive to import.
 * @returns The queued import's state.
 * @throws {HttpError} When the archive is refused (e.g. invalid file, or `409`
 *   while another import is still running).
 */
export async function importProfileData(file: File): Promise<ProfileImportStatus> {
  const formData = new FormData()
  formData.append('file', file, file.name)
  return apiFetch<ProfileImportStatus>('/profile/import', {
    method: 'POST',
    body: formData,
    timeoutMs: 0,
  })
}

/**
 * Reads where the user's profile import is.
 *
 * @param signal - Optional abort signal for cancellation.
 * @returns The import's state, or `null` when none is recorded (or it expired).
 * @throws {HttpError} When the request fails for a reason other than `404`.
 */
export async function fetchProfileImport(
  signal?: AbortSignal,
): Promise<ProfileImportStatus | null> {
  try {
    return await apiFetch<ProfileImportStatus>('/profile/import', { signal })
  } catch (error) {
    if (error instanceof HttpError && error.status === 404) {
      return null
    }
    throw error
  }
}
