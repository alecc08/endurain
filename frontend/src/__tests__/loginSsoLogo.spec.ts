import { describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { mount } from '@vue/test-utils'

import i18n from '@/i18n'
import LoginView from '@/features/auth/views/LoginView.vue'

const providers = ref([
  { id: 1, name: 'Tinyauth', slug: 'tinyauth', icon: 'https://cdn.example.com/logo.svg' },
  { id: 2, name: 'Keycloak', slug: 'keycloak', icon: 'keycloak' },
  { id: 3, name: 'Plain', slug: 'plain', icon: null },
])

vi.mock('@/features/config/composables/usePublicServerSettings', () => ({
  usePublicServerSettings: () => ({
    serverSettings: ref({ local_login_enabled: true, signup_enabled: false, sso_enabled: true }),
    ssoProviders: providers,
    isSettingsLoading: ref(false),
    isSsoLoading: ref(false),
    loginImageUrl: ref(''),
    load: vi.fn<() => Promise<void>>(() => Promise.resolve()),
  }),
}))

vi.mock('@/features/config/composables/useAppConfig', () => ({
  useAppConfig: () => ({ config: ref({ branding: { appName: 'Endurain' } }) }),
}))

vi.mock('@/features/auth/composables/useSsoLogin', () => ({
  useSsoLogin: () => ({
    startSsoLogin: vi.fn<() => Promise<void>>(),
    processSsoCallback: vi.fn<() => Promise<{ status: string }>>(() =>
      Promise.resolve({ status: 'none' }),
    ),
    completeSsoMfa: vi.fn<() => Promise<void>>(),
    maybeAutoRedirect: vi.fn<() => void>(),
  }),
}))

vi.mock('@/features/auth/composables/useLoginRouteMessages', () => ({
  useLoginRouteMessages: () => ({
    resolveInitialAlert: () => null,
    shouldForceLocalLogin: () => false,
  }),
}))

vi.mock('@/composables/useSafeRedirect', () => ({
  useSafeRedirect: () => ({ navigateAfterLogin: vi.fn<() => Promise<void>>() }),
}))

vi.mock('@/features/auth/stores/auth', () => ({ useAuthStore: () => ({}) }))

vi.mock('vue-router', () => ({
  useRoute: () => ({ query: {}, fullPath: '/login' }),
  useRouter: () => ({ replace: vi.fn<() => void>() }),
  RouterLink: { template: '<a><slot /></a>' },
}))

describe('LoginView SSO buttons', () => {
  it('shows the custom icon URL, a bundled logo for a built-in key and none otherwise', () => {
    const wrapper = mount(LoginView, {
      global: {
        plugins: [i18n],
        stubs: { AuthScreenLayout: { template: '<div><slot /></div>' } },
      },
    })

    const sources = wrapper
      .findAll('button[type="button"]')
      .filter((button) => button.attributes('aria-label')?.includes('Tinyauth') ?? false)
      .flatMap((button) => button.findAll('img').map((img) => img.attributes('src')))
    expect(sources).toEqual(['https://cdn.example.com/logo.svg'])

    const keycloak = wrapper
      .findAll('button')
      .find((button) => button.attributes('aria-label')?.includes('Keycloak'))
    expect(keycloak?.find('img').exists()).toBe(true)

    const plain = wrapper
      .findAll('button')
      .find((button) => button.attributes('aria-label')?.includes('Plain'))
    expect(plain?.find('img').exists()).toBe(false)
  })
})
