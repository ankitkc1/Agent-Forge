import { ErrorNotice, Skeleton } from '@/components/Feedback';
import { Link } from '@/components/Link';
import { useTemplates } from '@/hooks/queries';
import { humanize } from '@/lib/format';

export function TemplatesPage() {
  const templates = useTemplates();
  return (
    <div className="page">
      <header className="page-head">
        <h1>Templates</h1>
        <p>Worked requirements for common operations agents. Each one compiles deterministically, so you can see exactly what changes when you edit the wording.</p>
      </header>
      {templates.error ? <ErrorNotice error={templates.error} title="Templates could not be loaded" onRetry={() => void templates.refetch()} /> : null}
      {templates.isPending ? (
        <Skeleton lines={6} />
      ) : (
        <ul className="template-grid">
          {templates.data?.map(template => (
            <li key={template.id} className="panel template">
              <span className="template-domain">{humanize(template.domain)}</span>
              <h2>{template.title}</h2>
              <p>{template.summary}</p>
              <blockquote>{template.requirement}</blockquote>
              <Link to={`/?template=${encodeURIComponent(template.id)}`} className="button button-quiet">
                Use this requirement
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
