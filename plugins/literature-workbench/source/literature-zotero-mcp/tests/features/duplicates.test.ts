import { describe, expect, it } from 'vitest';
import { findDuplicateClusters } from '../../src/features/duplicates/detector.js';

function item(key: string, data: Record<string, unknown>, meta: Record<string, unknown> = {}) {
  return { key, version: 1, data: { itemType: 'journalArticle', ...data }, meta };
}

describe('duplicate detector', () => {
  it.each([
    ['DOI', '10.1000/Test', 'https://doi.org/10.1000/test', 'same-doi'],
    ['extra', 'PMID: 12345678', 'PMID: 12345678', 'same-pmid'],
    ['ISBN', '978-1-4028-9462-6', '9781402894626', 'same-isbn'],
  ])('creates a high-confidence cluster for matching %s', (field, a, b, reason) => {
    const result = findDuplicateClusters(
      [item('BATCH001', { title: 'First record', [field]: a })],
      [
        item('BATCH001', { title: 'First record', [field]: a }),
        item('LIB00001', { title: 'Second record', [field]: b }),
      ],
    );

    expect(result).toHaveLength(1);
    expect(result[0].confidence).toBe('high');
    expect(result[0].reasons).toContain(reason);
  });

  it('creates a medium-confidence cluster for similar title, matching author, and adjacent year', () => {
    const batch = item('BATCH001', {
      title: 'Deep learning for protein structure prediction',
      date: '2024',
      creators: [{ creatorType: 'author', firstName: 'Jane', lastName: 'Smith' }],
    });
    const existing = item('LIB00001', {
      title: 'Deep Learning for Protein-Structure Prediction',
      date: '2023',
      creators: [{ creatorType: 'author', firstName: 'J.', lastName: 'Smith' }],
    });

    const result = findDuplicateClusters([batch], [batch, existing]);

    expect(result).toHaveLength(1);
    expect(result[0].confidence).toBe('medium');
    expect(result[0].reasons).toContain('title-author-year');
  });

  it('does not group records with conflicting DOIs or incompatible item types', () => {
    const batch = item('BATCH001', { title: 'The same title', DOI: '10.1/a', date: '2024' });
    const conflictingDoi = item('LIB00001', {
      title: 'The same title',
      DOI: '10.1/b',
      date: '2024',
    });
    const incompatible = item('LIB00002', {
      itemType: 'book',
      title: 'The same title',
      date: '2024',
    });

    expect(findDuplicateClusters([batch], [batch, conflictingDoi, incompatible])).toEqual([]);
  });

  it('does not group correction or retraction records with the original article by title similarity', () => {
    const batch = item('BATCH001', { title: 'Protein folding with neural networks', date: '2024' });
    const correction = item('LIB00001', {
      title: 'Correction: Protein folding with neural networks',
      date: '2024',
    });

    expect(findDuplicateClusters([batch], [batch, correction])).toEqual([]);
  });

  it('recommends the richer record as master deterministically', () => {
    const sparse = item('BATCH001', { title: 'A useful paper', DOI: '10.1/a' });
    const rich = item(
      'LIB00001',
      {
        title: 'A useful paper',
        DOI: '10.1/a',
        abstractNote: 'Detailed abstract',
        publicationTitle: 'Journal',
        creators: [{ creatorType: 'author', firstName: 'A', lastName: 'Author' }],
        tags: [{ tag: 'project:test' }],
        collections: ['COLL0001'],
      },
      { numChildren: 2 },
    );

    const [cluster] = findDuplicateClusters([sparse], [sparse, rich]);

    expect(cluster.recommended_master_key).toBe('LIB00001');
    expect(cluster.master_reason).toMatch(/metadata|child|collection|tag/i);
    expect(cluster.native_merge_required).toBe(true);
  });
});
