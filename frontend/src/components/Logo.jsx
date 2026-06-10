export default function Logo({ size = 28 }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <defs>
        <linearGradient id="df-grad" x1="0" y1="0" x2="32" y2="32">
          <stop stopColor="#7c6cff" />
          <stop offset="1" stopColor="#38e8ff" />
        </linearGradient>
      </defs>
      {/* stacked "depth" layers */}
      <path
        d="M16 3 28 9.5 16 16 4 9.5 16 3Z"
        stroke="url(#df-grad)"
        strokeWidth="1.8"
        strokeLinejoin="round"
        opacity="0.95"
      />
      <path
        d="M5 15 16 21 27 15"
        stroke="url(#df-grad)"
        strokeWidth="1.8"
        strokeLinejoin="round"
        opacity="0.6"
      />
      <path
        d="M5 21 16 27 27 21"
        stroke="url(#df-grad)"
        strokeWidth="1.8"
        strokeLinejoin="round"
        opacity="0.3"
      />
    </svg>
  );
}
