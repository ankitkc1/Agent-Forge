import { useMemo, useState } from 'react';
import { ApiError } from '@/api/client';
import { CodeView } from '@/components/CodeView';
import { CopyButton, EmptyState, ErrorNotice, Notice, Skeleton } from '@/components/Feedback';
import { Icon } from '@/components/Icon';
import { useFile, useFiles } from '@/hooks/queries';
import { formatBytes, repositoryName, shortHash } from '@/lib/format';
import { ancestors, buildTree, languageLabel, type TreeNode } from '@/lib/report';
import { buildPath, navigate } from '@/router';
import type { Build } from '@/types';

function Branch({
  node,
  depth,
  expanded,
  selected,
  onToggle,
  onSelect,
}: {
  node: TreeNode;
  depth: number;
  expanded: Set<string>;
  selected: string | null;
  onToggle: (path: string) => void;
  onSelect: (path: string) => void;
}) {
  return (
    <ul className="tree-level" role={depth === 0 ? 'tree' : 'group'} aria-label={depth === 0 ? 'Repository files' : undefined}>
      {node.children.map(child => {
        const isFolder = child.file === null;
        const open = expanded.has(child.path);
        return (
          <li key={child.path} role="treeitem" aria-expanded={isFolder ? open : undefined} aria-selected={!isFolder ? child.path === selected : undefined}>
            <button
              type="button"
              className={`tree-row ${!isFolder && child.path === selected ? 'is-selected' : ''} ${child.file?.evidence ? 'is-evidence' : ''}`}
              style={{ paddingLeft: `${0.5 + depth * 0.9}rem` }}
              onClick={() => (isFolder ? onToggle(child.path) : onSelect(child.path))}
            >
              <Icon name={isFolder ? 'folder' : 'file'} />
              <span>{child.name}</span>
              {child.file ? <small>{formatBytes(child.file.size)}</small> : null}
            </button>
            {isFolder && open ? <Branch node={child} depth={depth + 1} expanded={expanded} selected={selected} onToggle={onToggle} onSelect={onSelect} /> : null}
          </li>
        );
      })}
    </ul>
  );
}

function Viewer({ buildId, path, sha256 }: { buildId: string; path: string; sha256: string | null }) {
  const file = useFile(buildId, path);
  if (file.isPending) return <Skeleton lines={8} />;
  if (file.error) {
    if (file.error instanceof ApiError && file.error.status === 415) {
      return <Notice title="Binary file">This file cannot be previewed. Download the source archive to inspect it.</Notice>;
    }
    return <ErrorNotice error={file.error} title={`${path} could not be opened`} onRetry={() => void file.refetch()} />;
  }
  const content = file.data;
  return (
    <div className="viewer">
      <div className="viewer-bar">
        <code>{path}</code>
        <span>
          {languageLabel(content.language)}, {formatBytes(content.size)}
          {sha256 ? `, sha256 ${shortHash(sha256)}` : ''}
        </span>
        <CopyButton value={content.content} label="Copy" />
      </div>
      {content.truncated ? <Notice tone="warn" title="Preview truncated">Only the first 500 KB are shown.</Notice> : null}
      <CodeView content={content.content} label={path} />
    </div>
  );
}

export function FilesTab({ build, selected }: { build: Build; selected: string | null }) {
  const files = useFiles(build.id, build.artifact_ready);
  const tree = useMemo(() => buildTree(files.data ?? []), [files.data]);
  const fallback = files.data?.find(entry => entry.path === 'README.md')?.path ?? files.data?.[0]?.path ?? null;
  const current = selected && files.data?.some(entry => entry.path === selected) ? selected : fallback;
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(['src', 'src/agent', ...(selected ? ancestors(selected) : [])]));

  if (!build.artifact_ready) {
    return (
      <EmptyState icon="folder" title="No packaged files">
        {build.status === 'succeeded'
          ? 'The artifact has been removed by the retention policy.'
          : 'Files become browsable once every gate has passed and the repository is signed and packaged.'}
      </EmptyState>
    );
  }
  if (files.isPending) return <Skeleton lines={8} />;
  if (files.error) return <ErrorNotice error={files.error} title="The file list could not be loaded" onRetry={() => void files.refetch()} />;

  const toggle = (path: string) =>
    setExpanded(previous => {
      const next = new Set(previous);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  const select = (path: string) => navigate(buildPath(build.id, 'files', path), { replace: true });
  const entry = files.data.find(item => item.path === current);

  return (
    <div className="files">
      <aside className="panel tree">
        <div className="tree-head">
          <strong>{repositoryName(build.agent_name)}/</strong>
          <span>{files.data.length} files</span>
        </div>
        <Branch node={tree} depth={0} expanded={expanded} selected={current} onToggle={toggle} onSelect={select} />
        <p className="help">
          Files under <code>.agentforge/</code> are build evidence: reports, SBOM, provenance and the signed manifest.
        </p>
      </aside>
      <section className="panel">{current ? <Viewer key={current} buildId={build.id} path={current} sha256={entry?.sha256 ?? null} /> : null}</section>
    </div>
  );
}
