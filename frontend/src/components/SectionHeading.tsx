import type { ReactNode } from 'react';

interface SectionHeadingProps {
  id?: string;
  index: string;
  title: string;
  note?: string;
  action?: ReactNode;
  level?: 'h2' | 'h3';
}

export function SectionHeading({
  id,
  index,
  title,
  note,
  action,
  level = 'h2',
}: SectionHeadingProps) {
  const Heading = level;
  return (
    <div className="section-heading">
      <div className="section-heading__identity">
        <span className="section-heading__index">{index}</span>
        <div>
          <Heading id={id}>{title}</Heading>
          {note ? <p>{note}</p> : null}
        </div>
      </div>
      {action ? <div className="section-heading__action">{action}</div> : null}
    </div>
  );
}
