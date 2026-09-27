<script setup lang="ts">
/**
 * CollocationNetworkGraph - D3 force-directed network for the
 * /analysis/collocation_network endpoint.
 *
 * Node size = O11 of the word with the node it was reached from (`freq`,
 * `freq_via`), node color = depth (seed / first / second order),
 * edge thickness + optional label = the chosen association measure.
 *
 * Defensive by design: every field is optional and missing data never throws.
 */
import { ref, onMounted, onUnmounted, watch, nextTick } from 'vue'
import * as d3 from 'd3'
import { t } from '@/i18n'
import { currentLocale } from '@/i18n/locale'
import { formatDecimal } from '@/i18n/format'
import type {
  CollocationNetworkNode,
  CollocationNetworkEdge,
} from '@/api/client'

interface Props {
  nodes: CollocationNetworkNode[]
  edges: CollocationNetworkEdge[]
  measureLabel?: string
  showEdgeLabels?: boolean
  height?: number
}

const props = withDefaults(defineProps<Props>(), {
  measureLabel: 'logDice',
  showEdgeLabels: false,
  height: 520,
})

interface SimNode extends d3.SimulationNodeDatum {
  id: string
  freq: number | null
  freqVia: string | null
  depth: number | null
  radius: number
}

interface SimLink extends d3.SimulationLinkDatum<SimNode> {
  source: string | SimNode
  target: string | SimNode
  weight: number
  label: string
}

const containerRef = ref<HTMLDivElement | null>(null)
let simulation: d3.Simulation<SimNode, SimLink> | null = null
let resizeObserver: ResizeObserver | null = null

function depthColor(depth: number | null): string {
  if (depth === 0) return 'var(--color-primary-500)'
  if (depth === 2) return 'var(--color-copilot-primary)'
  return 'var(--color-primary-300)'
}

function radiusForFreq(freq: number | null, depth: number | null): number {
  if (depth === 0) return 22
  const base = typeof freq === 'number' && Number.isFinite(freq) && freq > 0 ? freq : 1
  // sqrt scaling keeps very frequent collocates from dominating the canvas.
  return Math.max(7, Math.min(26, Math.sqrt(base) * 1.6))
}

