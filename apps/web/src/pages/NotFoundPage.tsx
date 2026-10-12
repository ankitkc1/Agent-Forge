import { EmptyState } from '@/components/Feedback';
import { Link } from '@/components/Link';

export function NotFoundPage({ path }: { path: string }) {
  return (
    <div className="page">
      <EmptyState
        icon="search"
        title="Nothing lives at this address"
        action={
          <Link to="/" className="button button-primary">
            Start a new agent
          </Link>
        }
      >
        <code>{path}</code> is not a page in the workbench.
      </EmptyState>
    </div>
  );
}
