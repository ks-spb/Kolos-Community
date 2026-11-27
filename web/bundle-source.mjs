/** Strip this project's one-line module declarations for offline bundles.
 * This is not a general JavaScript parser. Keep LF/CRLF handling in one place.
 */
export function stripModuleSyntax(source) {
  return source.replace(/^import[^\r\n]*;[ \t]*(?:\r?\n|$)/gm, '')
    .replace(/^export /gm, '');
}
