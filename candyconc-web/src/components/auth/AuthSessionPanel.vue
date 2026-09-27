<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { LogIn, LogOut, RefreshCw, ShieldAlert, ShieldCheck, UserCircle } from 'lucide-vue-next'
import Modal from '@/components/ui/Modal.vue'
import { useSessionStore } from '@/stores/session'
import { useUiStore } from '@/stores/ui'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const sessionStore = useSessionStore()
const uiStore = useUiStore()

const username = ref('')
const password = ref('')

const isBusy = computed(() =>
  sessionStore.status === 'loading' ||
  sessionStore.loginStatus === 'loading' ||
  sessionStore.logoutStatus === 'loading'
)
const canSubmitLogin = computed(() => Boolean(username.value.trim() && password.value && !isBusy.value))
const isHealthySession = computed(() => sessionStore.isAuthenticated || sessionStore.isLocalDevAllRoles)
const triggerTone = computed(() => {
  if (sessionStore.needsLogin || sessionStore.hasInvalidToken || sessionStore.status === 'error') return 'warning'
  if (isHealthySession.value) return 'ok'
  return 'neutral'
})
const sessionModeNote = computed(() => {
  const session = sessionStore.session
  if (!session) return t('layout.auth.notLoaded')
  if (session.release_mode && !session.authenticated) return t('layout.auth.releaseNeedsLogin')
  if (session.authenticated) return t('layout.auth.signedIn')
  if (session.can_access_all_roles) return t('layout.auth.localDev')
  return t('layout.auth.signedOut')
})

onMounted(() => {
  void sessionStore.load()
})

async function submitLogin() {
  if (!canSubmitLogin.value) return
  const nextSession = await sessionStore.login(username.value.trim(), password.value)
  password.value = ''
  if (nextSession?.authenticated) {
    uiStore.closeAuth()
  }
}

async function logout() {
  await sessionStore.logout()
  password.value = ''
}

async function refreshSession() {
  await sessionStore.load(true)
}
</script>

<template>
  <button
    type="button"
    class="session-trigger"
    :class="`session-trigger--${triggerTone}`"
    :title="sessionStore.statusLabel"
    @click="uiStore.openAuth()"
  >
    <ShieldAlert v-if="triggerTone === 'warning'" class="w-5 h-5" />
    <ShieldCheck v-else-if="triggerTone === 'ok'" class="w-5 h-5" />
    <UserCircle v-else class="w-5 h-5" />
    <span class="sr-only">{{ sessionStore.statusLabel }}</span>
  </button>

  <Modal
    v-model="uiStore.authOpen"
    :title="t('layout.auth.title')"
    :description="t('layout.auth.description')"
    size="md"
  >
    <section class="session-card" :class="`session-card--${triggerTone}`">
      <div class="session-card-heading">
        <div>
          <strong>{{ sessionStore.statusLabel }}</strong>
          <p>{{ sessionModeNote }}</p>
        </div>
        <span>{{ sessionStore.username || t('layout.auth.anonymous') }}</span>
      </div>
    </section>

    <p v-if="sessionStore.hasInvalidToken" class="warning-text">
      {{ t('layout.auth.invalidToken') }}
    </p>
    <p v-if="sessionStore.error" class="error-text">{{ sessionStore.error }}</p>
    <p v-if="sessionStore.loginError" class="error-text">{{ sessionStore.loginError }}</p>

    <form v-if="sessionStore.needsLogin" class="login-form" @submit.prevent="submitLogin">
      <label class="field">
        <span>{{ t('layout.auth.username') }}</span>
        <input v-model="username" type="text" autocomplete="username" :disabled="isBusy" />
      </label>
      <label class="field">
        <span>{{ t('layout.auth.password') }}</span>
        <input v-model="password" type="password" autocomplete="current-password" :disabled="isBusy" />
      </label>
      <button type="submit" class="btn-primary" :disabled="!canSubmitLogin">
        <LogIn class="w-4 h-4" />
        {{ sessionStore.loginStatus === 'loading' ? t('layout.auth.signingIn') : t('layout.auth.signIn') }}
      </button>
    </form>

    <template #footer>
      <button type="button" class="btn-secondary" :disabled="isBusy" @click="refreshSession">
        <RefreshCw class="w-4 h-4" />
        {{ t('layout.auth.check') }}
      </button>
      <button
        v-if="sessionStore.canLogout"
        type="button"
        class="btn-secondary danger-action"
        :disabled="isBusy"
        @click="logout"
      >
        <LogOut class="w-4 h-4" />
        {{ t('layout.auth.signOut') }}
      </button>
    </template>
  </Modal>
</template>

<style scoped>
@reference "../../style.css";

.session-trigger { @apply p-2 rounded-lg text-neutral-600 transition-colors duration-150 hover:bg-neutral-100 hover:text-neutral-900 dark:text-neutral-400 dark:hover:bg-neutral-800 dark:hover:text-neutral-100; }
.session-trigger--ok { @apply text-success-700 dark:text-success-300; }
.session-trigger--warning { @apply text-warning-700 dark:text-warning-300; }
.session-card { @apply rounded-xl border border-neutral-200 bg-neutral-50 p-4 dark:border-neutral-700 dark:bg-neutral-800/50; }
.session-card--ok { @apply border-success-200 bg-success-50 dark:border-success-900/40 dark:bg-success-900/20; }
.session-card--warning { @apply border-warning-200 bg-warning-50 dark:border-warning-900/40 dark:bg-warning-900/20; }
.session-card-heading { @apply flex items-start justify-between gap-3; }
.session-card-heading strong { @apply text-sm font-semibold text-neutral-900 dark:text-neutral-100; }
.session-card-heading p { @apply mt-1 text-xs leading-relaxed text-neutral-600 dark:text-neutral-300; }
.session-card-heading span { @apply rounded-full bg-white px-2 py-0.5 text-xs font-medium text-neutral-600 dark:bg-neutral-900 dark:text-neutral-300; }
.login-form { @apply mt-4 space-y-3; }
.field { @apply flex flex-col gap-1.5 text-sm font-medium text-neutral-700 dark:text-neutral-200; }
.field input { @apply rounded-lg border border-neutral-200 bg-white px-3 py-2 text-neutral-900 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-100; }
.btn-primary { @apply inline-flex items-center justify-center gap-2 rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 disabled:cursor-not-allowed disabled:opacity-50; }
.btn-secondary { @apply inline-flex items-center gap-2 rounded-lg border border-neutral-200 px-3 py-2 text-sm text-neutral-700 hover:bg-white disabled:opacity-50 dark:border-neutral-700 dark:text-neutral-200 dark:hover:bg-neutral-800; }
.danger-action { @apply border-error-200 text-error-700 hover:bg-error-50 dark:border-error-900/60 dark:text-error-300 dark:hover:bg-error-900/20; }
.warning-text { @apply mt-3 rounded-lg border border-warning-200 bg-warning-50 px-3 py-2 text-xs text-warning-800 dark:border-warning-900/40 dark:bg-warning-900/20 dark:text-warning-200; }
.error-text { @apply mt-3 rounded-lg border border-error-200 bg-error-50 px-3 py-2 text-xs text-error-700 dark:border-error-900/40 dark:bg-error-900/20 dark:text-error-200; }
</style>
