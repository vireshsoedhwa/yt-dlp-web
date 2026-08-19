/**
 * ErrorMessage — simple inline error banner.
 */

interface ErrorMessageProps {
  message: string;
  onDismiss?: () => void;
}

export function ErrorMessage({ message, onDismiss }: ErrorMessageProps) {
  return (
    <div className="bg-red-900/50 border border-red-700 rounded-lg px-4 py-3 flex items-start justify-between gap-2">
      <p className="text-sm text-red-200">{message}</p>
      {onDismiss && (
        <button
          onClick={onDismiss}
          className="text-red-400 hover:text-red-200 text-sm"
          aria-label="Dismiss error"
        >
          ✕
        </button>
      )}
    </div>
  );
}