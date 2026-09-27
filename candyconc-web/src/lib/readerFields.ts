/**
 * Which metadata a reader shows for a document, taken from the fields of the
 * corpus and not from a fixed list of field names.
 *
 * When the server names reader fields (`reader_fields` of /docs/list), they
 * decide: `title_field` heads the text, `label_fields` label it, in their
 * order. Without them (older servers) a field is shown when it tells
 * documents apart: more than one value in the corpus (the value counts of
 * the metadata schema), no document identifier. Values then keep the field
 * order of the document, and only `title`, a common metadata convention, is
 * read by name.
 */
import type { ReaderFields } from '@/api/client'
import { isIdentityField } from '@/stores/docset'

type Meta = Record<string, unknown>
type ValueCounts = Record<string, number | null | undefined>

const TITLE_FIELD = 'title'
/** Longer values (abstracts, notes) belong in the metadata block, not in a line. */
const MAX_LINE_VALUE_LENGTH = 80

function textOf(value: unknown): string {
  return value === null || value === undefined ? '' : String(value).trim()
}

function isTitleField(field: string): boolean {
  return field.toLowerCase() === TITLE_FIELD
}

/** Without a known value count every field counts as distinguishing. */
export function distinguishesDocuments(field: string, valueCounts: ValueCounts): boolean {
  const count = valueCounts[field]
  return typeof count === 'number' ? count > 1 : true
}

function lineValues(meta: Meta, valueCounts: ValueCounts, readerFields?: ReaderFields | null): Array<[string, string]> {
  const entries: Array<[string, unknown]> = readerFields
    ? readerFields.label_fields.map((field) => [field, meta[field]])
    : Object.entries(meta).filter(([field]) =>
      !isTitleField(field) && !isIdentityField(field) && distinguishesDocuments(field, valueCounts))
  return entries
    .map(([field, value]) => [field, textOf(value)] as [string, string])
    .filter(([, value]) => value !== '' && value.length <= MAX_LINE_VALUE_LENGTH)
}

/** The heading of a document: its title field, else the label the server gives it. */
export function documentHeading(
  meta: Meta,
  docLabel: string | null | undefined,
  readerFields?: ReaderFields | null,
): string {
  const titleKey = readerFields ? readerFields.title_field : Object.keys(meta).find(isTitleField)
  return (titleKey ? textOf(meta[titleKey]) : '') || textOf(docLabel)
}

/** The line under the heading: values of the distinguishing fields. */
export function documentSubline(
  meta: Meta,
  valueCounts: ValueCounts,
  readerFields?: ReaderFields | null,
  limit = 5,
): string[] {
  return lineValues(meta, valueCounts, readerFields).slice(0, limit).map(([, value]) => value)
}

/**
 * A list row: the document label, then the distinguishing fields the row
 * carries. A value equal to the label is left out.
 */
export function documentRowLabel(
  docLabel: string | null | undefined,
  meta: Meta,
  valueCounts: ValueCounts,
  readerFields?: ReaderFields | null,
  limit = 3,
): string {
  const label = textOf(docLabel)
  const values = lineValues(meta, valueCounts, readerFields)
    .map(([, value]) => value)
    .filter((value) => value !== label)
    .slice(0, limit)
  return [label, ...values].filter(Boolean).join(' · ')
}
