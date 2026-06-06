import {
	w as l,
	c as s,
	d as n,
	F as o,
	p as i,
	x as u,
	s as c,
	g as x,
	n as p,
	a as b,
} from "./index-BE68p4vw.js";
const d = /\x1b\[[0-9;]*[A-Za-z]/g;
function k(t) {
	return (t || "").replace(d, "");
}
function m(t) {
	const e = t || "";
	return /■|Stopped by user/.test(e)
		? "text-[#ff7b72] font-semibold"
		: /✔|PASS\b|^OK\b/.test(e)
		? "text-[#3fb950]"
		: /✖/.test(e)
		? "text-[#ff7b72]"
		: /^FAIL\b|^ERROR\b|^AssertionError/.test(e)
		? "text-[#ff7b72] font-semibold"
		: /^Traceback/.test(e) || /^\s+File "|^\s+raise /.test(e)
		? "text-[#ffa657]"
		: /^Running \d|^Ran \d/.test(e)
		? "text-[#79c0ff]"
		: /^={3,}$|^-{3,}$/.test(e)
		? "text-[#6e7681]"
		: /^FAILED\b/.test(e)
		? "text-[#ff7b72] font-bold"
		: "text-[#e6edf3]";
}
const _ = {
	__name: "Console",
	props: { lines: { type: Array, default: () => [] } },
	setup(t) {
		const e = t,
			r = b(null);
		return (
			l(
				() => e.lines.length,
				async () => {
					await p(), r.value && (r.value.scrollTop = r.value.scrollHeight);
				}
			),
			(g, y) => (
				s(),
				n(
					"div",
					{
						ref_key: "el",
						ref: r,
						class: "flex-1 overflow-y-auto whitespace-pre-wrap break-all bg-[#0d1117] px-4 py-3.5 font-mono text-xs leading-relaxed",
					},
					[
						(s(!0),
						n(
							o,
							null,
							i(
								t.lines,
								(a, f) => (
									s(),
									n(
										"div",
										{ key: f, class: u(c(m)(a.text)) },
										x(a.text || " "),
										3
									)
								)
							),
							128
						)),
					],
					512
				)
			)
		);
	},
};
export { _, k as s };
//# sourceMappingURL=Console-BDlHFzp2.js.map
