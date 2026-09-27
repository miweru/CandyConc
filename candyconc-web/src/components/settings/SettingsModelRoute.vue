<script setup lang="ts">
/**
 * SettingsModelRoute - welchen Weg der Copilot zum Modell nimmt.
 *
 * Lokal ist die Voreinstellung. Der zweite Weg existiert, weil ein Ausfall des
 * lokalen Modellservers sonst den ganzen Copilot stilllegt.
 *
 * Der Schluessel wird nur gesendet, nie geladen. Das Backend gibt ihn nicht
 * zurueck und schreibt ihn nicht auf die Platte.
 */
import { computed, onMounted, ref } from 'vue'
import { getModelRoute, setModelRoute, type ModelRoute } from '@/api/client'
import { MODEL_ROUTE_OPERATIONS } from '@/stores/settings'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useUiStore } from '@/stores/ui'
import { useCopilotStatus } from '@/composables/useCopilotStatus'
import { AlertTriangle, HardDrive, Cloud, Loader2 } from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const productCapabilities = useProductCapabilitiesStore()
const uiStore = useUiStore()

const stand = ref<ModelRoute | null>(null)
const laedt = ref(false)
const speichert = ref(false)
const fehler = ref<string | null>(null)

const gewaehltesProfil = ref<string>('lokal')
const endpoint = ref('')
const modell = ref('')
const schluessel = ref('')

const schreibZugriff = computed(() =>
  productCapabilities.productOperationAvailability(MODEL_ROUTE_OPERATIONS.update),
)
const darfUmstellen = computed(() => schreibZugriff.value.enabled)

const profile = computed(() => stand.value?.profile ?? [])
const aktivesProfil = computed(() => profile.value.find((p) => p.id === gewaehltesProfil.value))
const brauchtSchluessel = computed(() => aktivesProfil.value?.schluessel_noetig === true)
const istEigenerEndpunkt = computed(() => gewaehltesProfil.value === 'eigen')

const schluesselFehlt = computed(
  () => brauchtSchluessel.value && !schluessel.value && stand.value?.schluessel_gesetzt !== true,
)

function symbolFuer(profilId: string) {
  return profilId === 'lokal' ? HardDrive : Cloud
}

function uebernehmen(neu: ModelRoute) {
  stand.value = neu
  gewaehltesProfil.value = neu.aktiv
  endpoint.value = neu.endpoint ?? ''
  modell.value = neu.modell ?? ''
  schluessel.value = ''
}

async function laden() {
  laedt.value = true
  fehler.value = null
  try {
    uebernehmen(await getModelRoute())
  } catch (e) {
    fehler.value = e instanceof Error ? e.message : t('settings.modelRoute.loadFailed')
  } finally {
    laedt.value = false
  }
}

function profilWaehlen(profilId: string) {
  gewaehltesProfil.value = profilId
  const gewaehlt = profile.value.find((p) => p.id === profilId)
  if (gewaehlt) endpoint.value = gewaehlt.endpoint
}

async function speichern() {
  if (!darfUmstellen.value) {
    uiStore.showToast(schreibZugriff.value.disabledReason ?? t('settings.general.notEnabled'), 'warning')
    return
  }
  speichert.value = true
  fehler.value = null
  try {
    const neu = await setModelRoute({
      endpoint: endpoint.value,
      modell: modell.value,
      schluessel: schluessel.value || undefined,
    })
    uebernehmen(neu)
    void useCopilotStatus().refresh()
    uiStore.showToast(t('settings.modelRoute.switched'), 'success')
  } catch (e) {
    fehler.value = e instanceof Error ? e.message : t('settings.modelRoute.switchFailed')
  } finally {
    speichert.value = false
  }
}

onMounted(laden)
</script>

