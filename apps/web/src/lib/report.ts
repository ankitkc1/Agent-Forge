import type { FileEntry, TestCaseResult } from '@/types';

export function groupByFile(cases: TestCaseResult[]): Array<{ file: string; cases: TestCaseResult[] }> {
  const groups = new Map<string, TestCaseResult[]>();
  for (const testCase of cases) {
    const separator = testCase.id.indexOf('::');
    const file = separator === -1 ? '(other)' : testCase.id.slice(0, separator);
    const group = groups.get(file);
    if (group) group.push(testCase);
    else groups.set(file, [testCase]);
  }
  return [...groups.entries()].map(([file, items]) => ({ file, cases: items }));
}

export interface TreeNode {
  name: string;
  path: string;
  children: TreeNode[];
  file: FileEntry | null;
}

/** Folders first, then files, each alphabetical — the order developers expect from an editor. */
export function buildTree(entries: FileEntry[]): TreeNode {
  const root: TreeNode = { name: '', path: '', children: [], file: null };
  for (const entry of entries) {
    const parts = entry.path.split('/').filter(Boolean);
    let node = root;
    parts.forEach((part, index) => {
      const path = parts.slice(0, index + 1).join('/');
      let child = node.children.find(item => item.name === part);
      if (!child) {
        child = { name: part, path, children: [], file: null };
        node.children.push(child);
      }
      if (index === parts.length - 1) child.file = entry;
      node = child;
    });
  }
  const sort = (node: TreeNode) => {
    node.children.sort((a, b) => Number(Boolean(a.file)) - Number(Boolean(b.file)) || a.name.localeCompare(b.name));
    node.children.forEach(sort);
  };
  sort(root);
  return root;
}

export function ancestors(path: string): string[] {
  const parts = path.split('/');
  return parts.slice(0, -1).map((_, index) => parts.slice(0, index + 1).join('/'));
}

const LANGUAGE_LABELS: Record<string, string> = {
  python: 'Python',
  yaml: 'YAML',
  json: 'JSON',
  markdown: 'Markdown',
  toml: 'TOML',
  dockerfile: 'Dockerfile',
  text: 'Text',
  xml: 'XML',
  shell: 'Shell',
  makefile: 'Makefile',
  ini: 'INI',
  jinja: 'Jinja',
  html: 'HTML',
  dotenv: 'Environment',
};

export function languageLabel(language: string): string {
  return LANGUAGE_LABELS[language] ?? language;
}
