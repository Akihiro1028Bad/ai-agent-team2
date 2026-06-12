"use client";

import mermaid from "mermaid";
import { useEffect, useId, useState } from "react";

mermaid.initialize({
  startOnLoad: false,
  theme: "base",
  fontFamily: "var(--font-jb), monospace",
  themeVariables: {
    background: "transparent",
    primaryColor: "#161a20",
    primaryBorderColor: "#2d333d",
    primaryTextColor: "#e7eaf0",
    lineColor: "#5cc8e6",
    secondaryColor: "#111419",
    tertiaryColor: "#111419",
    clusterBkg: "#111419",
    clusterBorder: "#232831",
    edgeLabelBackground: "#0b0d10",
    nodeTextColor: "#e7eaf0",
  },
});

export function Mermaid({ chart }: { chart: string }) {
  const rawId = useId().replace(/[:]/g, "");
  const [svg, setSvg] = useState<string>("");
  const [err, setErr] = useState<string>("");

  useEffect(() => {
    let active = true;
    mermaid
      .render(`mmd-${rawId}`, chart)
      .then(({ svg }) => active && setSvg(svg))
      .catch((e: unknown) => active && setErr(e instanceof Error ? e.message : "render error"));
    return () => {
      active = false;
    };
  }, [chart, rawId]);

  if (err) {
    return (
      <pre className="overflow-auto rounded-lg border p-3 font-mono text-[11px]" style={{ borderColor: "var(--color-line)", color: "var(--color-rose)" }}>
        {chart}
      </pre>
    );
  }
  return <div className="flex justify-center [&_svg]:h-auto [&_svg]:max-w-full" dangerouslySetInnerHTML={{ __html: svg }} />;
}
