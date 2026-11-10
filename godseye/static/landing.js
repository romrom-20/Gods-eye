const svg = document.getElementById("hero-network");
if (svg) {
  const ns = "http://www.w3.org/2000/svg";
  const layers = [
    [60, 9],
    [190, 7],
    [330, 7],
    [460, 6],
  ];
  const nodes = layers.map(([x, n]) =>
    Array.from({ length: n }, (_, i) => [x, 50 + (i * 220) / (n - 1)]),
  );
  function shape(tag, attrs) {
    const e = document.createElementNS(ns, tag);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
    svg.append(e);
  }
  for (let l = 0; l < 3; l++)
    nodes[l].forEach(([x, y], a) =>
      nodes[l + 1].forEach(([xx, yy], b) => {
        const selected = l === 2 && b === 1 && a % 2 === 0;
        shape("path", {
          d: `M${x} ${y} C${x + 60} ${y},${xx - 60} ${yy},${xx} ${yy}`,
          fill: "none",
          stroke: selected ? "#ce6038" : "#a9b99b",
          "stroke-width": selected ? 2 : 0.7,
          opacity: selected ? 0.9 : 0.35,
          "stroke-dasharray": selected ? "5 5" : "none",
        });
      }),
    );
  nodes.forEach((layer, l) =>
    layer.forEach(([cx, cy], i) => {
      shape("circle", {
        cx,
        cy,
        r: l === 3 && i === 1 ? 9 : 5,
        fill: l === 3 && i === 1 ? "#ce6038" : "#6e8462",
        stroke: "#e9eddf",
        "stroke-width": 2,
      });
    }),
  );
}
const copy = document.getElementById("copy-install");
if (copy)
  copy.onclick = async () => {
    try {
      await navigator.clipboard.writeText(
        document.querySelector(".install pre").textContent,
      );
      document.getElementById("copy-status").textContent = "Commands copied.";
    } catch {
      document.getElementById("copy-status").textContent =
        "Select and copy the commands above.";
    }
  };
