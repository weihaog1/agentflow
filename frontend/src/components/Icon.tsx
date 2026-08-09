type IconName =
  | 'arrow'
  | 'check'
  | 'chevron'
  | 'close'
  | 'copy'
  | 'document'
  | 'evidence'
  | 'refresh'
  | 'run'
  | 'upload';

interface IconProps {
  name: IconName;
  size?: number;
}

export function Icon({ name, size = 16 }: IconProps) {
  const common = {
    width: size,
    height: size,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.8,
    strokeLinecap: 'square' as const,
    strokeLinejoin: 'miter' as const,
    'aria-hidden': true,
  };

  if (name === 'arrow') {
    return (
      <svg {...common}>
        <path d="M5 12h13M13 6l6 6-6 6" />
      </svg>
    );
  }
  if (name === 'check') {
    return (
      <svg {...common}>
        <path d="m5 12 4 4L19 6" />
      </svg>
    );
  }
  if (name === 'chevron') {
    return (
      <svg {...common}>
        <path d="m8 10 4 4 4-4" />
      </svg>
    );
  }
  if (name === 'close') {
    return (
      <svg {...common}>
        <path d="M6 6l12 12M18 6 6 18" />
      </svg>
    );
  }
  if (name === 'copy') {
    return (
      <svg {...common}>
        <rect x="8" y="8" width="11" height="11" />
        <path d="M16 8V5H5v11h3" />
      </svg>
    );
  }
  if (name === 'document') {
    return (
      <svg {...common}>
        <path d="M6 3h8l4 4v14H6z" />
        <path d="M14 3v5h4M9 12h6M9 16h6" />
      </svg>
    );
  }
  if (name === 'evidence') {
    return (
      <svg {...common}>
        <circle cx="11" cy="11" r="6" />
        <path d="m16 16 5 5M11 8v6M8 11h6" />
      </svg>
    );
  }
  if (name === 'refresh') {
    return (
      <svg {...common}>
        <path d="M19 7V3l-2 2a8 8 0 1 0 2 9" />
        <path d="M19 3h-4" />
      </svg>
    );
  }
  if (name === 'run') {
    return (
      <svg {...common}>
        <path d="M7 4v16l12-8z" />
      </svg>
    );
  }
  return (
    <svg {...common}>
      <path d="M12 16V4M7 9l5-5 5 5M5 15v5h14v-5" />
    </svg>
  );
}
