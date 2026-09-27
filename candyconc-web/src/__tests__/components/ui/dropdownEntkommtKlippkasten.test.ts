/**
 * Ein Menue, das ein Vorfahre beschneidet, ist unbedienbar.
 *
 * BEANSTANDET am 2026-08-31, woertlich: "wenn man auf mehr drueckt, dann
 * ist der Popup um dieses mehr zu finden nicht vorne angezeigt sondern
 * eher hinter den Hauptelementen weswegen man im Formular da scrollen
 * muss."
 *
 * Es war KEIN z-index-Problem. Die Registerleiste (TabNav.vue:155) traegt
 * `overflow-x-auto`. Nach der CSS-Spezifikation rechnet das die andere
 * Achse von `visible` auf `auto` um, die 56 Pixel hohe Leiste war damit
 * ein Klippkasten auf BEIDEN Achsen, und ein `position: absolute`-Menue
 * wird von jedem Overflow-Vorfahren beschnitten. Gemessen bei 1440x900:
 * Menue 182x317 Pixel, sichtbar davon 53 Pixel, also 83 Prozent wurden
 * gar nicht gezeichnet.
 *
 * Kein z-index kann das heilen. Die Loesung ist, das Menue aus jedem
 * Klippkasten herauszunehmen. Diese Datei prueft genau das, und zwar
 * strukturell, weil jsdom kein Layout rechnet: das Menue darf KEIN
 * Nachfahre der Dropdown-Wurzel mehr sein, und seine Lage kommt aus dem
 * Rechteck des Ausloesers.
 *
 * Vor dieser Datei hatte die Komponente NULL Testdeckung.
 */
import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'

import Dropdown from '@/components/ui/Dropdown.vue'

// Montierte Komponenten sauber abraeumen. body.innerHTML zu leeren, waehrend
// eine Komponente noch montiert ist, nimmt dem Portal seinen Einhaengepunkt,
// und der naechste Test stirbt an insertBefore auf null.
const montiert: { unmount: () => void }[] = []

function merken<T extends { unmount: () => void }>(w: T): T {
  montiert.push(w)
  return w
}

function mounten() {
  return merken(mount(Dropdown, {
    attachTo: document.body,
    slots: {
      trigger: '<button type="button" class="ausloeser">Mehr</button>',
      default: '<div role="menuitem" tabindex="0">Eintrag</div>',
    },
  }))
}

function ausloeserRechteck(wrapper: ReturnType<typeof mounten>, r: Partial<DOMRect>) {
  const el = wrapper.find('.dropdown-trigger').element as HTMLElement
  el.getBoundingClientRect = () =>
    ({ top: 100, bottom: 137, left: 220, right: 402, width: 182, height: 37, x: 220, y: 100, toJSON: () => ({}), ...r }) as DOMRect
}

function menuImDokument(): HTMLElement | null {
  return document.body.querySelector('.dropdown-menu')
}

afterEach(() => {
  while (montiert.length) montiert.pop()?.unmount()
  document.body.innerHTML = ''
})

describe('Dropdown entkommt dem Klippkasten', () => {
  it('haengt das Menue NICHT mehr unter die Dropdown-Wurzel', async () => {
    const wrapper = mounten()
    ausloeserRechteck(wrapper, {})
    await wrapper.find('.dropdown-trigger').trigger('click')

    const menue = menuImDokument()
    expect(menue).not.toBeNull()

    const wurzel = wrapper.find('.dropdown').element
    expect(wurzel.contains(menue)).toBe(false)
    expect(menue?.parentElement).not.toBeNull()
  })

  it('liest seine Lage aus dem Rechteck des Ausloesers', async () => {
    const wrapper = mounten()
    ausloeserRechteck(wrapper, {})
    await wrapper.find('.dropdown-trigger').trigger('click')

    const menue = menuImDokument() as HTMLElement
    expect(menue.style.top).toBe('137px')
    expect(menue.style.left).toBe('220px')
    expect(menue.style.right).toBe('auto')
  })

  it('richtet sich bei align=right an der rechten Kante aus', async () => {
    const wrapper = merken(mount(Dropdown, {
      attachTo: document.body,
      props: { align: 'right' },
      slots: {
        trigger: '<button type="button">Mehr</button>',
        default: '<div role="menuitem" tabindex="0">Eintrag</div>',
      },
    }))
    ausloeserRechteck(wrapper as never, {})
    await wrapper.find('.dropdown-trigger').trigger('click')

    const menue = menuImDokument() as HTMLElement
    expect(menue.style.left).toBe('auto')
    expect(menue.style.right).toBe(`${window.innerWidth - 402}px`)
  })

  it('uebernimmt bei width=trigger die Breite des Ausloesers', async () => {
    const wrapper = merken(mount(Dropdown, {
      attachTo: document.body,
      props: { width: 'trigger' },
      slots: {
        trigger: '<button type="button">Mehr</button>',
        default: '<div role="menuitem" tabindex="0">Eintrag</div>',
      },
    }))
    ausloeserRechteck(wrapper as never, {})
    await wrapper.find('.dropdown-trigger').trigger('click')

    expect((menuImDokument() as HTMLElement).style.width).toBe('182px')
  })

  it('schliesst weiterhin bei einem Klick ausserhalb', async () => {
    const wrapper = mounten()
    ausloeserRechteck(wrapper, {})
    await wrapper.find('.dropdown-trigger').trigger('click')
    expect(menuImDokument()).not.toBeNull()

    document.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await wrapper.vm.$nextTick()
    expect(menuImDokument()).toBeNull()
  })
})
