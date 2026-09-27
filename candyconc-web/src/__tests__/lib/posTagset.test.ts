import { describe, expect, it } from 'vitest'

import { detectPosTagset, examplePosTag, isDescribedPosTag, posTagGroup } from '@/lib/posTagset'

describe('posTagset', () => {
  it('recognises Universal POS, including the blank pipeline that only writes X', () => {
    expect(detectPosTagset(['NOUN', 'PUNCT', 'VERB', 'SPACE'])).toBe('upos')
    expect(detectPosTagset(['X'])).toBe('upos')
  })

  it('recognises STTS with its punctuation tags', () => {
    expect(detectPosTagset(['NN', '$.', 'VVFIN', '$,', 'ART'])).toBe('stts')
  })

  it('recognises no tagset for other or mixed tag lists', () => {
    expect(detectPosTagset([])).toBeNull()
    expect(detectPosTagset(['NN', 'IN', 'DT'])).toBeNull()
    expect(detectPosTagset(['NOUN', 'NN'])).toBeNull()
  })

  it('describes and groups only tags of the recognised tagset', () => {
    expect(isDescribedPosTag('NOUN', 'upos')).toBe(true)
    expect(isDescribedPosTag('NN', 'upos')).toBe(false)
    expect(isDescribedPosTag('$.', 'stts')).toBe(false)
    expect(isDescribedPosTag('NN', null)).toBe(false)
    expect(posTagGroup('PROPN', 'upos')).toBe('nominal')
    expect(posTagGroup('AUX', 'upos')).toBe('verbal')
    expect(posTagGroup('ADP', 'upos')).toBe('prep')
    expect(posTagGroup('NN', 'stts')).toBe('nominal')
    expect(posTagGroup('NN', null)).toBe('other')
  })

  it('picks an example tag the corpus has', () => {
    expect(examplePosTag(['PUNCT', 'NOUN', 'VERB'], 'upos')).toBe('NOUN')
    expect(examplePosTag(['$.', 'NN'], 'stts')).toBe('NN')
    expect(examplePosTag(['PUNCT', 'X'], 'upos')).toBe('X')
    expect(examplePosTag([',', 'IN', 'NN'], null)).toBe('IN')
    expect(examplePosTag([], null)).toBeNull()
  })
})
