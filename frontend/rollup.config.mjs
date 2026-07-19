import resolve from '@rollup/plugin-node-resolve';
import terser from '@rollup/plugin-terser';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const dev = process.env.ROLLUP_WATCH;

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const cardDir = path.resolve(__dirname, '../custom_components/victron_charge_control/static');
const cardFile = path.join(cardDir, 'victron-charge-controller-card.js');

export default {
  input: 'src/victron-charge-controller-card.js',
  output: {
    file: cardFile,
    format: 'es',
    sourcemap: dev ? true : false,
  },
  plugins: [
    resolve(),
    !dev && terser({ output: { comments: false } }),
  ],
};