// Minimal XML/SVG parser — enough for the input corpus (svg, g, path, rect,
// circle, ellipse, line, polyline, polygon, defs). No DOM dependency so the
// whole track stays deterministic and installable from npm alone.

/**
 * @typedef {{tag:string, attrs:Record<string,string>, children:XmlNode[]}} XmlNode
 */

const TAG_RE = /<(\/)?([A-Za-z_][\w:.-]*)((?:\s+[\w:.-]+\s*=\s*(?:"[^"]*"|'[^']*'))*)\s*(\/)?>/g;
const ATTR_RE = /([\w:.-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')/g;

function parseAttrs(str) {
  const attrs = {};
  if (!str) return attrs;
  let m;
  ATTR_RE.lastIndex = 0;
  while ((m = ATTR_RE.exec(str))) attrs[m[1]] = m[2] !== undefined ? m[2] : m[3];
  return attrs;
}

/** Parse an SVG document into a tree. Comments/DOCTYPE/PIs are skipped. */
export function parseXml(src) {
  const clean = src
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/<\?[\s\S]*?\?>/g, '')
    .replace(/<!DOCTYPE[^>[]*(\[[\s\S]*?\])?[^>]*>/gi, '');

  const root = { tag: '#root', attrs: {}, children: [] };
  const stack = [root];
  let m;
  TAG_RE.lastIndex = 0;
  while ((m = TAG_RE.exec(clean))) {
    const [, closing, tag, attrStr, selfClose] = m;
    if (closing) {
      // pop to matching tag
      for (let i = stack.length - 1; i > 0; i--) {
        if (stack[i].tag === tag) { stack.length = i; break; }
      }
      continue;
    }
    const node = { tag, attrs: parseAttrs(attrStr), children: [] };
    stack[stack.length - 1].children.push(node);
    if (!selfClose) stack.push(node);
  }
  return root;
}

/** Find the first <svg> element in a parsed tree. */
export function findSvg(root) {
  const stack = [root];
  while (stack.length) {
    const n = stack.shift();
    if (n.tag === 'svg') return n;
    stack.push(...n.children);
  }
  return null;
}
