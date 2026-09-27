export type MindmapNode = { text: string; children: MindmapNode[] };

export function parseMindmap(markdown: string): MindmapNode[] {
  const roots: MindmapNode[] = [];
  const stack: Array<{ level: number; node: MindmapNode }> = [];

  for (const raw of markdown.replace(/\r\n?/g, "\n").split("\n")) {
    const heading = raw.match(/^\s*(#{1,6})\s+(.+?)\s*#*\s*$/);
    const list = raw.match(/^(\s*)[-*+]\s+(.+)$/);
    const ordered = raw.match(/^(\s*)\d+[.)]\s+(.+)$/);
    if (!heading && !list && !ordered) continue;
    const level = heading
      ? heading[1].length
      : 7 + Math.floor((list ?? ordered)![1].replace(/\t/g, "  ").length / 2);
    const text = (heading ? heading[2] : (list ?? ordered)![2])
      .replace(/\*\*|__|`/g, "")
      .trim();
    if (!text) continue;
    const node: MindmapNode = { text, children: [] };
    while (stack.length && stack[stack.length - 1].level >= level) stack.pop();
    if (stack.length) stack[stack.length - 1].node.children.push(node);
    else roots.push(node);
    stack.push({ level, node });
  }
  return roots;
}
