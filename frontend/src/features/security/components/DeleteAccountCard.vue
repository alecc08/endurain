<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { Trash2 } from '@lucide/vue'

import type { StepUpInput } from '@/features/security/types'

import StepUpDialog from '@/features/security/components/StepUpDialog.vue'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { useToasts } from '@/composables/useToasts'
import { HttpError } from '@/services/http'
import { useDeleteAccountMutation } from '@/features/security/composables/useSecurity'

const props = defineProps<{
  /** The account's username; the user types it to confirm the deletion. */
  username: string
  /** Whether the account has a local password (gates the step-up password field). */
  hasLocalPassword: boolean
  /** Whether MFA is enabled (gates the step-up MFA-code field). */
  mfaEnabled: boolean
}>()

const { t } = useI18n()
const toasts = useToasts()
const router = useRouter()
const deleteMutation = useDeleteAccountMutation()

const isDialogOpen = ref(false)

/** Deletes the account after step-up, then leaves for the farewell page. */
function onConfirm(input: StepUpInput): void {
  deleteMutation.mutate(input, {
    onSuccess: () => {
      isDialogOpen.value = false
      void router.replace({ name: 'account-deleted' })
    },
    onError: (error) => {
      if (error instanceof HttpError && error.status === 409) {
        toasts.error(t('settings.security.deleteAccount.onlyAdminError'))
      } else if (error instanceof HttpError && error.status === 401) {
        toasts.error(t('settings.security.linked.invalidCredentials'))
      } else {
        toasts.error(t('settings.security.deleteAccount.error'))
      }
    },
  })
}
</script>

<template>
  <Card class="flex flex-col gap-3">
    <div class="flex flex-col gap-1">
      <h2 class="text-card-heading">{{ t('settings.security.deleteAccount.title') }}</h2>
      <p class="text-hint">{{ t('settings.security.deleteAccount.subtitle') }}</p>
    </div>

    <div>
      <Button variant="destructive" @click="isDialogOpen = true">
        <Trash2 class="size-4" aria-hidden="true" />
        <span>{{ t('settings.security.deleteAccount.action') }}</span>
      </Button>
    </div>

    <StepUpDialog
      v-model:open="isDialogOpen"
      :title="t('settings.security.deleteAccount.dialogTitle')"
      :description="t('settings.security.deleteAccount.dialogDescription')"
      :confirm-label="t('settings.security.deleteAccount.confirm')"
      :require-password="props.hasLocalPassword"
      :require-mfa="props.mfaEnabled"
      :confirm-phrase="props.username"
      destructive
      :pending="deleteMutation.isPending.value"
      @confirm="onConfirm"
    />
  </Card>
</template>
