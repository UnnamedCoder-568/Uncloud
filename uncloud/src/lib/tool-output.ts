/** Tool results are data, not Markdown. Preserve paths and decoded stdout. */
export function formatToolOutput(output: string): string {
  try {
    const value: unknown = JSON.parse(output);
    if (value && typeof value === 'object' && !Array.isArray(value)
        && 'stdout' in value && typeof value.stdout === 'string') {
      const { stdout, ...details } = value;
      return stdout + (Object.keys(details).length
        ? `\n${JSON.stringify(details, null, 2)}` : '');
    }
    return JSON.stringify(value, null, 2);
  } catch {
    return output;
  }
}
