<script setup lang="ts">
/**
 * ReaderTab - das Korpus lesen, nicht messen.
 *
 * Bis heute konnte man in CandyConc jedes Wort zaehlen und keinen Text
 * lesen. Die Dokumentsuche verlangt einen Suchbegriff, der Volltext
 * verlangt eine Dokumentnummer, und wer nur wissen wollte, was in seinem
 * Korpus eigentlich steht, musste raten. Der Wunsch stand seit Wochen im
 * Raum und wurde mehrfach wiederholt.
 *
 * Links das Verzeichnis, rechts der Text. Mehr nicht.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { BookOpen, ChevronLeft, ChevronRight, Loader2 } from 'lucide-vue-next'
import {
  listDocuments, getDocument, getMetaValuesPage, docsetFromMeta,
  type DocumentListItem, type Document, type ReaderFields,
} from '@/api/client'
import { useCorpusCapabilitiesStore, useDocsetStore } from '@/stores'
import { isIdentityField } from '@/stores/docset'
import { documentHeading, documentRowLabel, documentSubline } from '@/lib/readerFields'
import { formatNumber } from '@/i18n/format'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const korpus = useCorpusCapabilitiesStore()
const docsetStore = useDocsetStore()

/** Achsen, ueber die sich das Korpus durchstoebern laesst. */
const achsen = ref<Record<string, string[]>>({})
const achsenFehler = ref<string | null>(null)
const gewaehltesFeld = ref<string>('')
const gewaehlterWert = ref<string>('')
const docsetId = ref<string | undefined>(undefined)
const filterLaeuft = ref(false)

/**
 * Only fields worth browsing.
 *
 * A field with 19,272 values (source text ids in a paired corpus) or with
 * exactly one is not an axis for browsing, it is noise in the menu. The limit
 * is generous so that 100 sources remain selectable.
 */
const brauchbareAchsen = computed(() =>
  Object.entries(achsen.value)
    .filter(([, werte]) => werte.length > 1 && werte.length <= 200)
    .sort(([a], [b]) => a.localeCompare(b)),
)

const werteDesFeldes = computed(() => achsen.value[gewaehltesFeld.value] ?? [])

const seite = ref(0)
const proSeite = 50
const gesamt = ref(0)
const zeilen = ref<DocumentListItem[]>([])
const ladeListe = ref(false)
const listenFehler = ref<string | null>(null)

/** Reader fields the server names in the list response, null for older servers. */
const leserFelder = ref<ReaderFields | null>(null)

const gewaehlt = ref<number | null>(null)
const text = ref<Document | null>(null)
const ladeText = ref(false)
const textFehler = ref<string | null>(null)

const aktivesKorpus = computed(() => korpus.activeCorpus || undefined)

/**
 * The active scope of the interface (subcorpus or metadata filter). The
 * reader lists only its documents, its own field filter narrows further.
 * Without it the reader would list the whole corpus.
 */
const bereichDocsetId = computed(() =>
  docsetStore.hasActiveDocset && docsetStore.activeCorpus === korpus.activeCorpus
    ? docsetStore.activeDocsetId ?? undefined
    : undefined,
)
const bereichName = computed(() => {
  if (!bereichDocsetId.value) return ''
  if (docsetStore.activeSubcorpusName) return docsetStore.activeSubcorpusName
  if (docsetStore.summaryParts.length) return docsetStore.summaryParts.join(', ')
  const herkunft = docsetStore.activeDocsetOrigin
  if (herkunft?.kind === 'search') return t('kwic.reader.scopeQuery', { query: herkunft.query })
  return t('kwic.reader.scopeActive')
})
// Nur die neueste Anfrage darf den sichtbaren Zustand verändern.
let achsenAnfrage = 0, filterAnfrage = 0, listenAnfrage = 0, textAnfrage = 0

/**
 * The TEXT comes first, not its data sheet.
 *
 * In a parliamentary corpus a document can have 25 metadata fields.
 * Expanded, they fill a screen of key-value pairs before the first sentence.
 * A reader that makes you scroll to the text is no reader.
 */
const metaOffen = ref(false)
const metaAnzahl = computed(() => Object.keys(text.value?.meta ?? {}).length)

/**
 * Heading and subline come from the fields of the corpus (lib/readerFields):
 * the title field, else the document label, then the fields whose values tell
 * documents apart. A fixed set of project fields (speaker_name, protocol_date,
 * register, model) labelled only the corpora that happened to have them.
 */
