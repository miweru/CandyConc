<script setup lang="ts">
/**
 * BarChart - D3-based bar chart for frequency visualization
 */
import { ref, onMounted, onUnmounted, watch, nextTick } from 'vue'
import * as d3 from 'd3'
import { currentLocale } from '@/i18n/locale'
import { localeD3Format } from '@/i18n/d3Format'
import { formatNumber } from '@/i18n/format'

interface DataItem {
  token: string
  freq: number
}

interface Props {
  data: DataItem[]
  height?: number
}

const props = withDefaults(defineProps<Props>(), {
  height: 400
})

const containerRef = ref<HTMLDivElement | null>(null)
let resizeObserver: ResizeObserver | null = null

function render() {
  if (!containerRef.value || !props.data.length) return

  const container = containerRef.value
  container.innerHTML = ''

  const margin = { top: 20, right: 30, bottom: 100, left: 60 }
  const width = container.clientWidth - margin.left - margin.right
  const height = props.height - margin.top - margin.bottom

  if (width <= 0 || height <= 0) return

  const svg = d3.select(container)
    .append('svg')
    .attr('width', width + margin.left + margin.right)
    .attr('height', height + margin.top + margin.bottom)
    .append('g')
    .attr('transform', `translate(${margin.left},${margin.top})`)

  // Scales
  const x = d3.scaleBand<string>()
    .domain(props.data.map((d: DataItem) => d.token))
    .range([0, width])
    .padding(0.2)

  const y = d3.scaleLinear()
    .domain([0, d3.max(props.data, (d: DataItem) => d.freq) || 0])
    .nice()
    .range([height, 0])

  // X Axis
  svg.append('g')
    .attr('transform', `translate(0,${height})`)
    .call(d3.axisBottom(x))
    .selectAll('text')
    .attr('transform', 'rotate(-45)')
    .style('text-anchor', 'end')
    .attr('dx', '-.8em')
    .attr('dy', '.15em')

  // Y Axis
  svg.append('g')
    .call(d3.axisLeft(y).tickFormat(localeD3Format(',.0f')))

  // Bars with transition
  svg.selectAll('.bar')
    .data(props.data)
    .enter()
    .append('rect')
    .attr('class', 'bar')
    .attr('x', (d: DataItem) => x(d.token) || 0)
    .attr('y', height)
    .attr('width', x.bandwidth())
    .attr('height', 0)
    .attr('fill', 'var(--color-primary-500)')
    .attr('rx', 4)
    .transition()
    .duration(500)
    .attr('y', (d: DataItem) => y(d.freq))
    .attr('height', (d: DataItem) => height - y(d.freq))

  // Hover effects - need to re-select after transition
  svg.selectAll<SVGRectElement, DataItem>('.bar')
    .on('mouseover', function(_event: MouseEvent, d: DataItem) {
      d3.select(this).attr('fill', 'var(--color-primary-600)')

      // Tooltip
      svg.append('text')
        .attr('class', 'tooltip')
        .attr('x', (x(d.token) || 0) + x.bandwidth() / 2)
        .attr('y', y(d.freq) - 8)
        .attr('text-anchor', 'middle')
        .text(formatNumber(d.freq))
    })
    .on('mouseout', function() {
      d3.select(this).attr('fill', 'var(--color-primary-500)')
      svg.selectAll('.tooltip').remove()
    })
}

onMounted(() => {
  nextTick(render)

  if (containerRef.value) {
    resizeObserver = new ResizeObserver(() => {
      render()
    })
    resizeObserver.observe(containerRef.value)
  }
})

onUnmounted(() => {
  resizeObserver?.disconnect()
})

watch(() => props.data, render, { deep: true })
// Axis and label numbers follow the interface language.
watch(() => currentLocale(), render)
</script>

<template>
  <div ref="containerRef" class="bar-chart" />
</template>

<style scoped>
@reference "../../../style.css";

.bar-chart {
  @apply w-full min-h-[200px];
}

.bar-chart :deep(text) {
  @apply fill-neutral-600 dark:fill-neutral-400;
  font-size: 12px;
}

.bar-chart :deep(.tooltip) {
  @apply fill-neutral-900 dark:fill-neutral-100;
  font-size: 11px;
  font-weight: 600;
}

.bar-chart :deep(.domain),
.bar-chart :deep(.tick line) {
  @apply stroke-neutral-300 dark:stroke-neutral-600;
}
</style>
