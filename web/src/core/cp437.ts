/**
 * Code page 437 (the original IBM PC set), which the ZIP format assumes for entry names unless they are flagged UTF-8.
 * `TextDecoder` has no cp437, so the upper half is a table; 0x00-0x7F are ASCII.
 */
const UPPER =
  'ÇüéâäàåçêëèïîìÄÅ' +
  'ÉæÆôöòûùÿÖÜ¢£¥₧ƒ' +
  'áíóúñÑªº¿⌐¬½¼¡«»' +
  '░▒▓│┤╡╢╖╕╣║╗╝╜╛┐' +
  '└┴┬├─┼╞╟╚╔╩╦╠═╬╧' +
  '╨╤╥╙╘╒╓╫╪┘┌█▄▌▐▀' +
  'αßΓπΣσµτΦΘΩδ∞φε∩' +
  '≡±≥≤⌠⌡÷≈°∙·√ⁿ²■\u00a0';

export const decodeCp437 = (bytes: Uint8Array): string => {
  let out = '';
  for (const b of bytes) out += b < 0x80 ? String.fromCharCode(b) : UPPER[b - 0x80]!;
  return out;
};
