// Counts staff quotes that carry a photo. Read-only; prints counts only.
//   cd ~/Projects/prezr-dispatch && railway run -- node ~/Projects/paizah-photo-quote/eval/count_photos.mjs
import { createRequire } from "node:module";
const require = createRequire(process.cwd() + "/package.json");
const { Client } = require("pg");

const db = new Client({ connectionString: process.env.DATABASE_URL });
await db.connect();
await db.query("set default_transaction_read_only = on");
const { rows } = await db.query(`
  select brand, photo_state, state, count(*)::int as quotes,
         count(distinct estimate_id)::int as estimates,
         min(created_at)::date as first, max(created_at)::date as last
    from dispatch.staff_quote
   where photo_key is not null
   group by 1, 2, 3
   order by 1, 2, 3`);
console.table(rows);
await db.end();
