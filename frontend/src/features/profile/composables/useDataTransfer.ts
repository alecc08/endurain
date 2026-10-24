import { watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'

import type { ProfileImportStatus } from '@/features/profile/types'

import { queryKeys } from '@/services/queryKeys'
import { useAuthStore } from '@/features/auth/stores/auth'
import { isTerminalProfileImport } from '@/features/profile/types'
import {
  exportProfileData,
  fetchProfileImport,
  importProfileData,
} from '@/features/profile/services/dataTransfer'

/**
 * Export mutation. Resolves with the export archive; the caller is responsible
 * for saving it (e.g. via `downloadBlob`). Modelled as a mutation purely for
 * the in-flight / error state — it changes no server state.
 *
 * @returns The TanStack Query mutation that produces the export blob.
 */
export function useExportProfileMutation() {
  return useMutation<Blob, Error, void>({
    mutationFn: () => exportProfileData(),
  })
}

const IMPORT_POLL_MS = 3000

/**
 * Refreshes every domain an import can change: profile, activities, gear,
 * notifications and the current-user shell. The import's own state is left alone,
 * so refreshing the profile cannot restart the polling that triggered it.
 *
 * @param client - The active query client.
 */
function invalidateImportedData(client: ReturnType<typeof useQueryClient>): void {
  void client.invalidateQueries({ queryKey: queryKeys.profile.detail() })
  void client.invalidateQueries({ queryKey: queryKeys.profile.defaultGear() })
  void client.invalidateQueries({ queryKey: queryKeys.gears.all() })
  void client.invalidateQueries({ queryKey: queryKeys.activities.all() })
  void client.invalidateQueries({ queryKey: queryKeys.notifications.all() })
  void client.invalidateQueries({ queryKey: queryKeys.currentUser() })
}

/**
 * Import mutation. It only queues the import; the outcome comes from
 * {@link useProfileImportQuery}, which this seeds with the queued state so
 * polling starts straight away.
 *
 * @returns The TanStack Query mutation for importing a profile archive.
 */
export function useImportProfileMutation() {
  const client = useQueryClient()

  return useMutation<ProfileImportStatus, Error, File>({
    mutationFn: (file) => importProfileData(file),
    onSuccess: (status) => client.setQueryData(queryKeys.profile.import(), status),
  })
}

/**
 * Follows the user's profile import until it reaches a terminal state. It also
 * picks up an import that was started earlier (another tab, a page reload).
 * Once the import finishes, the data it changed is refetched.
 *
 * @returns The query; `data` is the import's current state, or `null` when none is recorded.
 */
export function useProfileImportQuery() {
  const client = useQueryClient()
  const { isAuthenticated } = storeToRefs(useAuthStore())

  const query = useQuery<ProfileImportStatus | null, Error>({
    queryKey: queryKeys.profile.import(),
    queryFn: ({ signal }) => fetchProfileImport(signal),
    enabled: isAuthenticated,
    refetchInterval: (state) => {
      const status = state.state.data
      return status && !isTerminalProfileImport(status) ? IMPORT_POLL_MS : false
    },
  })

  // Refetch what the import changed once, when it goes from running to finished.
  watch(
    () => query.data.value,
    (next, previous) => {
      if (previous && !isTerminalProfileImport(previous) && next && isTerminalProfileImport(next)) {
        invalidateImportedData(client)
      }
    },
  )

  return query
}