<template>
  <div class="settings-section">
    <h3 class="section-title">{{ t('settings.modelRoute.title') }}</h3>

    <p class="setting-description mb-4">
      {{ t('settings.modelRoute.intro') }}
    </p>

    <div v-if="laedt" class="ladezeile">
      <Loader2 class="w-4 h-4 animate-spin" />
      <span>{{ t('settings.modelRoute.loading') }}</span>
    </div>

    <template v-else-if="stand">
      <div class="profil-knoepfe">
        <button
          v-for="p in profile"
          :key="p.id"
          type="button"
          class="profil-btn"
          :class="{ active: gewaehltesProfil === p.id }"
          :disabled="!darfUmstellen"
          @click="profilWaehlen(p.id)"
        >
          <component :is="symbolFuer(p.id)" class="w-4 h-4" />
          <span class="profil-name">{{ p.name }}</span>
          <span class="profil-hinweis">{{ p.hinweis }}</span>
        </button>
      </div>

      <p v-if="istEigenerEndpunkt" class="setting-description mt-2">
        {{ t('settings.modelRoute.customEndpoint') }}
      </p>

      <div class="setting-row mt-4">
        <div class="setting-info">
          <label for="modellweg-endpoint">{{ t('settings.modelRoute.endpoint') }}</label>
          <p class="setting-description">{{ t('settings.modelRoute.endpointDescription') }}</p>
        </div>
        <input
          id="modellweg-endpoint"
          v-model="endpoint"
          type="url"
          class="setting-input"
          spellcheck="false"
          :disabled="!darfUmstellen"
        />
      </div>

      <div class="setting-row">
        <div class="setting-info">
          <label for="modellweg-modell">{{ t('settings.modelRoute.model') }}</label>
          <p class="setting-description">{{ t('settings.modelRoute.modelDescription') }}</p>
        </div>
        <input
          id="modellweg-modell"
          v-model="modell"
          type="text"
          class="setting-input"
          spellcheck="false"
          :disabled="!darfUmstellen"
        />
      </div>

      <div v-if="brauchtSchluessel" class="setting-row">
        <div class="setting-info">
          <label for="modellweg-schluessel">{{ t('settings.modelRoute.key') }}</label>
          <p class="setting-description">
            <template v-if="stand.schluessel_gesetzt">
              {{ t('settings.modelRoute.keySet', { suffix: stand.schluessel_endet_auf ?? '' }) }}
            </template>
            <template v-else>{{ t('settings.modelRoute.keyMissing') }}</template>
          </p>
        </div>
        <input
          id="modellweg-schluessel"
          v-model="schluessel"
          type="password"
          class="setting-input"
          autocomplete="off"
          spellcheck="false"
          :disabled="!darfUmstellen"
        />
      </div>

      <div v-if="brauchtSchluessel" class="warnkasten">
        <AlertTriangle class="w-4 h-4 shrink-0" />
        <div>
          <p>
            {{ t('settings.modelRoute.remoteWarning') }}
          </p>
          <p class="mt-1">
            {{ t('settings.modelRoute.keyScope') }}
          </p>
        </div>
      </div>

      <p v-if="fehler" class="fehlerzeile">{{ fehler }}</p>

      <div class="fusszeile">
        <span class="setting-description">
          {{ t('settings.modelRoute.active', { model: stand.modell || t('settings.modelRoute.noModel'), endpoint: stand.endpoint || t('settings.modelRoute.noEndpoint') }) }}
        </span>
        <button
          type="button"
          class="speichern-btn"
          :disabled="!darfUmstellen || speichert || schluesselFehlt"
          :title="
            !darfUmstellen
              ? schreibZugriff.disabledReason ?? t('settings.general.notEnabled')
              : schluesselFehlt
                ? t('settings.modelRoute.keyRequired')
                : t('settings.modelRoute.switchTitle')
          "
          @click="speichern"
        >
          <Loader2 v-if="speichert" class="w-4 h-4 animate-spin" />
          <span>{{ t('settings.modelRoute.switch') }}</span>
        </button>
      </div>
    </template>

    <p v-else class="fehlerzeile">{{ fehler ?? t('settings.modelRoute.unavailable') }}</p>
  </div>
</template>

<style scoped>
.ladezeile,
.fehlerzeile {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.875rem;
  color: var(--color-text-muted, #6b7280);
}

.fehlerzeile {
  color: var(--color-danger, #b91c1c);
  margin-top: 0.75rem;
}

.profil-knoepfe {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr));
  gap: 0.75rem;
}

.profil-btn {
  display: grid;
  grid-template-columns: auto 1fr;
  grid-template-areas: 'icon name' 'icon hint';
  gap: 0.125rem 0.5rem;
  align-items: start;
  padding: 0.75rem;
  text-align: left;
  border: 1px solid var(--color-border, #d1d5db);
  border-radius: 0.5rem;
  background: transparent;
  cursor: pointer;
}

.profil-btn:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.profil-btn.active {
  border-color: var(--color-primary, #2563eb);
  background: var(--color-primary-soft, rgba(37, 99, 235, 0.08));
}

.profil-btn > svg {
  grid-area: icon;
  margin-top: 0.15rem;
}

.profil-name {
  grid-area: name;
  font-weight: 600;
  font-size: 0.875rem;
}

.profil-hinweis {
  grid-area: hint;
  font-size: 0.75rem;
  color: var(--color-text-muted, #6b7280);
}

.setting-input {
  min-width: 18rem;
  padding: 0.375rem 0.5rem;
  border: 1px solid var(--color-border, #d1d5db);
  border-radius: 0.375rem;
  background: transparent;
  font-size: 0.875rem;
}

.warnkasten {
  display: flex;
  gap: 0.5rem;
  margin-top: 0.75rem;
  padding: 0.75rem;
  border: 1px solid var(--color-warning-border, #fcd34d);
  border-radius: 0.5rem;
  background: var(--color-warning-soft, rgba(252, 211, 77, 0.12));
  font-size: 0.8125rem;
}

.fusszeile {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-top: 1rem;
}

.speichern-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.4rem 0.9rem;
  border-radius: 0.375rem;
  border: 1px solid var(--color-primary, #2563eb);
  background: var(--color-primary, #2563eb);
  color: white;
  font-size: 0.875rem;
  cursor: pointer;
}

.speichern-btn:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}
</style>
