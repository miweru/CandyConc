<script setup lang="ts">
/**
 * ForceGraph - D3 force-directed graph for collocation networks
 */
import { ref, onMounted, onUnmounted, watch, nextTick } from 'vue'
import * as d3 from 'd3'

interface Node {
  id: string
  group: 'center' | 'collocate'
  size: number
}

interface Link {
  source: string
  target: string
  value: number
}

// Extended types for D3 simulation
interface SimNode extends Node, d3.SimulationNodeDatum {
  x?: number
  y?: number
  fx?: number | null
  fy?: number | null
}

interface SimLink extends d3.SimulationLinkDatum<SimNode> {
  value: number
}

interface Props {
  data: {
    nodes: Node[]
    links: Link[]
  }
  height?: number
}

const props = withDefaults(defineProps<Props>(), {
  height: 500
})

const containerRef = ref<HTMLDivElement | null>(null)
let simulation: d3.Simulation<SimNode, SimLink> | null = null

function render() {
  if (!containerRef.value || !props.data.nodes.length) return

  const container = containerRef.value
  container.innerHTML = ''

  const width = container.clientWidth
  const height = props.height

  if (width <= 0 || height <= 0) return

  const svg = d3.select(container)
    .append('svg')
    .attr('width', width)
    .attr('height', height)
    .attr('viewBox', [0, 0, width, height])

  // Create a copy of nodes and links for simulation
  const nodes: SimNode[] = props.data.nodes.map(d => ({ ...d }))
  const links: SimLink[] = props.data.links.map(d => ({ ...d }))

  // Color scale
  const color = (group: string) => group === 'center'
    ? 'var(--color-primary-500)'
    : 'var(--color-copilot-primary)'

  // Force simulation
  simulation = d3.forceSimulation<SimNode>(nodes)
    .force('link', d3.forceLink<SimNode, SimLink>(links).id((d: SimNode) => d.id).distance(100))
    .force('charge', d3.forceManyBody().strength(-300))
    .force('center', d3.forceCenter(width / 2, height / 2))
    .force('collision', d3.forceCollide<SimNode>().radius((d: SimNode) => d.size + 10))

  // Links
  const link = svg.append('g')
    .attr('class', 'links')
    .selectAll('line')
    .data(links)
    .enter()
    .append('line')
    .attr('stroke', 'var(--color-neutral-300)')
    .attr('stroke-opacity', 0.6)
    .attr('stroke-width', (d: SimLink) => Math.sqrt(d.value) * 0.5)

  // Nodes
  const node = svg.append('g')
    .attr('class', 'nodes')
    .selectAll<SVGGElement, SimNode>('g')
    .data(nodes)
    .enter()
    .append('g')
    .call(d3.drag<SVGGElement, SimNode>()
      .on('start', dragstarted)
      .on('drag', dragged)
      .on('end', dragended))

  // Node circles
  node.append('circle')
    .attr('r', (d: SimNode) => d.size)
    .attr('fill', (d: SimNode) => color(d.group))
    .attr('stroke', 'var(--color-white)')
    .attr('stroke-width', 2)

  // Node labels
  node.append('text')
    .text((d: SimNode) => d.id)
    .attr('x', 0)
    .attr('y', (d: SimNode) => d.size + 14)
    .attr('text-anchor', 'middle')
    .attr('class', 'node-label')

  // Simulation tick
  simulation.on('tick', () => {
    link
      .attr('x1', (d: SimLink) => (d.source as SimNode).x || 0)
      .attr('y1', (d: SimLink) => (d.source as SimNode).y || 0)
      .attr('x2', (d: SimLink) => (d.target as SimNode).x || 0)
      .attr('y2', (d: SimLink) => (d.target as SimNode).y || 0)

    node.attr('transform', (d: SimNode) => `translate(${d.x || 0},${d.y || 0})`)
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
})

onUnmounted(() => {
  simulation?.stop()
})

watch(() => props.data, () => {
  simulation?.stop()
  render()
}, { deep: true })
</script>

<template>
  <div ref="containerRef" class="force-graph" />
</template>

<style scoped>
@reference "../../../style.css";

.force-graph {
  @apply w-full min-h-[300px];
}

.force-graph :deep(.node-label) {
  @apply fill-neutral-700 dark:fill-neutral-300;
  font-size: 11px;
  pointer-events: none;
}

.force-graph :deep(circle) {
  cursor: grab;
}

.force-graph :deep(circle:active) {
  cursor: grabbing;
}
</style>
