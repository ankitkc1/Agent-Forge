import { describe, expect, it, vi } from 'vitest';
import { readEventStream, SseParser, type SseMessage } from './sse';

describe('SseParser', () => {
  it('parses named events, multi-line data, ids and comments', () => {
    const parser = new SseParser();
    const messages = parser.feed(': keep-alive\n\nevent: build\nid: 7\ndata: {"a":\ndata: 1}\n\ndata: plain\n\n');
    expect(messages).toEqual([
      { event: 'build', data: '{"a":\n1}', id: '7' },
      { event: 'message', data: 'plain', id: '7' },
    ]);
  });

  it('handles CRLF and chunks split anywhere, including inside a line ending', () => {
    const parser = new SseParser();
    const stream = 'event: log\r\ndata: {"id": 1}\r\n\r\nevent: end\r\ndata: {}\r\n\r\n';
    const received: SseMessage[] = [];
    for (const piece of stream.match(/.{1,3}/gs) ?? []) received.push(...parser.feed(piece));
    expect(received.map(message => message.event)).toEqual(['log', 'end']);
    expect(received[0]?.data).toBe('{"id": 1}');
  });

  it('ignores events without data and strips one leading space only', () => {
    const parser = new SseParser();
    expect(parser.feed('event: ping\n\ndata:  two spaces\n\n')).toEqual([{ event: 'message', data: ' two spaces', id: null }]);
  });
});

describe('readEventStream', () => {
  it('reads a streamed response and sends headers', async () => {
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('event: build\ndata: {"status":"running"}\n'));
        controller.enqueue(encoder.encode('\nevent: end\ndata: {}\n\n'));
        controller.close();
      },
    });
    const fetchImpl = vi.fn().mockResolvedValue(new Response(body, { status: 200 }));
    const events: string[] = [];
    await readEventStream('/stream', { signal: new AbortController().signal, headers: { Authorization: 'Bearer k' }, onMessage: message => events.push(message.event), fetchImpl });
    expect(events).toEqual(['build', 'end']);
    const init = (fetchImpl.mock.calls[0] as [string, RequestInit])[1];
    expect(init.headers).toMatchObject({ Accept: 'text/event-stream', Authorization: 'Bearer k' });
  });

  it('rejects when the stream is unavailable', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response('nope', { status: 503 }));
    await expect(readEventStream('/stream', { signal: new AbortController().signal, onMessage: () => undefined, fetchImpl })).rejects.toThrow('HTTP 503');
  });
});
