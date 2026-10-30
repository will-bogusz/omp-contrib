// The text half of run.mjs's place() helpers: pure edits of a PR body's Markdown, shared with shapes.mjs's
// fromFigures and its tests.

// The table whose header line starts with `first`: the body's lines and the table's first and last index.
function tableAt(body, first) {
  const lines = body.split("\n"), s = lines.findIndex(l => l.startsWith(first));
  if (s < 0) throw new Error(`no table line starts with ${JSON.stringify(first)}`);
  let e = s;
  while (lines[e + 1]?.startsWith("|")) e++;
  return { lines, s, e };
}

export const details = (summary, md) => `<details><summary>${summary}</summary>\n\n${md.trim()}\n\n</details>`;
export function table(body, first) {
  const { lines, s, e } = tableAt(body, first);
  return lines.slice(s, e + 1).join("\n");
}
export function swapTable(body, first, md) {
  const { lines, s, e } = tableAt(body, first);
  return [...lines.slice(0, s), md, ...lines.slice(e + 1)].join("\n");
}
export function replace(body, old, nu) {
  const n = body.split(old).length - 1;
  if (n !== 1) throw new Error(`replace: ${JSON.stringify(old.slice(0, 60))} occurs ${n} times, need exactly 1`);
  return body.replace(old, () => nu);
}