function render() {
  const container = containerRef.value
  if (!container) return
  container.innerHTML = ''

  const safeNodes = Array.isArray(props.nodes) ? props.nodes : []
  if (!safeNodes.length) return

  const width = container.clientWidth || 600
  const height = props.height
  if (width <= 0 || height <= 0) return

  const nodes: SimNode[] = safeNodes.map((n) => ({
    id: n.id,
    freq: n.freq ?? null,
    freqVia: n.freq_via ?? null,
    depth: n.depth ?? null,
    radius: radiusForFreq(n.freq ?? null, n.depth ?? null),
  }))
  const nodeIds = new Set(nodes.map((n) => n.id))

  const safeEdges = Array.isArray(props.edges) ? props.edges : []
  const links: SimLink[] = safeEdges
    .filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target))
    .map((e) => {
      const weight =
        typeof e.weight === 'number' && Number.isFinite(e.weight) ? e.weight : 0
      return {
        source: e.source,
        target: e.target,
        weight,
        label: weight ? formatDecimal(weight, 1) : '',
      }
    })

  const weights = links.map((l) => l.weight).filter((w) => w > 0)
  const minW = weights.length ? Math.min(...weights) : 0
  const maxW = weights.length ? Math.max(...weights) : 1
  const widthScale = d3
    .scaleLinear()
    .domain([minW, maxW === minW ? minW + 1 : maxW])
    .range([1, 6])
    .clamp(true)

  const svg = d3
    .select(container)
    .append('svg')
    .attr('width', width)
    .attr('height', height)
    .attr('viewBox', [0, 0, width, height])
    .attr('class', 'cn-svg')

  const root = svg.append('g')

  // Zoom / pan. The graph lies in a scrolling tab, so a plain wheel step
  // scrolls the tab. Ctrl or Cmd with the wheel zooms, and so does a pinch on
  // a trackpad (the browser reports it as a wheel event with ctrlKey).
  // Dragging pans.
  svg.call(
    d3
      .zoom<SVGSVGElement, unknown>()
      .filter((event: Event) => {
        if (event.type === 'wheel') {
          const wheel = event as WheelEvent
          return wheel.ctrlKey || wheel.metaKey
        }
        const pointer = event as MouseEvent
        return !pointer.ctrlKey && !pointer.button
      })
      .scaleExtent([0.3, 4])
      .on('zoom', (event) => {
        root.attr('transform', event.transform.toString())
      }) as any
  )

  simulation = d3
    .forceSimulation<SimNode>(nodes)
    .force(
      'link',
      d3
        .forceLink<SimNode, SimLink>(links)
        .id((d: SimNode) => d.id)
        .distance(110)
    )
    .force('charge', d3.forceManyBody().strength(-340))
    .force('center', d3.forceCenter(width / 2, height / 2))
    .force(
      'collision',
      d3.forceCollide<SimNode>().radius((d: SimNode) => d.radius + 12)
    )

  const link = root
    .append('g')
    .attr('class', 'cn-links')
    .selectAll('line')
    .data(links)
    .enter()
    .append('line')
    .attr('stroke', 'var(--color-neutral-300)')
    .attr('stroke-opacity', 0.6)
    .attr('stroke-width', (d: SimLink) => widthScale(d.weight))

  const edgeLabel = props.showEdgeLabels
    ? root
        .append('g')
        .attr('class', 'cn-edge-labels')
        .selectAll('text')
        .data(links)
        .enter()
        .append('text')
        .text((d: SimLink) => d.label)
        .attr('class', 'cn-edge-label')
        .attr('text-anchor', 'middle')
    : null

  const node = root
    .append('g')
    .attr('class', 'cn-nodes')
    .selectAll<SVGGElement, SimNode>('g')
    .data(nodes)
    .enter()
    .append('g')
    .call(
      d3
        .drag<SVGGElement, SimNode>()
        .on('start', dragstarted)
        .on('drag', dragged)
        .on('end', dragended)
    )

  node
    .append('circle')
    .attr('r', (d: SimNode) => d.radius)
    .attr('fill', (d: SimNode) => depthColor(d.depth))
    .attr('stroke', 'var(--color-white)')
    .attr('stroke-width', 2)

  node
    .append('title')
    .text((d: SimNode) => {
      const parts = [d.id]
      if (typeof d.freq === 'number') {
        parts.push(d.freqVia ? t('analysis.charts.o11Via', { via: d.freqVia, freq: d.freq }) : `O11: ${d.freq}`)
      }
      if (d.depth === 0) parts.push(t('analysis.charts.seed'))
      else if (d.depth === 2) parts.push(t('analysis.charts.secondOrder'))
      else parts.push(t('analysis.charts.firstOrder'))
      return parts.join(' · ')
    })

  node
    .append('text')
    .text((d: SimNode) => d.id)
    .attr('x', 0)
    .attr('y', (d: SimNode) => d.radius + 14)
    .attr('text-anchor', 'middle')
    .attr('class', 'cn-node-label')

  simulation.on('tick', () => {
    link
      .attr('x1', (d: SimLink) => (d.source as SimNode).x ?? 0)
      .attr('y1', (d: SimLink) => (d.source as SimNode).y ?? 0)
      .attr('x2', (d: SimLink) => (d.target as SimNode).x ?? 0)
      .attr('y2', (d: SimLink) => (d.target as SimNode).y ?? 0)

    edgeLabel
      ?.attr('x', (d: SimLink) => (((d.source as SimNode).x ?? 0) + ((d.target as SimNode).x ?? 0)) / 2)
      .attr('y', (d: SimLink) => (((d.source as SimNode).y ?? 0) + ((d.target as SimNode).y ?? 0)) / 2)

    node.attr('transform', (d: SimNode) => `translate(${d.x ?? 0},${d.y ?? 0})`)
  })

  function dragstarted(event: d3.D3DragEvent<SVGGElement, SimNode, SimNode>) {
    if (!event.active) simulation?.alphaTarget(0.3).restart()
    event.subject.fx = event.subject.x
    event.subject.fy = event.subject.y
  }

  function dragged(event: d3.D3DragEvent<SVGGElement, SimNode, SimNode>) {
    event.subject.fx = event.x
    event.subject.fy = event.y
  }

  function dragended(event: d3.D3DragEvent<SVGGElement, SimNode, SimNode>) {
    if (!event.active) simulation?.alphaTarget(0)
    event.subject.fx = null
    event.subject.fy = null
  }
}

onMounted(() => {
  nextTick(render)
  if (containerRef.value && typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(() => {
      simulation?.stop()
      render()
    })
    resizeObserver.observe(containerRef.value)
  }
})

onUnmounted(() => {
  simulation?.stop()
  resizeObserver?.disconnect()
})

watch(
  () => [props.nodes, props.edges, props.showEdgeLabels, currentLocale()],
  () => {
    simulation?.stop()
    render()
  },
  { deep: true }
)
</script>

<template>
  <div ref="containerRef" class="cn-graph" :aria-label="t('analysis.charts.network')" />
</template>

<style scoped>
@reference "../../../style.css";

.cn-graph {
  @apply w-full min-h-[300px];
}

.cn-graph :deep(.cn-node-label) {
  @apply fill-neutral-700 dark:fill-neutral-300;
  font-size: 11px;
  pointer-events: none;
}

.cn-graph :deep(.cn-edge-label) {
  @apply fill-neutral-500 dark:fill-neutral-400;
  font-size: 9px;
  pointer-events: none;
}

.cn-graph :deep(circle) {
  cursor: grab;
}

.cn-graph :deep(circle:active) {
  cursor: grabbing;
}

.cn-graph :deep(.cn-svg) {
  @apply rounded-lg;
}
</style>