const kopfzeile = computed(() =>
  documentHeading(text.value?.meta ?? {}, text.value?.doc, leserFelder.value) || t('kwic.reader.document'),
)
const unterzeile = computed(() =>
  documentSubline(text.value?.meta ?? {}, feldWerte.value, leserFelder.value).join(' · '),
)
const letzteSeite = computed(() => Math.max(0, Math.ceil(gesamt.value / proSeite) - 1))
const vonBis = computed(() => {
  if (!gesamt.value) return ''
  const von = seite.value * proSeite + 1
  const bis = Math.min(gesamt.value, (seite.value + 1) * proSeite)
  return t('kwic.reader.range', { from: formatNumber(von), to: formatNumber(bis), total: formatNumber(gesamt.value) })
})

/**
 * Browsable fields from the metadata schema of the corpus: more than one and
 * at most 200 values, no document identifiers. The server takes field names,
 * a wildcard returns no values, and the reader would offer no field filter
 * and label every row with corpus-wide constants.
 */
const ACHSE_MAX_WERTE = 200
const achsenFelder = computed(() =>
  Object.entries(docsetStore.metaFieldValueCounts)
    .filter(([feld, anzahl]) =>
      !isIdentityField(feld) && typeof anzahl === 'number' && anzahl > 1 && anzahl <= ACHSE_MAX_WERTE)
    .map(([feld]) => feld)
    .sort(),
)

async function ladeAchsen() {
  const anfrage = ++achsenAnfrage
  achsenFehler.value = null
  const felder = achsenFelder.value
  if (!felder.length) {
    achsen.value = {}
    return
  }
  try {
    const seite = await getMetaValuesPage({ fields: felder, corpus: aktivesKorpus.value, limit: ACHSE_MAX_WERTE })
    if (anfrage !== achsenAnfrage) return
    achsen.value = seite.values
  } catch (fehler) {
    if (anfrage !== achsenAnfrage) return
    achsenFehler.value = fehler instanceof Error ? fehler.message : String(fehler)
  }
}

/** Ein Metadatenfilter wird zu einem Docset, derselben Naht wie im Kontrast. */
async function filterAnwenden() {
  const anfrage = ++filterAnfrage
  ++listenAnfrage
  ++textAnfrage
  seite.value = 0
  gewaehlt.value = null
  text.value = null
  textFehler.value = null
  ladeText.value = ladeListe.value = false
  zeilen.value = []
  gesamt.value = 0
  docsetId.value = undefined
  listenFehler.value = null
  filterLaeuft.value = true
  try {
    if (gewaehltesFeld.value && gewaehlterWert.value) {
      const ergebnis = await docsetFromMeta(
        { [gewaehltesFeld.value]: gewaehlterWert.value },
        aktivesKorpus.value,
      )
      if (anfrage !== filterAnfrage) return
      docsetId.value = ergebnis.docset_id
    }
    await ladeVerzeichnis()
  } catch (fehler) {
    if (anfrage !== filterAnfrage) return
    listenFehler.value = fehler instanceof Error ? fehler.message : String(fehler)
  } finally {
    if (anfrage === filterAnfrage) filterLaeuft.value = false
  }
}

function filterLoeschen() {
  gewaehltesFeld.value = ''
  gewaehlterWert.value = ''
  void filterAnwenden()
}

async function ladeVerzeichnis() {
  const anfrage = ++listenAnfrage
  ladeListe.value = true
  listenFehler.value = null
  try {
    const antwort = await listDocuments({
      corpus: aktivesKorpus.value,
      offset: seite.value * proSeite,
      limit: proSeite,
      docsetId: docsetId.value,
      scopeDocsetId: bereichDocsetId.value,
    })
    if (anfrage !== listenAnfrage) return
    gesamt.value = antwort.total
    zeilen.value = antwort.items
    leserFelder.value = antwort.reader_fields ?? null
    if (gewaehlt.value === null && antwort.items.length) {
      void oeffne(antwort.items[0]!.doc_id)
    }
  } catch (fehler) {
    if (anfrage !== listenAnfrage) return
    listenFehler.value = fehler instanceof Error ? fehler.message : String(fehler)
  } finally {
    if (anfrage === listenAnfrage) ladeListe.value = false
  }
}

async function oeffne(docId: number) {
  const anfrage = ++textAnfrage
  gewaehlt.value = docId
  text.value = null
  ladeText.value = true
  textFehler.value = null
  try {
    const antwort = await getDocument(String(docId), aktivesKorpus.value)
    if (anfrage !== textAnfrage) return
    text.value = antwort
  } catch (fehler) {
    if (anfrage !== textAnfrage) return
    textFehler.value = fehler instanceof Error ? fehler.message : String(fehler)
  } finally {
    if (anfrage === textAnfrage) ladeText.value = false
  }
}

function blaettere(richtung: -1 | 1) {
  const ziel = seite.value + richtung
  if (ziel < 0 || ziel > letzteSeite.value) return
  seite.value = ziel
  void ladeVerzeichnis()
}

/**
 * Value counts per field: from the metadata schema, completed by the loaded
 * browsing values. A field with one value tells no documents apart and stays
 * in the metadata block of the document.
 */
