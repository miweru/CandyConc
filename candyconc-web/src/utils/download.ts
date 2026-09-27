/**
 * Kanonischer Browser-Download-Helfer (Blob → temporärer Object-URL → Klick).
 *
 * Einzige Implementierung dieses Musters im Frontend; lokale Kopien in
 * Komponenten/Services importieren von hier. No-op außerhalb einer
 * DOM-Umgebung (SSR / Tests ohne jsdom).
 */
export function downloadBlob(blob: Blob, filename: string): void {
  if (typeof document === 'undefined') return
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

/** Download beliebigen Textinhalts mit explizitem MIME-Type. */
export function downloadText(content: string, filename: string, mimeType: string): void {
  downloadBlob(new Blob([content], { type: mimeType }), filename)
}
