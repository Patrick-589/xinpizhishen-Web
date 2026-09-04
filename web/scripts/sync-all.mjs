console.log(`[${new Date().toISOString()}] Starting disclosure data sync`);

await import('./sync-company-announcements.mjs');
await import('./sync-peer-announcements.mjs');
await import('./sync-rules.mjs');
await import('./sync-csrc-rules.mjs');

console.log(`[${new Date().toISOString()}] Disclosure data sync completed`);
