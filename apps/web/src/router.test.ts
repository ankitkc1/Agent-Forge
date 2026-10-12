import { describe, expect, it } from 'vitest';
import { buildPath, parseRoute } from './router';

const ID = '7359162b-7fe2-494c-affa-9f634f6a6208';

describe('parseRoute', () => {
  it('maps every screen', () => {
    expect(parseRoute('/')).toEqual({ name: 'compose', template: null });
    expect(parseRoute('/new', '?template=customer-support')).toEqual({ name: 'compose', template: 'customer-support' });
    expect(parseRoute('/builds/')).toEqual({ name: 'builds' });
    expect(parseRoute('/templates')).toEqual({ name: 'templates' });
    expect(parseRoute('/system')).toEqual({ name: 'system' });
  });

  it('parses build tabs and selected files', () => {
    expect(parseRoute(`/builds/${ID}`)).toEqual({ name: 'build', id: ID, tab: 'overview', file: null });
    expect(parseRoute(`/builds/${ID.toUpperCase()}`, '?tab=files&file=src%2Fagent%2Fgraph.py')).toEqual({
      name: 'build',
      id: ID,
      tab: 'files',
      file: 'src/agent/graph.py',
    });
    expect(parseRoute(`/builds/${ID}`, '?tab=unknown')).toMatchObject({ tab: 'overview' });
  });

  it('rejects malformed paths', () => {
    expect(parseRoute('/builds/../../etc')).toMatchObject({ name: 'not-found' });
    expect(parseRoute('/builds/<script>')).toMatchObject({ name: 'not-found' });
    expect(parseRoute('/nope')).toEqual({ name: 'not-found', path: '/nope' });
  });
});

describe('buildPath', () => {
  it('omits the default tab and encodes files', () => {
    expect(buildPath(ID)).toBe(`/builds/${ID}`);
    expect(buildPath(ID, 'files', 'src/agent/graph.py')).toBe(`/builds/${ID}?tab=files&file=src%2Fagent%2Fgraph.py`);
    expect(parseRoute(`/builds/${ID}`, buildPath(ID, 'files', 'a b.py').split('?')[1])).toMatchObject({ file: 'a b.py' });
  });
});
