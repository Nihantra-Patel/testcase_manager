// eslint-disable-next-line no-control-regex
const ANSI_RE = /\x1b\[[0-9;]*[A-Za-z]/g

export function stripAnsi(str) {
  return (str || '').replace(ANSI_RE, '')
}

// Map a console line to a colour class (ported from the old test_runner.js
// _colourLine palette, tuned for the dark console background).
export function lineColor(line) {
  const s = line || ''
  if (/■|Stopped by user/.test(s)) return 'text-[#ff7b72] font-semibold'
  if (/✔|PASS\b|^OK\b/.test(s)) return 'text-[#3fb950]'
  if (/✖/.test(s)) return 'text-[#ff7b72]'
  if (/^FAIL\b|^ERROR\b|^AssertionError/.test(s)) return 'text-[#ff7b72] font-semibold'
  if (/^Traceback/.test(s)) return 'text-[#ffa657]'
  if (/^\s+File "|^\s+raise /.test(s)) return 'text-[#ffa657]'
  if (/^Running \d|^Ran \d/.test(s)) return 'text-[#79c0ff]'
  if (/^={3,}$|^-{3,}$/.test(s)) return 'text-[#6e7681]'
  if (/^FAILED\b/.test(s)) return 'text-[#ff7b72] font-bold'
  return 'text-[#e6edf3]'
}
