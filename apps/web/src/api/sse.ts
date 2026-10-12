// Server-sent events over fetch. EventSource cannot send an Authorization header, so the
// workbench reads the stream itself and parses it according to the HTML specification.

export interface SseMessage {
  event: string;
  data: string;
  id: string | null;
}

export class SseParser {
  private buffer = '';
  private data: string[] = [];
  private event = '';
  private lastId: string | null = null;

  /** Feed a decoded chunk; returns every message completed by it. */
  feed(chunk: string): SseMessage[] {
    this.buffer += chunk;
    const messages: SseMessage[] = [];
    let newline: RegExpExecArray | null;
    const pattern = /\r\n|\r|\n/;
    while ((newline = pattern.exec(this.buffer)) !== null) {
      // A lone trailing "\r" may be the first half of "\r\n"; wait for more input.
      if (newline[0] === '\r' && newline.index === this.buffer.length - 1) break;
      const line = this.buffer.slice(0, newline.index);
      this.buffer = this.buffer.slice(newline.index + newline[0].length);
      const message = this.line(line);
      if (message) messages.push(message);
    }
    return messages;
  }

  private line(line: string): SseMessage | null {
    if (line === '') {
      if (this.data.length === 0) {
        this.event = '';
        return null;
      }
      const message = { event: this.event || 'message', data: this.data.join('\n'), id: this.lastId };
      this.data = [];
      this.event = '';
      return message;
    }
    if (line.startsWith(':')) return null;
    const colon = line.indexOf(':');
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? '' : line.slice(colon + 1);
    if (value.startsWith(' ')) value = value.slice(1);
    if (field === 'data') this.data.push(value);
    else if (field === 'event') this.event = value;
    else if (field === 'id' && !value.includes('\0')) this.lastId = value;
    return null;
  }
}

export interface StreamOptions {
  headers?: Record<string, string>;
  signal: AbortSignal;
  onMessage: (message: SseMessage) => void;
  fetchImpl?: typeof fetch;
}

/** Resolves when the server closes the stream; rejects on HTTP or network errors. */
export async function readEventStream(url: string, options: StreamOptions): Promise<void> {
  const fetcher = options.fetchImpl ?? fetch;
  const response = await fetcher(url, {
    headers: { Accept: 'text/event-stream', ...options.headers },
    signal: options.signal,
    cache: 'no-store',
  });
  if (!response.ok || !response.body) {
    throw new Error(`event stream unavailable (HTTP ${response.status})`);
  }
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  const parser = new SseParser();
  for (;;) {
    const { done, value } = await reader.read();
    if (done) return;
    for (const message of parser.feed(value)) options.onMessage(message);
  }
}
