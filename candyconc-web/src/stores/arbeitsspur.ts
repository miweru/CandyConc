/**
 * Die Ansicht der Arbeitsspur, und NUR die Ansicht.
 *
 * Die Spur selbst wird aus der Nachricht abgeleitet, nicht hier gespeichert:
 * `ChatMessage` traegt bereits `toolCalls` und `stages`, und zwei Quellen
 * fuer denselben Sachverhalt laufen frueher oder spaeter auseinander. Hier
 * steht deshalb ausschliesslich, WIE die Spur gerade gezeigt wird und
 * welcher Nachricht sie folgt.
 *
 * Drei Zustaende, wie bei einem Abspielgeraet:
 *
 * - `aus`      niemand sieht etwas, die Arbeitsflaeche gehoert der Suche
 * - `leiste`   eine schmale Zeile am unteren Rand, faehrt beim Turnstart
 *              von selbst ein und zeigt den laufenden Schritt
 * - `gross`    die Spur legt sich UEBER die Arbeitsflaeche, der Chat bleibt
 *              rechts daneben stehen
 *
 * `gross` ueberlagert, es tauscht nichts aus. Wer minimiert, findet die
 * Konkordanz, die Frequenzliste oder den Kontrast unveraendert vor, samt
 * Bildlaufstand und Auswahl. Ein Austausch waere billiger zu bauen und
 * wuerde genau das zerstoeren, was der Nutzer gerade in der Hand hatte.
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export type ArbeitsspurModus = 'aus' | 'leiste' | 'gross'

export const useArbeitsspurStore = defineStore('arbeitsspur', () => {
  const modus = ref<ArbeitsspurModus>('aus')

  /** Die Nachricht, deren Arbeit gezeigt wird. Leer = die juengste. */
  const verfolgteNachricht = ref<string | null>(null)

  /**
   * Hat jemand die Spur in diesem Turn von Hand geschlossen?
   *
   * Ohne diese Marke faehrt sie beim naechsten Statusframe wieder ein, und
   * eine Ansicht, die sich gegen den erklaerten Willen erneut oeffnet, ist
   * eine Zumutung. Die Marke faellt beim naechsten Turn.
   */
  const inDiesemTurnGeschlossen = ref(false)

  const istSichtbar = computed(() => modus.value !== 'aus')
  const istGross = computed(() => modus.value === 'gross')

  /** Ein Turn beginnt: die Spur faehrt ein, sofern niemand widersprochen hat. */
  function turnBeginnt(nachrichtId: string): void {
    verfolgteNachricht.value = nachrichtId
    inDiesemTurnGeschlossen.value = false
    if (modus.value === 'aus') modus.value = 'leiste'
  }

  function zeigen(nachrichtId?: string): void {
    if (nachrichtId) verfolgteNachricht.value = nachrichtId
    if (modus.value === 'aus') modus.value = 'leiste'
  }

  function vergroessern(nachrichtId?: string): void {
    if (nachrichtId) verfolgteNachricht.value = nachrichtId
    modus.value = 'gross'
  }

  function verkleinern(): void {
    modus.value = 'leiste'
  }

  function schliessen(): void {
    modus.value = 'aus'
    inDiesemTurnGeschlossen.value = true
  }

  function umschalten(nachrichtId?: string): void {
    if (modus.value === 'gross') verkleinern()
    else vergroessern(nachrichtId)
  }

  return {
    modus,
    verfolgteNachricht,
    inDiesemTurnGeschlossen,
    istSichtbar,
    istGross,
    turnBeginnt,
    zeigen,
    vergroessern,
    verkleinern,
    schliessen,
    umschalten,
  }
})
