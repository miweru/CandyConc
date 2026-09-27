import { describe, expect, it } from 'vitest'

import {
  applyMetaLiteralOverrides,
  applyNodeLiteralOverrides,
  collectMetaLiteralTargets,
  collectNodeLiteralTargets,
  createBuilderNode,
  createLiteral,
  createMetaCond,
  createMetaGroup,
  createTokenCondition,
  duplicateMetaSibling,
  duplicateNodeSibling,
  extractMetaSibling,
  extractNodeSibling,
  findMetaExprById,
  findNodeById,
  generateBuilderQuery,
  groupSelectedMetaSiblings,
  groupSelectedNodeSiblings,
  hydrateBuilderState,
  insertMetaSibling,
  insertNodeSibling,
  moveSelectedMetaSiblings,
  moveSelectedNodeSiblings,
  normalizeSelectedMetaExpr,
  normalizeSelectedNode,
  transformMetaExprInTree,
  transformNodeInTree,
  type CqlBuilderNode,
  ungroupMetaSibling,
  ungroupNodeSibling,
  wrapMetaExpr,
  wrapNode,
  wrapSelectedNodeSiblings,
} from '@/lib/queryBuilder/ast'

function tok(...conditions: ReturnType<typeof createTokenCondition>[]): CqlBuilderNode {
  return {
    id: crypto.randomUUID(),
    type: 'tok',
    conditions,
  }
}

