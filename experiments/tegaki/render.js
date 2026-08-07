// Deterministic SVG -> PNG rasterization for the contact sheets (report §7.1, §15).
// resvg-js, with sharp as the fallback.

import { Resvg } from '@resvg/resvg-js';

export function svgToPng(svgText, widthPx) {
  const r = new Resvg(svgText, { fitTo: { mode: 'width', value: widthPx }, background: 'white' });
  return r.render().asPng();
}

/** Overlay: recovered centerlines in red over the input fill in grey at 40%. */
export function overlaySvg(inputSvgText, outputSvgText) {
  const vb = /viewBox="([^"]*)"/.exec(inputSvgText);
  const inner = (s) => s.replace(/^[\s\S]*?<svg[^>]*>/, '').replace(/<\/svg>\s*$/, '');
  const grey = inner(inputSvgText)
    .replace(/fill="(?!none)[^"]*"/g, 'fill="#888888"')
    .replace(/fill-opacity="[^"]*"/g, '');
  const red = inner(outputSvgText)
    .replace(/stroke="[^"]*"/g, 'stroke="#e00000"')
    .replace(/stroke-opacity="[^"]*"/g, '')
    .replace(/fill="(?!none)[^"]*"/g, 'fill="#e00000"')
    .replace(/stroke-width="[^"]*"/g, 'stroke-width="1.2"');
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" version="1.1"${vb ? ` viewBox="${vb[1]}"` : ''}>` +
    `<g opacity="0.4">${grey}</g>${red}</svg>`
  );
}
