import { api } from '@/api/client';
import { CodeView } from '@/components/CodeView';
import { CopyButton, EmptyState } from '@/components/Feedback';
import { artifactFileName, formatBytes, formatInteger } from '@/lib/format';
import type { Build, BuildReport } from '@/types';

function Fact({ label, value, copy }: { label: string; value: string | null | undefined; copy?: boolean }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>
        {value ? <code className="wrap">{value}</code> : '—'}
        {copy && value ? <CopyButton value={value} label="Copy" className="button button-quiet button-small" /> : null}
      </dd>
    </div>
  );
}

export function ProvenanceTab({ build, report }: { build: Build; report: Partial<BuildReport> | undefined }) {
  const pkg = report?.package;
  if (!pkg) {
    return (
      <EmptyState icon="seal" title="Not packaged">
        {build.status === 'failed' || build.status === 'cancelled'
          ? 'Only builds that pass every gate are packaged, signed and given provenance.'
          : 'Provenance is recorded when the verified repository is packaged.'}
      </EmptyState>
    );
  }
  const archive = artifactFileName(build.agent_name, build.id);
  const origin = window.location.origin;
  const verify = [
    `# 1. Check the archive digest`,
    `sha256sum ${archive}   # expect ${pkg.archive_sha256}`,
    ``,
    ...(pkg.signature?.signed
      ? [
          `# 2. Fetch this AgentForge instance's public key`,
          `curl -fsS ${origin}${api.signingKeyUrl()} -o agentforge-signing-key.pub`,
          ``,
          `# 3. Verify every file against the signed manifest`,
          `agentforge verify-artifact ${archive} --public-key agentforge-signing-key.pub`,
        ]
      : [`# 2. Verify every file against the manifest`, `agentforge verify-artifact ${archive}`]),
  ].join('\n');

  return (
    <div className="stack">
      <div className="split">
        <section className="panel">
          <h3>Artifact</h3>
          <dl className="facts facts-wide">
            <Fact label="Archive SHA-256" value={pkg.archive_sha256} copy />
            <Fact label="Source digest" value={pkg.source_digest} copy />
            <Fact label="Specification SHA-256" value={build.spec_hash} copy />
            <div>
              <dt>Size</dt>
              <dd>
                {formatBytes(pkg.size_bytes)}, {formatInteger(pkg.files)} files
              </dd>
            </div>
          </dl>
        </section>
        <section className="panel">
          <h3>Build</h3>
          <dl className="facts facts-wide">
            <Fact label="Signature" value={pkg.signature?.signed ? pkg.signature.key_id : 'Unsigned (no signing key configured)'} />
            <Fact label="AgentForge" value={report?.agentforge_version ?? build.agentforge_version} />
            <Fact label="Sandbox" value={report?.sandbox} />
            <div>
              <dt>SBOM</dt>
              <dd>CycloneDX 1.6, {formatInteger(pkg.sbom_components)} locked components</dd>
            </div>
            <div>
              <dt>Provenance</dt>
              <dd>in-toto statement with a SLSA v1 predicate</dd>
            </div>
          </dl>
        </section>
      </div>
      <section className="panel">
        <div className="section-title">
          <h3>Verify the download</h3>
          <CopyButton value={verify} label="Copy commands" />
        </div>
        <p className="help">
          The evidence lives inside the archive under <code>.agentforge/</code>: MANIFEST.sha256 lists every file, sbom.cdx.json and provenance.json describe what was
          built and how.
        </p>
        <CodeView content={verify} label="Verification commands" />
      </section>
    </div>
  );
}
