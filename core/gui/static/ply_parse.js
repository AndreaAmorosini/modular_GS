/* Binary PLY header parsing for the SfM point cloud viewer.
   Pure JS, no dependencies, so it can be unit-tested outside the browser. */

/* Parse a binary_little_endian PLY header. Returns:
   { vertexCount, props: [{name, size, offset}], stride, dataStart, isAscii } */
export function parsePlyHeader(buffer) {
  const bytes = new Uint8Array(buffer);
  const maxHead = Math.min(bytes.length, 65536);
  let headerText = "";
  for (let i = 0; i < maxHead; i++) headerText += String.fromCharCode(bytes[i]);
  const endMarker = headerText.indexOf("end_header");
  if (endMarker < 0) throw new Error("PLY header not found (file is ASCII or corrupt?)");

  const headerLines = headerText.slice(0, endMarker).split("\n");
  const sizes = { float: 4, uchar: 1, double: 8, int: 4, uint: 4, short: 2, ushort: 2, char: 1 };
  let vertexCount = 0;
  let isAscii = false;
  let stride = 0;
  const props = [];
  let inVertex = false;

  for (const line of headerLines) {
    const parts = line.trim().split(/\s+/);
    if (parts[0] === "format") {
      isAscii = parts[1] === "ascii";
    } else if (parts[0] === "element") {
      inVertex = parts[1] === "vertex";
      if (inVertex) {
        vertexCount = parseInt(parts[2], 10);
      } else if (props.length) {
        // a second element started after vertex: stop collecting properties
        inVertex = false;
        break;
      }
    } else if (parts[0] === "property" && inVertex) {
      const type = parts[1];
      // list properties (e.g. "property list uchar int vertex_indices") have
      // variable size: they must not appear in a vertex element we can read
      if (type === "list") throw new Error("Variable-size PLY properties are not supported.");
      props.push({ name: parts[2], size: sizes[type] ?? 4, offset: stride });
      stride += sizes[type] ?? 4;
    }
  }

  const dataStart = endMarker + "end_header".length + 1;
  return { vertexCount, props, stride, dataStart, isAscii };
}

/* Extract positions (Float32Array) and colors (Float32Array, 0..1) from a
   binary PLY buffer using a parsed header. Colors are returned only if
   red/green/blue uchar properties exist. */
export function extractPoints(buffer, header) {
  const { vertexCount, props, stride, dataStart } = header;
  const find = (name) => props.find((p) => p.name === name);
  const px = find("x"), py = find("y"), pz = find("z");
  const cr = find("red"), cg = find("green"), cb = find("blue");
  if (!px || !py || !pz) throw new Error("PLY has no x/y/z properties.");

  const positions = new Float32Array(vertexCount * 3);
  const colors = cr && cg && cb ? new Float32Array(vertexCount * 3) : null;

  const view = new DataView(buffer);
  for (let i = 0; i < vertexCount; i++) {
    const base = dataStart + i * stride;
    positions[i * 3] = view.getFloat32(base + px.offset, true);
    positions[i * 3 + 1] = view.getFloat32(base + py.offset, true);
    positions[i * 3 + 2] = view.getFloat32(base + pz.offset, true);
    if (colors) {
      colors[i * 3] = view.getUint8(base + cr.offset) / 255;
      colors[i * 3 + 1] = view.getUint8(base + cg.offset) / 255;
      colors[i * 3 + 2] = view.getUint8(base + cb.offset) / 255;
    }
  }
  return { positions, colors, vertexCount };
}