const feldWerte = computed<Record<string, number | null>>(() => {
  const anzahlen: Record<string, number | null> = { ...docsetStore.metaFieldValueCounts }
  for (const [feld, werte] of Object.entries(achsen.value)) {
    if (typeof anzahlen[feld] !== 'number') anzahlen[feld] = werte.length
  }
  return anzahlen
})

/** The label of a list row: document label and the distinguishing fields the row carries. */
function kennzeichnung(zeile: DocumentListItem): string {
  return documentRowLabel(zeile.doc, zeile.meta, feldWerte.value, leserFelder.value)
}

onMounted(() => {
  void ladeVerzeichnis()
  void ladeAchsen()
})
watch(aktivesKorpus, () => {
  achsen.value = {}
  leserFelder.value = null
  filterLoeschen()
})
// The schema of the corpus arrives after mounting and after a corpus change.
watch(() => achsenFelder.value.join('|'), () => void ladeAchsen())
watch(bereichDocsetId, (neu, alt) => {
  if (neu === alt) return
  // Keep the reader's own field filter, start again at the first page.
  ++listenAnfrage
  ++textAnfrage
  seite.value = 0
  gewaehlt.value = null
  text.value = null
  zeilen.value = []
  gesamt.value = 0
  void ladeVerzeichnis()
})
onBeforeUnmount(() => {
  ++achsenAnfrage
  ++filterAnfrage
  ++listenAnfrage
  ++textAnfrage
})
</script>

<template>
  <div class="reader-tab">
    <aside class="reader-liste">
      <header class="liste-kopf">
        <BookOpen class="w-4 h-4" />
        <span class="font-medium">{{ t('kwic.reader.documents') }}</span>
        <span v-if="vonBis" class="text-xs text-neutral-500 ml-auto">{{ vonBis }}</span>
      </header>
      <p v-if="bereichName" class="liste-bereich" data-testid="reader-scope">
        {{ t('kwic.reader.scope', { scope: bereichName }) }}
      </p>

      <div v-if="brauchbareAchsen.length" class="liste-filter">
        <select
          v-model="gewaehltesFeld"
          class="filter-feld"
          :aria-label="t('kwic.reader.metadataField')"
          @change="gewaehlterWert = ''; filterAnwenden()"
        >
          <option value="">{{ bereichDocsetId ? t('kwic.reader.wholeScope') : t('kwic.reader.wholeCorpus') }}</option>
          <option v-for="[feld, werte] in brauchbareAchsen" :key="feld" :value="feld">
            {{ feld }} ({{ werte.length }})
          </option>
        </select>
        <select
          v-if="gewaehltesFeld"
          v-model="gewaehlterWert"
          class="filter-wert"
          :aria-label="t('kwic.reader.value')"
          @change="filterAnwenden"
        >
          <option value="">{{ t('kwic.reader.chooseValue') }}</option>
          <option v-for="wert in werteDesFeldes" :key="wert" :value="wert">{{ wert }}</option>
        </select>
        <button
          v-if="docsetId"
          type="button"
          class="filter-weg"
          :disabled="filterLaeuft"
          @click="filterLoeschen"
        >
          {{ t('kwic.reader.reset') }}
        </button>
      </div>

      <p v-if="listenFehler" class="reader-fehler">{{ listenFehler }}</p>
      <div v-else-if="(ladeListe || filterLaeuft) && !zeilen.length" class="reader-laden">
        <Loader2 class="w-4 h-4 animate-spin" />
        <span>{{ t('kwic.reader.listLoading') }}</span>
      </div>

      <ul v-else class="liste">
        <li v-for="zeile in zeilen" :key="zeile.doc_id">
          <button
            type="button"
            class="listeneintrag"
            :class="{ gewaehlt: zeile.doc_id === gewaehlt }"
            @click="oeffne(zeile.doc_id)"
          >
            <span class="eintrag-kopf">
              <span class="eintrag-kennung">{{ kennzeichnung(zeile) }}</span>
              <span class="eintrag-laenge">{{ t('kwic.reader.tokens', { count: formatNumber(zeile.token_count) }, zeile.token_count) }}</span>
            </span>
            <span class="eintrag-vorschau">{{ zeile.preview }}</span>
          </button>
        </li>
      </ul>

      <footer class="liste-fuss">
        <button type="button" class="blaetter" :disabled="seite === 0" @click="blaettere(-1)">
          <ChevronLeft class="w-4 h-4" />
        </button>
        <span class="text-xs text-neutral-500">{{ t('kwic.reader.page', { page: seite + 1, pages: letzteSeite + 1 }) }}</span>
        <button type="button" class="blaetter" :disabled="seite >= letzteSeite" @click="blaettere(1)">
          <ChevronRight class="w-4 h-4" />
        </button>
      </footer>
    </aside>

    <section class="reader-text">
      <p v-if="textFehler" class="reader-fehler">{{ textFehler }}</p>
      <div v-else-if="ladeText" class="reader-laden">
        <Loader2 class="w-4 h-4 animate-spin" />
        <span>{{ t('kwic.reader.textLoading') }}</span>
      </div>
      <template v-else-if="text">
        <header class="text-kopf">
          <h2>{{ kopfzeile }}</h2>
          <p v-if="unterzeile" class="text-unterzeile">{{ unterzeile }}</p>
          <button type="button" class="meta-schalter" @click="metaOffen = !metaOffen">
            {{ metaOffen ? t('kwic.reader.hideMetadata') : t('kwic.reader.showMetadata', { count: metaAnzahl }) }}
          </button>
          <dl v-if="metaOffen" class="text-meta">
            <template v-for="(wert, schluessel) in text.meta" :key="schluessel">
              <dt>{{ schluessel }}</dt>
              <dd>{{ wert }}</dd>
            </template>
          </dl>
        </header>
        <article class="volltext">{{ text.text }}</article>
      </template>
      <p v-else class="reader-leer">{{ t('kwic.reader.choose') }}</p>
    </section>
  </div>
