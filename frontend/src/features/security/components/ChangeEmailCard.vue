<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Mail } from '@lucide/vue'

import type { StepUpInput } from '@/features/security/types'

import StepUpDialog from '@/features/security/components/StepUpDialog.vue'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { useToasts } from '@/composables/useToasts'
import { HttpError } from '@/services/http'
import { useChangeEmailMutation } from '@/features/security/composables/useSecurity'
import { isValidEmail } from '@/utils/validation'

const props = defineProps<{
  /** The account's current email address. */
  email: string
  /** Whether the account has a local password (gates the step-up password field). */
  hasLocalPassword: boolean
  /** Whether MFA is enabled (gates the step-up MFA-code field). */
  mfaEnabled: boolean
}>()

const { t } = useI18n()
const toasts = useToasts()
const changeMutation = useChangeEmailMutation()

const isDialogOpen = ref(false)
const newEmail = ref('')
const revokeOtherSessions = ref(false)

const invalidMessage = t('settings.security.email.invalid')
const trimmedEmail = computed(() => newEmail.value.trim())
const isEmailValid = computed(() => isValidEmail(trimmedEmail.value))
const showInvalid = computed(() => trimmedEmail.value.length > 0 && !isEmailValid.value)

// Start from an empty field each time the dialog opens.
watch(isDialogOpen, (isOpen) => {
  if (isOpen) {
    newEmail.value = ''
    revokeOtherSessions.value = false
  }
})

/** Changes the email after step-up, then closes and tells the user to verify the new address. */
function onConfirm(stepUp: StepUpInput): void {
  changeMutation.mutate(
    { email: trimmedEmail.value, stepUp, revokeOtherSessions: revokeOtherSessions.value },
    {
      onSuccess: () => {
        isDialogOpen.value = false
        toasts.success(t('settings.security.email.success'))
      },
      onError: (error) => {
        if (error instanceof HttpError && error.status === 409) {
          toasts.error(t('settings.security.email.conflict'))
        } else if (error instanceof HttpError && error.status === 401) {
          toasts.error(t('settings.security.linked.invalidCredentials'))
        } else {
          toasts.error(t('settings.security.email.error'))
        }
      },
    },
  )
}
</script>

<template>
  <Card class="flex flex-col gap-3">
    <div class="flex flex-col gap-1">
      <h2 class="text-card-heading">{{ t('settings.security.email.title') }}</h2>
      <p class="text-hint">{{ t('settings.security.email.subtitle') }}</p>
    </div>

    <div class="flex flex-wrap items-center justify-between gap-3">
      <div class="min-w-0">
        <p class="text-hint">{{ t('settings.security.email.current') }}</p>
        <p class="truncate font-medium text-foreground">{{ props.email }}</p>
      </div>
      <Button variant="outline" @click="isDialogOpen = true">
        <Mail class="size-4" aria-hidden="true" />
        <span>{{ t('settings.security.email.action') }}</span>
      </Button>
    </div>

    <StepUpDialog
      v-model:open="isDialogOpen"
      :title="t('settings.security.email.dialogTitle')"
      :description="t('settings.security.email.dialogDescription')"
      :confirm-label="t('settings.security.email.confirm')"
      :require-password="props.hasLocalPassword"
      :require-mfa="props.mfaEnabled"
      :extra-valid="isEmailValid"
      :pending="changeMutation.isPending.value"
      @confirm="onConfirm"
    >
      <div class="flex flex-col gap-1.5">
        <Label for="change-email-new">{{ t('settings.security.email.new') }}</Label>
        <Input
          id="change-email-new"
          v-model="newEmail"
          type="email"
          maxlength="250"
          autocomplete="email"
          :aria-invalid="showInvalid"
          :disabled="changeMutation.isPending.value"
          class="w-full"
        />
        <p v-if="showInvalid" class="text-hint text-destructive">{{ invalidMessage }}</p>
      </div>
      <Switch v-model="revokeOtherSessions" :disabled="changeMutation.isPending.value">
        {{ t('settings.security.password.revokeOthers') }}
      </Switch>
    </StepUpDialog>
  </Card>
</template>
