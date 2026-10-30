// Builds the private test set: each staff-quote photo plus the lines on its Zoho
// estimate as it stands now (after staff edited it), which is the answer key.
//
//   cd ~/Projects/prezr-dispatch && railway run -- node ~/Projects/paizah-photo-quote/eval/export_prezr_set.ts
//
// Reads only: one GET per estimate through dispatch's own Zoho door (so the
// daily-budget breaker and the call log apply) and one signed GET per photo.
// Writes only into paizah-photo-quote/data/prezr/, which git ignores. These are
// customers' clothes: they stay on this Mac and never go into the submission.
import { mkdir, writeFile, access } from 'node:fs/promises';
import { q } from '/Users/sujith/Projects/prezr-dispatch/packages/worker/src/db.ts';
import { books } from '/Users/sujith/Projects/prezr-dispatch/packages/worker/src/adapters/zoho.ts';
import { config } from '/Users/sujith/Projects/prezr-dispatch/packages/worker/src/zoho-sync.ts';
import { signedPhotoUrl } from '/Users/sujith/Projects/prezr-dispatch/packages/worker/src/photo-sign.ts';

const OUT = '/Users/sujith/Projects/paizah-photo-quote/data/prezr';
await mkdir(OUT, { recursive: true });

const cfg = await config();
if (!cfg?.organization_id) throw new Error('no back office config');

type Row = { id: string; tenant_id: string; brand: string; photo_key: string; estimate_id: string;
             estimate_number: string | null; created_at: string; result: unknown };
const rows = await q<Row>(
  `select id, tenant_id, brand, photo_key, estimate_id, estimate_number, created_at, result
     from dispatch.staff_quote
    where photo_key is not null and state = 'confirmed' and estimate_id is not null
    order by created_at`, []);

let done = 0, skipped = 0, failed = 0;
for (const r of rows) {
  // The answer file is written last, so its presence means the row is complete.
  try {
    await access(`${OUT}/${r.id}.json`);
    skipped += 1;
    continue;
  } catch { /* not yet exported */ }
  try {
    const est = await books<{ estimate: {
      estimate_number: string; status: string; location_name?: string; total: number;
      line_items: Array<{ item_id?: string; name: string; description?: string; quantity: number; rate: number; item_total: number }>;
    } }>(cfg.connector_slug, cfg.organization_id, { path: `/estimates/${r.estimate_id}` });

    // photo_key holds every photo of the lot, comma-joined (up to five per quote).
    const photos: string[] = [];
    for (const [n, key] of r.photo_key.split(',').entries()) {
      const [tenant, file] = key.split('/');
      const { url } = signedPhotoUrl(tenant, file.replace(/\.jpg$/, ''), 'get');
      const res = await fetch(url);
      if (!res.ok) throw new Error(`photo ${n} ${res.status}`);
      const name = n === 0 ? `${r.id}.jpg` : `${r.id}_${n}.jpg`;
      await writeFile(`${OUT}/${name}`, new Uint8Array(await res.arrayBuffer()));
      photos.push(name);
    }

    const e = est.estimate;
    await writeFile(`${OUT}/${r.id}.json`, JSON.stringify({
      brand: r.brand,
      photos,
      created_at: r.created_at,
      estimate_number: e.estimate_number,
      status: e.status,
      location: e.location_name ?? null,
      total: e.total,
      lines: e.line_items.map((l) => ({ item_id: l.item_id ?? null, name: l.name, description: l.description ?? '',
                                         quantity: l.quantity, rate: l.rate, total: l.item_total })),
      bot_first_read: r.result,
    }, null, 2));
    done += 1;
  } catch (err) {
    failed += 1;
    console.error(r.id, String(err).slice(0, 200));
  }
}
console.log(`exported ${done}, already there ${skipped}, failed ${failed}, of ${rows.length}`);
process.exit(0);
