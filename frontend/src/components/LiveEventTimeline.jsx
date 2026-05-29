import React from 'react';


function summarizeEvent(event) {
  if (!event || typeof event !== 'object') {
    return '';
  }

  const detail = event.detail && typeof event.detail === 'object'
    ? event.detail
    : event.payload && typeof event.payload === 'object'
      ? event.payload
      : {};

  if (detail.message) {
    return detail.message;
  }
  if (event.message) {
    return event.message;
  }
  if (detail.title && detail.status) {
    return `${detail.title} · ${detail.status}`;
  }
  if (detail.phase && detail.status) {
    return `${detail.phase} · ${detail.status}`;
  }
  if (detail.command) {
    return detail.command;
  }
  if (event.vm && event.msg) {
    return `${event.vm}: ${String(event.msg).trim()}`;
  }
  if (typeof event.correct === 'boolean') {
    return event.correct ? 'Correct answer recorded.' : 'Incorrect answer recorded.';
  }
  if (detail.score !== undefined) {
    return `Score ${detail.score}`;
  }
  return '';
}


function formatTimestamp(ts) {
  if (!ts) {
    return '';
  }
  try {
    return new Date(ts * 1000).toLocaleTimeString();
  } catch {
    return '';
  }
}


export default function LiveEventTimeline({ title = 'Live Events', events = [], emptyMessage = 'Waiting for live events.' }) {
  return (
    <div className="mt-4 bg-background p-4 rounded border border-border">
      <h5 className="font-bold mb-3 text-primary">{title}</h5>
      {events.length > 0 ? (
        <div className="space-y-3">
          {events.map((event, index) => {
            const summary = summarizeEvent(event);
            const timestamp = formatTimestamp(event?.ts);
            return (
              <div key={`${event?.type || 'event'}-${event?.ts || index}-${index}`} className="rounded-lg border border-border bg-surface px-4 py-3 text-sm">
                <div className="flex items-start justify-between gap-3">
                  <div className="text-primary font-medium">{event?.type || 'event'}</div>
                  {timestamp && <div className="text-secondary text-xs uppercase tracking-[0.18em]">{timestamp}</div>}
                </div>
                {summary && <div className="text-secondary mt-2">{summary}</div>}
              </div>
            );
          })}
        </div>
      ) : (
        <div className="text-sm text-secondary">{emptyMessage}</div>
      )}
    </div>
  );
}