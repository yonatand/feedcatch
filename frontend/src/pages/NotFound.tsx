import { Link } from 'react-router-dom';
import { EmptyState } from '../components/Table';

export default function NotFound() {
  return (
    <EmptyState title="Page not found">
      <Link to="/">Back to the dashboard</Link>
    </EmptyState>
  );
}