describe('cqlBuilder exact AST mapping', () => {
  it('renders nested alternatives in the middle of sequences without losing grouping', () => {
    const query = generateBuilderQuery({
      id: crypto.randomUUID(),
      type: 'seq',
      parts: [
        tok(createTokenCondition({ attr: 'word', op: '=', scalar: createLiteral({ value: 'A' }) })),
        {
          id: crypto.randomUUID(),
          type: 'alt',
          options: [
            {
              id: crypto.randomUUID(),
              type: 'seq',
              parts: [
                tok(createTokenCondition({ attr: 'word', op: '=', scalar: createLiteral({ value: 'B' }) })),
                tok(createTokenCondition({ attr: 'word', op: '=', scalar: createLiteral({ value: 'C' }) })),
              ],
            },
            tok(createTokenCondition({ attr: 'word', op: '=', scalar: createLiteral({ value: 'D' }) })),
          ],
        },
        tok(createTokenCondition({ attr: 'word', op: '=', scalar: createLiteral({ value: 'E' }) })),
      ],
    })

    expect(query).toBe('[word="A"] ([word="B"] [word="C"] | [word="D"]) [word="E"]')
  })

  it('renders quantifiers over alternatives exactly', () => {
    const query = generateBuilderQuery({
      id: crypto.randomUUID(),
      type: 'quant',
      min: 1,
      max: null,
      node: {
        id: crypto.randomUUID(),
        type: 'alt',
        options: [
          tok(createTokenCondition({ attr: 'lemma', op: '=', scalar: createLiteral({ value: 'Hase' }) })),
          tok(createTokenCondition({ attr: 'word', op: '~', scalar: createLiteral({ value: '^pr.*' }) })),
        ],
      },
    })

    expect(query).toBe('([lemma="Hase"] | [word~"^pr.*"])+')
  })

  it('preserves CQL value flags such as %c through rendering and hydration', () => {
    expect(generateBuilderQuery(tok(createTokenCondition({
      attr: 'word',
      op: '=',
      scalar: createLiteral({ value: 'Haus' }),
      flags: 'c',
    })))).toBe('[word="Haus" %c]')

    expect(generateBuilderQuery(tok(createTokenCondition({
      attr: 'lemma',
      op: 'in',
      setValues: [createLiteral({ value: 'gehen' }), createLiteral({ value: 'ging' })],
      flags: 'c',
    })))).toBe('[lemma in {"gehen", "ging"} %c]')

    const hydrated = hydrateBuilderState({
      type: 'tok',
      conds: [{ attr: 'word', op: '~', value: '^haus', flags: 'c' }],
    })

    expect(hydrated.node).toBeTruthy()
    expect(generateBuilderQuery(hydrated.node!)).toBe('[word~"^haus" %c]')
  })

  it('round-trips empty token clauses as any-token queries', () => {
    expect(generateBuilderQuery(tok())).toBe('[]')

    const hydrated = hydrateBuilderState({
      type: 'seq',
      parts: [
        { type: 'tok', conds: [] },
        { type: 'tok', conds: [{ attr: 'lemma', op: '=', value: 'Haus' }] },
      ],
    })

    expect(hydrated.node).toBeTruthy()
    expect(hydrated.unsupportedReason).toBeUndefined()
    expect(generateBuilderQuery(hydrated.node!)).toBe('[] [lemma="Haus"]')
  })

  it('does not preserve unsupported case-insensitive flags on negated token conditions', () => {
    expect(generateBuilderQuery(tok(createTokenCondition({
      attr: 'word',
      op: '!=',
      scalar: createLiteral({ value: 'Haus' }),
      flags: 'c',
    })))).toBe('[word!="Haus"]')

    const hydrated = hydrateBuilderState({
      type: 'tok',
      conds: [{ attr: 'word', op: '!=', value: 'Haus', flags: 'c' }],
    })

    expect(hydrated.node).toBeTruthy()
    expect(generateBuilderQuery(hydrated.node!)).toBe('[word!="Haus"]')
  })

  it('renders nested metadata groups with preserved precedence', () => {
    const query = generateBuilderQuery({
      id: crypto.randomUUID(),
      type: 'where',
      expr: createMetaGroup('and', {
        parts: [
          createMetaCond({ field: 'source', op: '=', value: createLiteral({ value: 'mlsum' }) }),
          createMetaGroup('or', {
            parts: [
              createMetaCond({ field: 'genre', op: '=', value: createLiteral({ value: 'news' }) }),
              createMetaCond({ field: 'year', op: '>=', value: createLiteral({ kind: 'number', value: '2024' }) }),
            ],
          }),
        ],
      }),
      node: {
        id: crypto.randomUUID(),
        type: 'within',
        scope: 's',
        node: tok(createTokenCondition({ attr: 'sim', op: '=', scalar: createLiteral({ value: 'Hase' }) })),
      },
    })

    expect(query).toBe('where(source="mlsum" & (genre="news" | year>=2024), within(<s>, [sim="Hase"]))')
  })

  it('hydrates exact backend builder json including nested seq/alt/where', () => {
    const hydrated = hydrateBuilderState({
      type: 'where',
      expr: {
        kind: 'and',
        parts: [
          { kind: 'cond', field: 'source', op: '=', value: 'mlsum' },
          {
            kind: 'or',
            parts: [
              { kind: 'cond', field: 'genre', op: '=', value: 'news' },
              { kind: 'cond', field: 'year', op: '>=', value: 2024 },
            ],
          },
        ],
      },
      node: {
        type: 'seq',
        parts: [
          { type: 'tok', conds: [{ attr: 'word', op: '=', value: 'A' }] },
          {
            type: 'alt',
            options: [
              {
                type: 'seq',
                parts: [
                  { type: 'tok', conds: [{ attr: 'word', op: '=', value: 'B' }] },
                  { type: 'tok', conds: [{ attr: 'word', op: '=', value: 'C' }] },
                ],
              },
              { type: 'tok', conds: [{ attr: 'k', op: '=', value: 20 }, { attr: 'sim', op: '=', value: 'Hase' }] },
            ],
          },
        ],
      },
    })

    expect(hydrated.node).not.toBeNull()
    expect(hydrated.unsupportedReason).toBeUndefined()
    expect(generateBuilderQuery(hydrated.node!)).toBe(
      'where(source="mlsum" & (genre="news" | year>=2024), [word="A"] ([word="B"] [word="C"] | [k=20 & sim="Hase"]))'
    )
  })

  it('creates exact default nodes for all real AST node types', () => {
    expect(createBuilderNode('tok').type).toBe('tok')
    expect(createBuilderNode('seq').type).toBe('seq')
    expect(createBuilderNode('alt').type).toBe('alt')
    expect(createBuilderNode('quant').type).toBe('quant')
    expect(createBuilderNode('within').type).toBe('within')
    expect(createBuilderNode('where').type).toBe('where')
  })

  it('does not emit invalid empty token clauses for a blank starter node', () => {
    expect(generateBuilderQuery(createBuilderNode('tok'))).toBe('')
  })

  it('wraps a selected node into within(...) without losing the existing subtree', () => {
    const root: CqlBuilderNode = {
      id: crypto.randomUUID(),
      type: 'seq',
      parts: [
        tok(createTokenCondition({ attr: 'lemma', op: '=', scalar: createLiteral({ value: 'Haus' }) })),
        tok(createTokenCondition({ attr: 'word', op: '=', scalar: createLiteral({ value: 'Baum' }) })),
      ],
    }
    const target = root.parts[0]
    const next = transformNodeInTree(root, target.id, (node) => wrapNode(node, 'within'))
    const wrapped = findNodeById(next, target.id)

    expect(generateBuilderQuery(next)).toBe('within(<s>, [lemma="Haus"]) [word="Baum"]')
    expect(wrapped?.type).toBe('tok')
  })

  it('wraps a selected meta condition into an OR group while preserving the original condition', () => {
    const root: CqlBuilderNode = {
      id: crypto.randomUUID(),
      type: 'where',
      expr: createMetaGroup('and', {
        parts: [
          createMetaCond({ field: 'source', op: '=', value: createLiteral({ value: 'mlsum' }) }),
          createMetaCond({ field: 'year', op: '>=', value: createLiteral({ kind: 'number', value: '2024' }) }),
        ],
      }),
      node: tok(createTokenCondition({ attr: 'lemma', op: '=', scalar: createLiteral({ value: 'Hase' }) })),
    }
    const target = root.expr.parts[0]
    const next = transformMetaExprInTree(root, target.id, (expr) => wrapMetaExpr(expr, 'or'))
    const wrappedGroup = next.type === 'where' ? next.expr.parts[0] : null
    const wrapped = findMetaExprById((next.type === 'where' ? next.expr : createMetaGroup('and')), target.id)

    expect(wrappedGroup?.kind).toBe('or')
    expect(wrappedGroup && wrappedGroup.kind !== 'cond' ? wrappedGroup.parts : []).toHaveLength(2)
    expect(wrapped?.kind).toBe('cond')
  })

  it('groups selected sibling query nodes into an alternative', () => {
    const first = tok(createTokenCondition({ attr: 'word', op: '=', scalar: createLiteral({ value: 'A' }) }))
    const second = tok(createTokenCondition({ attr: 'word', op: '=', scalar: createLiteral({ value: 'B' }) }))
    const third = tok(createTokenCondition({ attr: 'word', op: '=', scalar: createLiteral({ value: 'C' }) }))
    const root: CqlBuilderNode = {
      id: crypto.randomUUID(),
      type: 'seq',
      parts: [first, second, third],
    }

    const grouped = groupSelectedNodeSiblings(root, [first.id, second.id], 'alt')
    expect(grouped?.type).toBe('alt')
    expect(generateBuilderQuery(root)).toBe('([word="A"] | [word="B"]) [word="C"]')
  })

  it('wraps a selected sequence range into a quantifier while preserving sequence semantics', () => {
    const first = tok(createTokenCondition({ attr: 'word', op: '=', scalar: createLiteral({ value: 'A' }) }))
    const second = tok(createTokenCondition({ attr: 'word', op: '=', scalar: createLiteral({ value: 'B' }) }))
    const third = tok(createTokenCondition({ attr: 'word', op: '=', scalar: createLiteral({ value: 'C' }) }))
    const root: CqlBuilderNode = {
      id: crypto.randomUUID(),
      type: 'seq',
      parts: [first, second, third],
    }

    const wrapped = wrapSelectedNodeSiblings(root, [first.id, second.id], 'quant')
    expect(wrapped?.type).toBe('quant')
    expect(generateBuilderQuery(root)).toBe('([word="A"] [word="B"])? [word="C"]')
  })

  it('wraps selected alternative arms into where(...) without flattening them', () => {
    const first = tok(createTokenCondition({ attr: 'word', op: '=', scalar: createLiteral({ value: 'A' }) }))
    const second = tok(createTokenCondition({ attr: 'word', op: '=', scalar: createLiteral({ value: 'B' }) }))
    const third = tok(createTokenCondition({ attr: 'word', op: '=', scalar: createLiteral({ value: 'C' }) }))
    const root: CqlBuilderNode = {
      id: crypto.randomUUID(),
      type: 'alt',
      options: [first, second, third],
    }

    const wrapped = wrapSelectedNodeSiblings(root, [first.id, second.id], 'where')
    expect(wrapped?.type).toBe('where')
    expect(generateBuilderQuery(root)).toBe('(where(, ([word="A"] | [word="B"])) | [word="C"])')
  })

  it('moves a contiguous query selection to the end of its sibling block', () => {
    const first = tok(createTokenCondition({ attr: 'word', op: '=', scalar: createLiteral({ value: 'A' }) }))
    const second = tok(createTokenCondition({ attr: 'word', op: '=', scalar: createLiteral({ value: 'B' }) }))
    const third = tok(createTokenCondition({ attr: 'word', op: '=', scalar: createLiteral({ value: 'C' }) }))
    const fourth = tok(createTokenCondition({ attr: 'word', op: '=', scalar: createLiteral({ value: 'D' }) }))
    const root: CqlBuilderNode = {
      id: crypto.randomUUID(),
      type: 'seq',
      parts: [first, second, third, fourth],
    }

    const moved = moveSelectedNodeSiblings(root, [second.id, third.id], 4)
    expect(moved).toHaveLength(2)
    expect(generateBuilderQuery(root)).toBe('[word="A"] [word="D"] [word="B"] [word="C"]')
  })

  it('groups selected sibling meta expressions into an OR group', () => {
    const source = createMetaCond({ field: 'source', op: '=', value: createLiteral({ value: 'mlsum' }) })
    const genre = createMetaCond({ field: 'genre', op: '=', value: createLiteral({ value: 'news' }) })
    const year = createMetaCond({ field: 'year', op: '>=', value: createLiteral({ kind: 'number', value: '2024' }) })
    const root: CqlBuilderNode = {
      id: crypto.randomUUID(),
      type: 'where',
      expr: createMetaGroup('and', { parts: [source, genre, year] }),
      node: tok(createTokenCondition({ attr: 'lemma', op: '=', scalar: createLiteral({ value: 'Hase' }) })),
    }

    const grouped = groupSelectedMetaSiblings(root, [source.id, genre.id], 'or')
    expect(grouped?.kind).toBe('or')
    expect(generateBuilderQuery(root)).toBe('where((source="mlsum" | genre="news") & year>=2024, [lemma="Hase"])')
  })

  it('moves a contiguous meta selection within the same parent group', () => {
    const source = createMetaCond({ field: 'source', op: '=', value: createLiteral({ value: 'mlsum' }) })
    const genre = createMetaCond({ field: 'genre', op: '=', value: createLiteral({ value: 'news' }) })
    const year = createMetaCond({ field: 'year', op: '>=', value: createLiteral({ kind: 'number', value: '2024' }) })
    const register = createMetaCond({ field: 'register', op: '=', value: createLiteral({ value: 'essay' }) })
    const root: CqlBuilderNode = {
      id: crypto.randomUUID(),
      type: 'where',
      expr: createMetaGroup('and', { parts: [source, genre, year, register] }),
      node: tok(createTokenCondition({ attr: 'lemma', op: '=', scalar: createLiteral({ value: 'Hase' }) })),
    }

    const moved = moveSelectedMetaSiblings(root, [genre.id, year.id], 4)
    expect(moved).toHaveLength(2)
    expect(generateBuilderQuery(root)).toBe('where(source="mlsum" & register="essay" & genre="news" & year>=2024, [lemma="Hase"])')
  })

  it('duplicates a selected query node as a fresh sibling copy', () => {
    const first = tok(createTokenCondition({ attr: 'lemma', op: '=', scalar: createLiteral({ value: 'Haus' }) }))
    const second = tok(createTokenCondition({ attr: 'word', op: '=', scalar: createLiteral({ value: 'Baum' }) }))
    const root: CqlBuilderNode = {
      id: crypto.randomUUID(),
      type: 'seq',
      parts: [first, second],
    }

    const duplicate = duplicateNodeSibling(root, first.id)
    expect(duplicate).not.toBeNull()
    expect(duplicate?.id).not.toBe(first.id)
    expect(generateBuilderQuery(root)).toBe('[lemma="Haus"] [lemma="Haus"] [word="Baum"]')
  })

  it('normalizes nested sequence wrappers into a flatter exact AST', () => {
    const nestedSeq: CqlBuilderNode = {
      id: crypto.randomUUID(),
      type: 'seq',
      parts: [
        tok(createTokenCondition({ attr: 'word', op: '=', scalar: createLiteral({ value: 'A' }) })),
        {
          id: crypto.randomUUID(),
          type: 'seq',
          parts: [
            tok(createTokenCondition({ attr: 'word', op: '=', scalar: createLiteral({ value: 'B' }) })),
            tok(createTokenCondition({ attr: 'word', op: '=', scalar: createLiteral({ value: 'C' }) })),
          ],
        },
      ],
    }

    const normalized = normalizeSelectedNode(nestedSeq, nestedSeq.id)
    expect(normalized?.type).toBe('seq')
    expect(generateBuilderQuery(normalized!)).toBe('[word="A"] [word="B"] [word="C"]')
  })

  it('duplicates a selected meta expression as a fresh sibling copy', () => {
    const source = createMetaCond({ field: 'source', op: '=', value: createLiteral({ value: 'mlsum' }) })
    const year = createMetaCond({ field: 'year', op: '>=', value: createLiteral({ kind: 'number', value: '2024' }) })
    const root: CqlBuilderNode = {
      id: crypto.randomUUID(),
      type: 'where',
      expr: createMetaGroup('and', { parts: [source, year] }),
      node: tok(createTokenCondition({ attr: 'lemma', op: '=', scalar: createLiteral({ value: 'Hase' }) })),
    }

    const duplicate = duplicateMetaSibling(root, source.id)
    expect(duplicate).not.toBeNull()
    expect(duplicate?.id).not.toBe(source.id)
    expect(generateBuilderQuery(root)).toBe('where(source="mlsum" & source="mlsum" & year>=2024, [lemma="Hase"])')
  })

  it('normalizes nested meta groups of the same kind', () => {
    const nested = createMetaGroup('and', {
      parts: [
        createMetaCond({ field: 'source', op: '=', value: createLiteral({ value: 'mlsum' }) }),
        createMetaGroup('and', {
          parts: [
            createMetaCond({ field: 'genre', op: '=', value: createLiteral({ value: 'news' }) }),
            createMetaCond({ field: 'year', op: '>=', value: createLiteral({ kind: 'number', value: '2024' }) }),
          ],
        }),
      ],
    })
    const root: CqlBuilderNode = {
      id: crypto.randomUUID(),
      type: 'where',
      expr: nested,
      node: tok(createTokenCondition({ attr: 'lemma', op: '=', scalar: createLiteral({ value: 'Hase' }) })),
    }

    const normalized = normalizeSelectedMetaExpr(root, nested.id)
    expect(normalized?.kind).toBe('and')
    expect(generateBuilderQuery(root)).toBe('where(source="mlsum" & genre="news" & year>=2024, [lemma="Hase"])')
  })

  it('extracts a query node from its sibling block and leaves the remaining structure valid', () => {
    const first = tok(createTokenCondition({ attr: 'lemma', op: '=', scalar: createLiteral({ value: 'Haus' }) }))
    const second = tok(createTokenCondition({ attr: 'word', op: '=', scalar: createLiteral({ value: 'Baum' }) }))
    const root: CqlBuilderNode = {
      id: crypto.randomUUID(),
      type: 'seq',
      parts: [first, second],
    }

    const extracted = extractNodeSibling(root, first.id)
    expect(extracted?.id).toBe(first.id)
    expect(generateBuilderQuery(root)).toBe('[word="Baum"]')
  })

  it('reinserts a parked query node next to a different sibling with fresh ids', () => {
    const first = tok(createTokenCondition({ attr: 'word', op: '=', scalar: createLiteral({ value: 'A' }) }))
    const second = tok(createTokenCondition({ attr: 'word', op: '=', scalar: createLiteral({ value: 'B' }) }))
    const parked = tok(createTokenCondition({ attr: 'word', op: '=', scalar: createLiteral({ value: 'X' }) }))
    const root: CqlBuilderNode = {
      id: crypto.randomUUID(),
      type: 'seq',
      parts: [first, second],
    }

    const inserted = insertNodeSibling(root, second.id, parked, 'before')
    expect(inserted).not.toBeNull()
    expect(inserted?.id).not.toBe(parked.id)
    expect(generateBuilderQuery(root)).toBe('[word="A"] [word="X"] [word="B"]')
  })

  it('extracts a meta expression from its boolean group and keeps the group editable', () => {
    const source = createMetaCond({ field: 'source', op: '=', value: createLiteral({ value: 'mlsum' }) })
    const year = createMetaCond({ field: 'year', op: '>=', value: createLiteral({ kind: 'number', value: '2024' }) })
    const root: CqlBuilderNode = {
      id: crypto.randomUUID(),
      type: 'where',
      expr: createMetaGroup('and', { parts: [source, year] }),
      node: tok(createTokenCondition({ attr: 'lemma', op: '=', scalar: createLiteral({ value: 'Hase' }) })),
    }

    const extracted = extractMetaSibling(root, source.id)
    expect(extracted?.id).toBe(source.id)
    expect(generateBuilderQuery(root)).toBe('where(year>=2024, [lemma="Hase"])')
  })

  it('reinserts a parked meta expression into another boolean block with fresh ids', () => {
    const source = createMetaCond({ field: 'source', op: '=', value: createLiteral({ value: 'mlsum' }) })
    const year = createMetaCond({ field: 'year', op: '>=', value: createLiteral({ kind: 'number', value: '2024' }) })
    const parked = createMetaCond({ field: 'genre', op: '=', value: createLiteral({ value: 'news' }) })
    const root: CqlBuilderNode = {
      id: crypto.randomUUID(),
      type: 'where',
      expr: createMetaGroup('and', { parts: [source, year] }),
      node: tok(createTokenCondition({ attr: 'lemma', op: '=', scalar: createLiteral({ value: 'Hase' }) })),
    }

    const inserted = insertMetaSibling(root, year.id, parked, 'after')
    expect(inserted).not.toBeNull()
    expect(inserted?.id).not.toBe(parked.id)
    expect(generateBuilderQuery(root)).toBe('where(source="mlsum" & year>=2024 & genre="news", [lemma="Hase"])')
  })

  it('collects literal targets from query fragments including sets and where-metadata', () => {
    const root: CqlBuilderNode = {
      id: crypto.randomUUID(),
      type: 'where',
      expr: createMetaGroup('and', {
        parts: [
          createMetaCond({ field: 'source', op: '=', value: createLiteral({ value: 'mlsum' }) }),
        ],
      }),
      node: {
        id: crypto.randomUUID(),
        type: 'seq',
        parts: [
          tok(createTokenCondition({ attr: 'lemma', op: '=', scalar: createLiteral({ value: 'Hase' }) })),
          tok(createTokenCondition({
            attr: 'pos',
            op: 'in',
            setValues: [createLiteral({ value: 'NN' }), createLiteral({ value: 'NE' })],
          })),
        ],
      },
    }

    const targets = collectNodeLiteralTargets(root)
    expect(targets.map((target) => `${target.scope}:${target.label}`)).toEqual([
      'meta:source',
      'token:lemma',
      'token:pos[1]',
      'token:pos[2]',
    ])
    expect(targets.map((target) => target.currentValue)).toEqual(['mlsum', 'Hase', 'NN', 'NE'])
  })

  it('applies literal overrides to query fragments without mutating the original snippet', () => {
    const source = createMetaCond({ field: 'source', op: '=', value: createLiteral({ value: 'mlsum' }) })
    const lemma = createTokenCondition({ attr: 'lemma', op: '=', scalar: createLiteral({ value: 'Hase' }) })
    const root: CqlBuilderNode = {
      id: crypto.randomUUID(),
      type: 'where',
      expr: createMetaGroup('and', { parts: [source] }),
      node: tok(lemma),
    }

    const [metaTarget, nodeTarget] = collectNodeLiteralTargets(root)
    const next = applyNodeLiteralOverrides(root, {
      [metaTarget!.literalId]: { kind: 'string', value: 'zeit' },
      [nodeTarget!.literalId]: { kind: 'string', value: 'Fuchs' },
    })

    expect(generateBuilderQuery(root)).toBe('where(source="mlsum", [lemma="Hase"])')
    expect(generateBuilderQuery(next)).toBe('where(source="zeit", [lemma="Fuchs"])')
  })

  it('collects and applies literal overrides to standalone meta fragments', () => {
    const expr = createMetaGroup('or', {
      parts: [
        createMetaCond({ field: 'year', op: '>=', value: createLiteral({ kind: 'number', value: '2024' }) }),
        createMetaCond({ field: 'genre', op: '=', value: createLiteral({ value: 'news' }) }),
      ],
    })

    const targets = collectMetaLiteralTargets(expr)
    const next = applyMetaLiteralOverrides(expr, {
      [targets[0]!.literalId]: { kind: 'number', value: '2025' },
      [targets[1]!.literalId]: { kind: 'string', value: 'essay' },
    })

    expect(generateBuilderQuery({ id: crypto.randomUUID(), type: 'where', expr, node: tok(createTokenCondition()) })).toContain('year>=2024 | genre="news"')
    expect(generateBuilderQuery({ id: crypto.randomUUID(), type: 'where', expr: next, node: tok(createTokenCondition()) })).toContain('year>=2025 | genre="essay"')
  })

  it('ungroups a nested sequence inside a sequence parent', () => {
    const nested: CqlBuilderNode = {
      id: crypto.randomUUID(),
      type: 'seq',
      parts: [
        tok(createTokenCondition({ attr: 'word', op: '=', scalar: createLiteral({ value: 'A' }) })),
        tok(createTokenCondition({ attr: 'word', op: '=', scalar: createLiteral({ value: 'B' }) })),
      ],
    }
    const root: CqlBuilderNode = {
      id: crypto.randomUUID(),
      type: 'seq',
      parts: [
        nested,
        tok(createTokenCondition({ attr: 'word', op: '=', scalar: createLiteral({ value: 'C' }) })),
      ],
    }

    const ungrouped = ungroupNodeSibling(root, nested.id)
    expect(ungrouped).toHaveLength(2)
    expect(generateBuilderQuery(root)).toBe('[word="A"] [word="B"] [word="C"]')
  })

  it('ungroups a nested OR group inside an OR parent', () => {
    const nested = createMetaGroup('or', {
      parts: [
        createMetaCond({ field: 'source', op: '=', value: createLiteral({ value: 'mlsum' }) }),
        createMetaCond({ field: 'genre', op: '=', value: createLiteral({ value: 'news' }) }),
      ],
    })
    const root: CqlBuilderNode = {
      id: crypto.randomUUID(),
      type: 'where',
      expr: createMetaGroup('or', {
        parts: [
          nested,
          createMetaCond({ field: 'year', op: '>=', value: createLiteral({ kind: 'number', value: '2024' }) }),
        ],
      }),
      node: tok(createTokenCondition({ attr: 'lemma', op: '=', scalar: createLiteral({ value: 'Hase' }) })),
    }

    const ungrouped = ungroupMetaSibling(root, nested.id)
    expect(ungrouped).toHaveLength(2)
    expect(generateBuilderQuery(root)).toBe('where(source="mlsum" | genre="news" | year>=2024, [lemma="Hase"])')
  })
})