</template>

<style scoped>
.reader-tab { display: grid; grid-template-columns: minmax(260px, 24rem) 1fr; gap: 1rem; height: 100%; min-height: 0; }
.reader-liste { display: flex; flex-direction: column; min-height: 0; border-right: 1px solid rgb(var(--color-neutral-200)); }
.liste-bereich { padding: 0.375rem 0.75rem; font-size: 0.75rem; color: rgb(var(--color-neutral-600)); border-bottom: 1px solid rgb(var(--color-neutral-200)); }
.liste-filter { display: flex; flex-wrap: wrap; gap: 0.375rem; padding: 0.5rem 0.75rem; border-bottom: 1px solid rgb(var(--color-neutral-200)); }
.filter-feld, .filter-wert { font-size: 0.75rem; padding: 0.25rem 0.375rem; border: 1px solid rgb(var(--color-neutral-300)); border-radius: 0.25rem; background: transparent; max-width: 100%; }
.filter-weg { font-size: 0.75rem; color: rgb(var(--color-neutral-500)); text-decoration: underline; }
.liste-kopf { display: flex; align-items: center; gap: 0.5rem; padding: 0.5rem 0.75rem; border-bottom: 1px solid rgb(var(--color-neutral-200)); }
.liste { flex: 1; overflow-y: auto; margin: 0; padding: 0; list-style: none; }
.listeneintrag { display: flex; flex-direction: column; gap: 0.25rem; width: 100%; text-align: left; padding: 0.5rem 0.75rem; border-bottom: 1px solid rgb(var(--color-neutral-100)); }
.listeneintrag:hover { background: rgb(var(--color-neutral-50)); }
.listeneintrag.gewaehlt { background: rgb(var(--color-primary-50)); }
.eintrag-kopf { display: flex; justify-content: space-between; gap: 0.5rem; font-size: 0.75rem; color: rgb(var(--color-neutral-500)); }
.eintrag-kennung { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.eintrag-laenge { flex-shrink: 0; }
.eintrag-vorschau { font-size: 0.8125rem; line-height: 1.35; display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.liste-fuss { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; padding: 0.5rem 0.75rem; border-top: 1px solid rgb(var(--color-neutral-200)); }
.blaetter:disabled { opacity: 0.4; }
.reader-text { overflow-y: auto; min-height: 0; padding: 0 1rem 2rem 0; }
.text-kopf h2 { font-size: 1.125rem; font-weight: 600; }
.text-unterzeile { font-size: 0.8125rem; color: rgb(var(--color-neutral-500)); margin-top: 0.125rem; }
.meta-schalter { font-size: 0.75rem; color: rgb(var(--color-neutral-500)); text-decoration: underline; margin: 0.5rem 0; }
.text-meta { margin-bottom: 1rem; display: grid; grid-template-columns: auto 1fr; gap: 0.125rem 0.75rem; font-size: 0.75rem; color: rgb(var(--color-neutral-500)); margin-bottom: 1rem; }
.text-meta dt { font-weight: 500; }
.text-meta dd { margin: 0; overflow-wrap: anywhere; }
.volltext { white-space: pre-wrap; line-height: 1.7; font-size: 0.9375rem; max-width: 46rem; }
.reader-laden, .reader-leer, .reader-fehler { display: flex; align-items: center; gap: 0.5rem; padding: 1rem; font-size: 0.875rem; color: rgb(var(--color-neutral-500)); }
.reader-fehler { color: rgb(var(--color-error-600)); }
@media (max-width: 900px) { .reader-tab { grid-template-columns: 1fr; } .reader-liste { border-right: 0; max-height: 40vh; } }
</style>
