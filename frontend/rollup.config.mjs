import resolve from '@rollup/plugin-node-resolve';
import terser from '@rollup/plugin-terser';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const dev = process.env.ROLLUP_WATCH;

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const cardDir = path.resolve(__dirname, '../custom_components/victron_charge_control/static');
const cardFile = path.join(cardDir, 'victron-charge-controller-card.js');
const manifestFile = path.resolve(
  __dirname,
  '../custom_components/victron_charge_control/manifest.json',
);
const versionModuleId = 'virtual:integration-version';
const resolvedVersionModuleId = `\0${versionModuleId}`;

function readIntegrationVersion() {
  const manifest = JSON.parse(readFileSync(manifestFile, 'utf8'));
  if (typeof manifest.version !== 'string' || !manifest.version.trim()) {
    throw new Error(`Missing integration version in ${manifestFile}`);
  }
  return manifest.version.trim();
}

const integrationVersionPlugin = {
  name: 'integration-version',
  buildStart() {
    this.addWatchFile(manifestFile);
  },
  resolveId(source) {
    return source === versionModuleId ? resolvedVersionModuleId : null;
  },
  load(id) {
    if (id !== resolvedVersionModuleId) return null;
    return `export const CARD_VERSION = ${JSON.stringify(readIntegrationVersion())};`;
  },
};

export default {
  input: 'src/victron-charge-controller-card.js',
  output: {
    file: cardFile,
    format: 'es',
    sourcemap: dev ? true : false,
  },
  plugins: [
    integrationVersionPlugin,
    resolve(),
    !dev && terser({ output: { comments: false } }),
  ],
};
