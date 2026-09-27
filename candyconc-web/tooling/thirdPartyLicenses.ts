// Collects the licenses of every npm package that ends up in the production
// bundle and emits them as THIRD_PARTY_LICENSES.txt next to index.html.
// Runs on every `vite build`, so the notices always match the shipped files.
import { existsSync, readdirSync, readFileSync } from 'node:fs'
import { join, sep } from 'node:path'
import type { Plugin } from 'vite'

interface PackageNotice {
  name: string
  version: string
  license: string
  homepage: string
  texts: string[]
}

const NOTICE_FILE = /^(licen[cs]e|copying|notice)([.-].*)?$/i
const MARKER = `${sep}node_modules${sep}`

function packageRoot(moduleId: string): string | null {
  const path = moduleId.replace(/^\0/, '').split('?')[0]
  const at = path.lastIndexOf(MARKER)
  if (at < 0) return null
  const parts = path.slice(at + MARKER.length).split(sep)
  const depth = parts[0].startsWith('@') ? 2 : 1
  if (parts.length <= depth) return null
  return path.slice(0, at + MARKER.length) + parts.slice(0, depth).join(sep)
}

function readNotice(root: string): PackageNotice | null {
  const manifestPath = join(root, 'package.json')
  if (!existsSync(manifestPath)) return null
  const manifest = JSON.parse(readFileSync(manifestPath, 'utf-8')) as Record<string, unknown>
  const repository = manifest.repository
  const repositoryUrl =
    typeof repository === 'string'
      ? repository
      : typeof repository === 'object' && repository !== null
        ? String((repository as Record<string, unknown>).url ?? '')
        : ''
  const texts = readdirSync(root)
    .filter((name) => NOTICE_FILE.test(name))
    .sort()
    .map((name) => readFileSync(join(root, name), 'utf-8').trim())
  return {
    name: String(manifest.name ?? root),
    version: String(manifest.version ?? ''),
    license: String(manifest.license ?? 'see package'),
    homepage: String(manifest.homepage ?? repositoryUrl),
    texts,
  }
}

// Packages whose output a build plugin generates without a module import, so
// they never appear in the module graph (Tailwind writes its CSS directly).
const GENERATED_BY_PLUGINS = ['tailwindcss']

export function thirdPartyLicenses(fileName = 'THIRD_PARTY_LICENSES.txt'): Plugin {
  let projectRoot = process.cwd()
  return {
    name: 'candyconc-third-party-licenses',
    apply: 'build',
    configResolved(config) {
      projectRoot = config.root
    },
    generateBundle() {
      const roots = new Set<string>()
      for (const id of this.getModuleIds()) {
        const root = packageRoot(id)
        if (root) roots.add(root)
      }
      for (const name of GENERATED_BY_PLUGINS) {
        roots.add(join(projectRoot, 'node_modules', name))
      }
      const seen = new Set<string>()
      const notices = [...roots]
        .map(readNotice)
        .filter((notice): notice is PackageNotice => notice !== null)
        .filter((notice) => {
          const key = `${notice.name}@${notice.version}`
          if (seen.has(key)) return false
          seen.add(key)
          return true
        })
        .sort((a, b) => a.name.localeCompare(b.name))
      const rule = '='.repeat(78)
      const sections = notices.map((notice) =>
        [
          rule,
          `${notice.name} ${notice.version}`,
          `License: ${notice.license}`,
          notice.homepage ? `Source: ${notice.homepage}` : '',
          '',
          notice.texts.length > 0
            ? notice.texts.join('\n\n')
            : `The package ships no license file. Its package.json declares: ${notice.license}`,
        ]
          .filter((line, index) => index !== 3 || line !== '')
          .join('\n'),
      )
      const header = [
        'Third-party software in the CandyConc web interface',
        '',
        'The files in this directory bundle the following npm packages.',
        `Generated at build time from the installed packages (${notices.length} packages).`,
        '',
      ].join('\n')
      this.emitFile({ type: 'asset', fileName, source: `${header}\n${sections.join('\n\n')}\n` })
    },
  }
}
